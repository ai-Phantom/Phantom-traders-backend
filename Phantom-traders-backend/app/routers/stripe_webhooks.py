"""
routers/stripe_webhooks.py
Handles Stripe webhook events to sync subscription state with Supabase.

Events handled:
  - checkout.session.completed  → activate plan after payment
  - customer.subscription.created/updated → sync plan on change
  - customer.subscription.deleted → downgrade to free
  - invoice.payment_succeeded → keep plan active on renewal

Plan is written to user_profiles.plan and Discord roles are synced
automatically if the user has linked their Discord account.
"""

from fastapi import APIRouter, Request, HTTPException
from app.database import get_supabase
from app.config import get_settings
import stripe
import logging
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_stripe():
    s = get_settings()
    stripe.api_key = s.STRIPE_SECRET_KEY
    return stripe


def price_to_plan(price_id: str) -> str:
    """Map a Stripe price ID to a plan name using config."""
    s = get_settings()
    mapping = {}

    # Build mapping from settings (safely — these may not all be configured yet)
    for attr, plan in [
        ("STRIPE_PRICE_PRO_MONTHLY",   "pro"),
        ("STRIPE_PRICE_PRO_ANNUAL",    "pro"),
        ("STRIPE_PRICE_ELITE_MONTHLY", "elite"),
        ("STRIPE_PRICE_ELITE_ANNUAL",  "elite"),
    ]:
        val = getattr(s, attr, None)
        if val:
            mapping[val] = plan

    if price_id in mapping:
        return mapping[price_id]

    # Fallback: try to resolve from Stripe product metadata/name
    try:
        st = get_stripe()
        price = st.Price.retrieve(price_id, expand=["product"])
        product = price.product if hasattr(price, "product") else {}
        if isinstance(product, str):
            product = st.Product.retrieve(product)

        # Check product metadata
        meta_plan = getattr(product, "metadata", {}).get("plan", "")
        if meta_plan in ("pro", "elite"):
            return meta_plan

        # Check product name
        name = getattr(product, "name", "").lower()
        if "elite" in name or "all access" in name or "expert" in name:
            return "elite"
        if "pro" in name or "portfolio" in name:
            return "pro"
    except Exception as e:
        logger.warning(f"Could not resolve plan for price {price_id}: {e}")

    return "pro"  # default for any paid plan


def find_user_id_from_metadata(data: dict) -> str | None:
    """Extract supabase_user_id from Stripe object metadata."""
    # Check direct metadata
    uid = (data.get("metadata") or {}).get("supabase_user_id")
    if uid:
        return uid
    # Check subscription_data metadata (set during checkout creation)
    uid = (data.get("subscription_data") or {}).get("metadata", {}).get("supabase_user_id")
    return uid


def find_user_by_customer(sb, customer_id: str) -> str | None:
    """Look up user by stripe_customer_id in user_profiles."""
    if not customer_id:
        return None
    try:
        result = sb.table("user_profiles") \
            .select("id") \
            .eq("stripe_customer_id", customer_id) \
            .limit(1) \
            .execute()
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
    except Exception as e:
        logger.warning(f"find_user_by_customer error: {e}")
    return None


def find_user_by_email(sb, email: str) -> str | None:
    """Look up user by email in user_profiles."""
    if not email:
        return None
    try:
        result = sb.table("user_profiles") \
            .select("id") \
            .eq("email", email) \
            .limit(1) \
            .execute()
        if result.data and len(result.data) > 0:
            return result.data[0]["id"]
    except Exception as e:
        logger.warning(f"find_user_by_email error: {e}")
    return None


def resolve_user(sb, data: dict) -> str | None:
    """Try every method to find the Supabase user ID from a Stripe event."""
    # 1. From metadata
    uid = find_user_id_from_metadata(data)
    if uid:
        return uid

    # 2. From stripe_customer_id
    customer_id = data.get("customer")
    uid = find_user_by_customer(sb, customer_id)
    if uid:
        return uid

    # 3. From email
    email = data.get("customer_email") or (data.get("customer_details") or {}).get("email")
    uid = find_user_by_email(sb, email)
    if uid:
        return uid

    return None


def update_user_plan(sb, user_id: str, plan: str, customer_id: str = None,
                     status: str = None, period_end: str = None):
    """Update plan and subscription fields in user_profiles."""
    update_data = {"plan": plan}

    if customer_id:
        update_data["stripe_customer_id"] = customer_id
    if status:
        update_data["subscription_status"] = status
    if period_end:
        update_data["subscription_end_date"] = period_end

    try:
        sb.table("user_profiles") \
            .update(update_data) \
            .eq("id", user_id) \
            .execute()
        logger.info(f"Updated {user_id} → plan={plan} status={status}")
        return True
    except Exception as e:
        logger.error(f"Failed to update user {user_id}: {e}")
        return False


async def try_sync_discord(sb, user_id: str, plan: str):
    """If user has Discord linked, sync their role."""
    try:
        profile = sb.table("user_profiles") \
            .select("discord_user_id") \
            .eq("id", user_id) \
            .single() \
            .execute()

        discord_id = profile.data.get("discord_user_id") if profile.data else None
        if discord_id:
            from app.routers.discord_sync import assign_discord_role
            await assign_discord_role(discord_id, plan)
            logger.info(f"Discord role synced for {user_id} → {plan}")
    except Exception as e:
        logger.warning(f"Discord sync failed for {user_id}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/stripe")
async def stripe_webhook(request: Request):
    """
    Stripe sends events here. We verify the signature, then update
    the user's plan in Supabase based on what happened.
    """
    s = get_settings()
    st = get_stripe()
    sb = get_supabase()

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify webhook signature
    try:
        event = st.Webhook.construct_event(
            payload, sig_header, s.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.error("Stripe webhook: invalid payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except st.error.SignatureVerificationError:
        logger.error("Stripe webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]
    logger.info(f"[STRIPE] {event_type} — {event.get('id', '?')}")

    # ── checkout.session.completed ─────────────────────────────
    if event_type == "checkout.session.completed":
        customer_id = data.get("customer")
        amount = data.get("amount_total") or 0

        # Get line items to determine plan
        plan = "pro"
        try:
            session = st.checkout.Session.retrieve(
                data["id"], expand=["line_items"]
            )
            line_items = session.line_items.data if session.line_items else []
            for item in line_items:
                pid = item.price.id if item.price else ""
                plan = price_to_plan(pid)
                break
        except Exception as e:
            logger.warning(f"Could not fetch line items: {e}")
            # Fallback from amount
            if amount >= 3500:
                plan = "elite"

        user_id = resolve_user(sb, data)
        if user_id:
            update_user_plan(sb, user_id, plan, customer_id, status="active")
            await try_sync_discord(sb, user_id, plan)
        else:
            logger.warning(
                f"checkout.session.completed — no user found. "
                f"customer={customer_id} email={data.get('customer_email')}"
            )

    # ── customer.subscription.created / updated ────────────────
    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = data.get("customer")
        sub_status = data.get("status", "")  # active, past_due, canceled, etc.

        # Safely get subscription items
        items = []
        try:
            items_obj = data.get("items")
            if items_obj and hasattr(items_obj, "data"):
                items = items_obj.data
            elif isinstance(items_obj, dict):
                items = items_obj.get("data", [])
        except Exception:
            pass

        plan = "pro"
        for item in items:
            pid = ""
            if hasattr(item, "price") and item.price:
                pid = item.price.id if hasattr(item.price, "id") else item.get("price", {}).get("id", "")
            elif isinstance(item, dict):
                pid = item.get("price", {}).get("id", "")
            if pid:
                plan = price_to_plan(pid)
                break

        # Safely get period end
        period_end = None
        try:
            raw_end = data.get("current_period_end")
            if raw_end:
                period_end = datetime.fromtimestamp(int(raw_end)).isoformat()
        except Exception:
            pass

        user_id = find_user_by_customer(sb, customer_id)

        if sub_status in ("active", "trialing"):
            if user_id:
                update_user_plan(sb, user_id, plan, customer_id,
                                 status="active", period_end=period_end)
                await try_sync_discord(sb, user_id, plan)
            else:
                logger.warning(f"subscription event — no user for customer={customer_id}")

        elif sub_status in ("canceled", "unpaid", "past_due"):
            if user_id:
                update_user_plan(sb, user_id, "free", customer_id,
                                 status=sub_status, period_end=period_end)
                await try_sync_discord(sb, user_id, "free")
                logger.info(f"Downgraded {user_id} to free (subscription {sub_status})")

    # ── customer.subscription.deleted ──────────────────────────
    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user_id = find_user_by_customer(sb, customer_id)
        if user_id:
            update_user_plan(sb, user_id, "free", customer_id, status="canceled")
            await try_sync_discord(sb, user_id, "free")
            logger.info(f"Subscription deleted — {user_id} downgraded to free")

    # ── invoice.payment_succeeded (renewal) ────────────────────
    elif event_type == "invoice.payment_succeeded":
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        if subscription_id:
            # Get plan from invoice line items
            plan = "pro"
            lines = []
            try:
                lines_obj = data.get("lines")
                if lines_obj and hasattr(lines_obj, "data"):
                    lines = lines_obj.data
                elif isinstance(lines_obj, dict):
                    lines = lines_obj.get("data", [])
            except Exception:
                pass

            for line in lines:
                pid = ""
                if hasattr(line, "price") and line.price:
                    pid = line.price.id if hasattr(line.price, "id") else ""
                elif isinstance(line, dict):
                    pid = line.get("price", {}).get("id", "")
                if pid:
                    plan = price_to_plan(pid)
                    break

            user_id = find_user_by_customer(sb, customer_id)
            if user_id:
                update_user_plan(sb, user_id, plan, customer_id, status="active")

    return {"status": "ok"}
