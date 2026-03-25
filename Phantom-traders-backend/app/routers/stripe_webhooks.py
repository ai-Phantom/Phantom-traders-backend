"""
routers/stripe_webhooks.py
Handles Stripe webhook events to sync subscription state with Supabase.
Includes referral conversion tracking with tiered credits:
  - Pro upgrade   → $5 credit to referrer
  - Elite upgrade → $10 credit to referrer
  - Discord referral (active Pro/Elite member) → $5 credit
"""

from fastapi import APIRouter, Request, HTTPException
from app.database import get_supabase
from app.config import get_settings
from app.routers.email_service import send_upgrade_email
import stripe
import logging
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Credit amounts by plan ────────────────────────────────────
REFERRAL_CREDITS = {
    "pro":     5,
    "elite":   10,
    "discord": 5,
}

PLAN_AMOUNTS = {
    "price_1TEtzRPddnEAOUngGm0Ri56o": ("pro",   "$20.00", "monthly"),
    "price_1TEtzRPddnEAOUngsJ9zcwkT": ("elite",  "$50.00", "monthly"),
    "price_1TEtzRPddnEAOUngVca0PJAu": ("pro",   "$199.00", "annual"),
    "price_1TEtzQPddnEAOUngFbNfRqQe": ("elite",  "$499.00", "annual"),
}


# ── Helpers ───────────────────────────────────────────────────

def get_stripe():
    s = get_settings()
    stripe.api_key = s.STRIPE_SECRET_KEY
    return stripe


def price_to_plan(price_id: str) -> str:
    s = get_settings()
    mapping = {}
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
    try:
        st = get_stripe()
        price = st.Price.retrieve(price_id, expand=["product"])
        product = price.product if hasattr(price, "product") else {}
        if isinstance(product, str):
            product = st.Product.retrieve(product)
        meta_plan = getattr(product, "metadata", {}).get("plan", "")
        if meta_plan in ("pro", "elite"):
            return meta_plan
        name = getattr(product, "name", "").lower()
        if "elite" in name or "all access" in name:
            return "elite"
        if "pro" in name or "portfolio" in name:
            return "pro"
    except Exception as e:
        print(f"Could not resolve plan for price {price_id}: {e}")
    return "pro"


def find_user_id_from_metadata(data: dict) -> str | None:
    uid = (data.get("metadata") or {}).get("supabase_user_id")
    if uid:
        return uid
    uid = (data.get("subscription_data") or {}).get("metadata", {}).get("supabase_user_id")
    return uid


def find_user_by_customer(sb, customer_id: str) -> str | None:
    if not customer_id:
        return None
    try:
        result = sb.table("user_profiles").select("id").eq("stripe_customer_id", customer_id).limit(1).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        print(f"find_user_by_customer error: {e}")
    return None


def find_user_by_email(sb, email: str) -> str | None:
    if not email:
        return None
    try:
        result = sb.table("user_profiles").select("id").eq("email", email).limit(1).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        print(f"find_user_by_email error: {e}")
    return None


def resolve_user(sb, data: dict) -> str | None:
    uid = find_user_id_from_metadata(data)
    if uid:
        return uid
    uid = find_user_by_customer(sb, data.get("customer"))
    if uid:
        return uid
    email = data.get("customer_email") or (data.get("customer_details") or {}).get("email")
    return find_user_by_email(sb, email)


def get_user_profile(sb, user_id: str) -> dict:
    try:
        result = sb.table("user_profiles").select("email, full_name, plan, discord_user_id").eq("id", user_id).single().execute()
        return result.data or {}
    except Exception:
        return {}


def update_user_plan(sb, user_id: str, plan: str, customer_id: str = None, status: str = None, period_end: str = None):
    update_data = {"plan": plan}
    if customer_id:
        update_data["stripe_customer_id"] = customer_id
    if status:
        update_data["subscription_status"] = status
    if period_end:
        update_data["subscription_end_date"] = period_end
    try:
        sb.table("user_profiles").update(update_data).eq("id", user_id).execute()
        print(f"Updated {user_id} → plan={plan} status={status}")
        return True
    except Exception as e:
        print(f"Failed to update user {user_id}: {e}")
        return False


async def try_sync_discord(sb, user_id: str, plan: str):
    try:
        profile = sb.table("user_profiles").select("discord_user_id").eq("id", user_id).single().execute()
        discord_id = profile.data.get("discord_user_id") if profile.data else None
        if discord_id:
            from app.routers.discord_sync import assign_discord_role
            await assign_discord_role(discord_id, plan)
            print(f"Discord role synced for {user_id} → {plan}")
    except Exception as e:
        print(f"Discord sync failed for {user_id}: {e}")


def fire_upgrade_email(sb, user_id: str, plan: str, price_id: str):
    try:
        profile = get_user_profile(sb, user_id)
        email = profile.get("email")
        full_name = profile.get("full_name") or email or "Trader"
        first_name = full_name.split()[0].capitalize()
        print(f"DEBUG fire_upgrade_email: price_id={price_id!r} plan={plan!r}")
        if price_id and price_id in PLAN_AMOUNTS:
            plan_info = PLAN_AMOUNTS[price_id]
        else:
            plan_info = (plan, "$50.00" if plan == "elite" else "$20.00", "monthly")
        print(f"DEBUG plan_info: {plan_info}")
        _, amount, billing = plan_info
        send_upgrade_email(email, first_name, plan, amount, billing)
        print(f"Upgrade email sent to {email} → {plan}")
    except Exception as e:
        print(f"Upgrade email failed (non-fatal): {e}")


def process_referral_conversion(sb, referred_user_id: str, plan: str):
    """
    When a referred user upgrades, find their referral record,
    mark it converted, calculate credit, and add to referrer's balance.

    Credit rules:
      - Pro upgrade   → $5
      - Elite upgrade → $10
      - Discord referral (referrer is active Pro/Elite + in Discord) → $5
    """
    try:
        # Find the referral record for this user
        result = sb.table("referrals") \
            .select("*") \
            .eq("referred_id", referred_user_id) \
            .eq("converted", False) \
            .limit(1) \
            .execute()

        if not result.data:
            print(f"No unconverted referral found for user {referred_user_id}")
            return

        referral = result.data[0]
        referrer_id = referral.get("referrer_id")
        referral_type = referral.get("referral_type", "web")

        if not referrer_id:
            print("Referral has no referrer_id — skipping credit")
            return

        # Get referrer profile to check eligibility
        referrer_profile = get_user_profile(sb, referrer_id)
        referrer_plan = referrer_profile.get("plan", "free")
        referrer_discord = referrer_profile.get("discord_user_id")

        # Calculate credit amount
        credit = 0
        if referral_type == "discord":
            # Discord referral: referrer must be active Pro/Elite AND in Discord
            if referrer_plan in ("pro", "elite") and referrer_discord:
                credit = REFERRAL_CREDITS["discord"]
                print(f"Discord referral credit: ${credit} to {referrer_id}")
            else:
                print(f"Discord referral ineligible — referrer plan={referrer_plan}, discord={bool(referrer_discord)}")
                credit = 0
        else:
            # Web referral: credit based on what the referred user upgraded to
            credit = REFERRAL_CREDITS.get(plan, 0)
            print(f"Web referral credit: ${credit} ({plan}) to {referrer_id}")

        # Mark referral as converted
        sb.table("referrals").update({
            "converted":      True,
            "converted_at":   datetime.utcnow().isoformat(),
            "converted_plan": plan,
            "credit_amount":  credit,
        }).eq("id", referral["id"]).execute()

        # Add credit to referrer's balance (if credit > 0)
        if credit > 0:
            # Increment referral_credits on user_profiles
            current = referrer_profile.get("referral_credits") or 0
            sb.table("user_profiles").update({
                "referral_credits": current + credit
            }).eq("id", referrer_id).execute()

            print(f"✓ ${credit} credit added to referrer {referrer_id} (total: ${current + credit})")

            # Mark credit as applied
            sb.table("referrals").update({
                "credit_applied":    True,
                "credit_applied_at": datetime.utcnow().isoformat(),
            }).eq("id", referral["id"]).execute()

    except Exception as e:
        print(f"Referral conversion error (non-fatal): {e}")


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/stripe")
async def stripe_webhook(request: Request):
    s = get_settings()
    st = get_stripe()
    sb = get_supabase()

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = st.Webhook.construct_event(payload, sig_header, s.STRIPE_WEBHOOK_SECRET)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except st.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]
    print(f"[STRIPE] {event_type} — {event.get('id', '?')}")

    # ── checkout.session.completed ─────────────────────────────
    if event_type == "checkout.session.completed":
        customer_id = data.get("customer")
        amount = data.get("amount_total") or 0

        plan = "pro"
        price_id = ""
        try:
            session = st.checkout.Session.retrieve(data["id"], expand=["line_items"])
            line_items = session.line_items.data if session.line_items else []
            for item in line_items:
                price_id = item.price.id if item.price else ""
                plan = price_to_plan(price_id)
                break
        except Exception as e:
            print(f"Could not fetch line items: {e}")
            if amount >= 3500:
                plan = "elite"

        user_id = resolve_user(sb, data)
        if user_id:
            update_user_plan(sb, user_id, plan, customer_id, status="active")
            await try_sync_discord(sb, user_id, plan)
            fire_upgrade_email(sb, user_id, plan, price_id)
            # ── Process referral conversion ──
            process_referral_conversion(sb, user_id, plan)
        else:
            print(f"checkout.session.completed — no user found. customer={customer_id}")

    # ── customer.subscription.created / updated ────────────────
    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = data.get("customer")
        sub_status = data.get("status", "")

        plan = "pro"
        price_id = ""
        try:
            items_data = []
            if hasattr(data, 'items') and hasattr(data.items, 'data'):
                items_data = data.items.data
            else:
                items_obj = data.get("items") or {}
                if hasattr(items_obj, 'data'):
                    items_data = items_obj.data
                elif isinstance(items_obj, dict):
                    items_data = items_obj.get("data", [])
            for item in items_data:
                try:
                    if hasattr(item, 'price') and hasattr(item.price, 'id'):
                        price_id = item.price.id
                        plan = price_to_plan(price_id)
                    elif isinstance(item, dict):
                        price = item.get("price") or {}
                        price_id = price.get("id", "") if isinstance(price, dict) else getattr(price, 'id', '')
                        plan = price_to_plan(price_id)
                except Exception as e:
                    print(f"Error extracting price: {e}")
                break
        except Exception as e:
            print(f"Error processing subscription items: {e}")

        period_end = None
        try:
            raw_end = data.current_period_end if hasattr(data, 'current_period_end') else data.get("current_period_end")
            if raw_end:
                period_end = datetime.fromtimestamp(int(raw_end)).isoformat()
        except Exception as e:
            print(f"Error getting period_end: {e}")

        user_id = find_user_id_from_metadata(data) or find_user_by_customer(sb, customer_id)
        print(f"Subscription {sub_status}: customer={customer_id} user={user_id} plan={plan}")

        if sub_status in ("active", "trialing"):
            if user_id:
                update_user_plan(sb, user_id, plan, customer_id, status="active", period_end=period_end)
                await try_sync_discord(sb, user_id, plan)
        elif sub_status in ("canceled", "unpaid", "past_due"):
            if user_id:
                update_user_plan(sb, user_id, "free", customer_id, status=sub_status, period_end=period_end)
                await try_sync_discord(sb, user_id, "free")

    # ── customer.subscription.deleted ──────────────────────────
    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user_id = find_user_by_customer(sb, customer_id)
        if user_id:
            update_user_plan(sb, user_id, "free", customer_id, status="canceled")
            await try_sync_discord(sb, user_id, "free")

    # ── invoice.payment_succeeded (renewal) ────────────────────
    elif event_type == "invoice.payment_succeeded":
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        if subscription_id:
            plan = "pro"
            price_id = ""
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
                if hasattr(line, "price") and line.price:
                    price_id = line.price.id if hasattr(line.price, "id") else ""
                elif isinstance(line, dict):
                    price_id = line.get("price", {}).get("id", "")
                if price_id:
                    plan = price_to_plan(price_id)
                    break
            user_id = find_user_by_customer(sb, customer_id)
            if user_id:
                update_user_plan(sb, user_id, plan, customer_id, status="active")

    return {"status": "ok"}
