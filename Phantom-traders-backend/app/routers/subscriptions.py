"""
routers/subscriptions.py
Handles Stripe checkout session creation and billing portal.
Promo codes enabled — customers can enter LAUNCH25 or TESTME95 at checkout.
"""

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import get_settings
from app.database import get_supabase
from app.routers.rate_limit import rate_limit
import stripe
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def get_stripe():
    s = get_settings()
    stripe.api_key = s.STRIPE_SECRET_KEY
    return stripe


# ── POST /checkout ─────────────────────────────────────────────
@router.post("/checkout")
async def create_checkout(request: Request):
    await rate_limit(request, "checkout")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    price_id     = body.get("price_id")
    mode         = body.get("mode", "subscription")
    user_id      = body.get("user_id")
    access_token = body.get("access_token")
    success_url  = body.get("success_url", "https://aiphantomtraders.com?checkout=success")
    cancel_url   = body.get("cancel_url",  "https://aiphantomtraders.com?checkout=cancelled")

    if not price_id:
        raise HTTPException(400, "price_id is required")
    if not user_id:
        raise HTTPException(400, "user_id is required")

    st = get_stripe()
    sb = get_supabase()

    # Get or create Stripe customer
    customer_id = None
    try:
        profile = sb.table("user_profiles").select("stripe_customer_id, email").eq("id", user_id).single().execute()
        if profile.data:
            customer_id = profile.data.get("stripe_customer_id")
            email       = profile.data.get("email", "")
            # Create customer in Stripe if not exists
            if not customer_id:
                customer = st.Customer.create(
                    email=email,
                    metadata={"supabase_user_id": user_id}
                )
                customer_id = customer.id
                sb.table("user_profiles").update({"stripe_customer_id": customer_id}).eq("id", user_id).execute()
    except Exception as e:
        logger.warning(f"Could not fetch/create Stripe customer: {e}")

    # Build checkout session params
    session_params = {
        "mode": mode,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url":  cancel_url,
        "allow_promotion_codes": True,   # ← enables LAUNCH25, TESTME95 etc.
        "metadata": {"supabase_user_id": user_id},
        "subscription_data": {
            "metadata": {"supabase_user_id": user_id}
        } if mode == "subscription" else {},
    }

    if customer_id:
        session_params["customer"] = customer_id
    elif email:
        session_params["customer_email"] = email

    try:
        session = st.checkout.Session.create(**session_params)
        return {"checkout_url": session.url}
    except stripe.error.StripeError as e:
        logger.error(f"Stripe checkout error: {e}")
        raise HTTPException(400, str(e))


# ── POST /portal ───────────────────────────────────────────────
@router.post("/portal")
async def billing_portal(request: Request, credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        body = await request.json()
    except Exception:
        body = {}

    user_id      = body.get("user_id") or request.query_params.get("user_id")
    return_url   = body.get("return_url", "https://aiphantomtraders.com")

    if not user_id:
        raise HTTPException(400, "user_id is required")

    st = get_stripe()
    sb = get_supabase()

    try:
        profile = sb.table("user_profiles").select("stripe_customer_id").eq("id", user_id).single().execute()
        customer_id = profile.data.get("stripe_customer_id") if profile.data else None
    except Exception as e:
        raise HTTPException(400, f"Could not find user: {e}")

    if not customer_id:
        raise HTTPException(400, "No Stripe customer found for this user — they need to subscribe first")

    try:
        portal = st.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url
        )
        return {"portal_url": portal.url}
    except stripe.error.StripeError as e:
        logger.error(f"Stripe portal error: {e}")
        raise HTTPException(400, str(e))
