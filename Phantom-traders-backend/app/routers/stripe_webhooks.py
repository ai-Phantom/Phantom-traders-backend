"""
routers/stripe_webhooks.py
Listens for Stripe events and keeps our database in sync.

CRITICAL: This endpoint must verify Stripe's webhook signature.
Never process a webhook without verifying it — anyone could send fake events.

Events handled:
  checkout.session.completed       → payment succeeded, activate subscription
  customer.subscription.updated   → plan changed, upgrade/downgrade
  customer.subscription.deleted   → cancelled, downgrade to free
  invoice.payment_failed           → payment failed, mark as past_due
  invoice.payment_succeeded        → payment recovered, reactivate
"""

from fastapi import APIRouter, Request, HTTPException, Header
from app.database import get_supabase
from app.config import get_settings
from app.routers.discord_sync import assign_discord_role
import stripe
import logging
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


# Map Stripe Price IDs → plan names (loaded at request time)
def get_price_map():
    s = get_settings()
    return {
        s.STRIPE_PRICE_PRO_MONTHLY:   "pro",
        s.STRIPE_PRICE_PRO_ANNUAL:    "pro",
        s.STRIPE_PRICE_ELITE_MONTHLY: "elite",
        s.STRIPE_PRICE_ELITE_ANNUAL:  "elite",
    }


# ── Webhook entry point ───────────────────────────────────────────────────────

@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature")
):
    s = get_settings()
    stripe.api_key = s.STRIPE_SECRET_KEY

    payload = await request.body()

    # ── Verify signature ─────────────────────────────────────────────────────
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, s.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature")
        raise HTTPException(400, "Invalid signature")
    except Exception as e:
        logger.error(f"Webhook parsing error: {e}")
        raise HTTPException(400, "Webhook error")

    event_type = event["type"]
    data       = event["data"]["object"]
    logger.info(f"Stripe event: {event_type}")

    # ── Route events ─────────────────────────────────────────────────────────

    if event_type == "checkout.session.completed":
        await handle_checkout_completed(data)

    elif event_type == "customer.subscription.updated":
        await handle_subscription_updated(data)

    elif event_type == "customer.subscription.deleted":
        await handle_subscription_deleted(data)

    elif event_type in ("invoice.payment_failed",):
        await handle_payment_failed(data)

    elif event_type == "invoice.payment_succeeded":
        await handle_payment_succeeded(data)

    return {"received": True}


# ── Event handlers ────────────────────────────────────────────────────────────

async def handle_checkout_completed(session: dict):
    """Payment went through — activate subscription."""
    sb        = get_supabase()
    user_id   = session.get("metadata", {}).get("supabase_user_id")
    customer  = session.get("customer")

    if not user_id:
        # Try to look up by customer ID
        profile = sb.table("user_profiles") \
            .select("id") \
            .eq("stripe_customer_id", customer) \
            .single() \
            .execute()
        user_id = profile.data.get("id") if profile.data else None

    if not user_id:
        logger.error(f"checkout.session.completed: no user found for customer {customer}")
        return

    # Get the subscription to find the plan
    subscription_id = session.get("subscription")
    plan = "pro"  # default

    if subscription_id:
        price_map = get_price_map()
        sub = stripe.Subscription.retrieve(subscription_id, expand=["items.data.price"])
        price_id = sub["items"]["data"][0]["price"]["id"] if sub["items"]["data"] else None
        plan = price_map.get(price_id, "pro")
        end_date = datetime.fromtimestamp(sub["current_period_end"]).isoformat()
    else:
        end_date = None

    # Update user profile
    sb.table("user_profiles").update({
        "plan":                plan,
        "subscription_status": "active",
        "subscription_end_date": end_date,
        "stripe_customer_id":  customer,
    }).eq("id", user_id).execute()

    logger.info(f"User {user_id} activated on {plan} plan")

    # Sync Discord role
    await sync_discord_for_user(user_id, plan)


async def handle_subscription_updated(subscription: dict):
    """Subscription changed — upgrade, downgrade, or renewal."""
    sb       = get_supabase()
    customer = subscription.get("customer")

    profile = sb.table("user_profiles") \
        .select("id") \
        .eq("stripe_customer_id", customer) \
        .single() \
        .execute()

    user_id = profile.data.get("id") if profile.data else None
    if not user_id:
        logger.error(f"subscription.updated: no user for customer {customer}")
        return

    price_map = get_price_map()
    price_id  = subscription["items"]["data"][0]["price"]["id"] if subscription.get("items", {}).get("data") else None
    plan      = price_map.get(price_id, "free")
    status    = subscription.get("status", "inactive")
    end_date  = datetime.fromtimestamp(subscription["current_period_end"]).isoformat()

    sb.table("user_profiles").update({
        "plan":                  plan,
        "subscription_status":   status,
        "subscription_end_date": end_date,
        "cancel_at_period_end":  subscription.get("cancel_at_period_end", False),
    }).eq("id", user_id).execute()

    logger.info(f"User {user_id} subscription updated → {plan} ({status})")
    await sync_discord_for_user(user_id, plan)


async def handle_subscription_deleted(subscription: dict):
    """Subscription fully cancelled — drop to free."""
    sb       = get_supabase()
    customer = subscription.get("customer")

    profile = sb.table("user_profiles") \
        .select("id") \
        .eq("stripe_customer_id", customer) \
        .single() \
        .execute()

    user_id = profile.data.get("id") if profile.data else None
    if not user_id:
        return

    sb.table("user_profiles").update({
        "plan":                  "free",
        "subscription_status":   "cancelled",
        "subscription_end_date": None,
    }).eq("id", user_id).execute()

    logger.info(f"User {user_id} downgraded to free (cancelled)")
    await sync_discord_for_user(user_id, "free")


async def handle_payment_failed(invoice: dict):
    """Payment failed — mark past_due but keep access until period ends."""
    sb       = get_supabase()
    customer = invoice.get("customer")

    profile = sb.table("user_profiles") \
        .select("id") \
        .eq("stripe_customer_id", customer) \
        .single() \
        .execute()

    user_id = profile.data.get("id") if profile.data else None
    if not user_id:
        return

    sb.table("user_profiles").update({
        "subscription_status": "past_due",
    }).eq("id", user_id).execute()

    logger.warning(f"User {user_id} payment failed — marked past_due")


async def handle_payment_succeeded(invoice: dict):
    """Payment recovered after failure — reactivate."""
    sb           = get_supabase()
    customer     = invoice.get("customer")
    billing_reason = invoice.get("billing_reason", "")

    # Only handle renewals (not first payment — that's checkout.session.completed)
    if billing_reason not in ("subscription_cycle", "subscription_update"):
        return

    profile = sb.table("user_profiles") \
        .select("id, plan") \
        .eq("stripe_customer_id", customer) \
        .single() \
        .execute()

    user_id = profile.data.get("id") if profile.data else None
    if not user_id:
        return

    sb.table("user_profiles").update({
        "subscription_status": "active",
    }).eq("id", user_id).execute()

    logger.info(f"User {user_id} payment succeeded — reactivated")


# ── Discord sync helper ───────────────────────────────────────────────────────

async def sync_discord_for_user(user_id: str, plan: str):
    """Look up Discord ID for user and assign correct role."""
    sb = get_supabase()

    profile = sb.table("user_profiles") \
        .select("discord_user_id") \
        .eq("id", user_id) \
        .single() \
        .execute()

    discord_user_id = profile.data.get("discord_user_id") if profile.data else None

    if discord_user_id:
        try:
            await assign_discord_role(discord_user_id, plan)
            sb.table("user_profiles").update({
                "discord_role_synced": True
            }).eq("id", user_id).execute()
            logger.info(f"Discord role synced for user {user_id} → {plan}")
        except Exception as e:
            logger.error(f"Discord role sync failed for {user_id}: {e}")
    else:
        logger.info(f"User {user_id} has no Discord linked — skipping role sync")
