"""
routers/subscriptions.py
Creates Stripe Checkout sessions and Customer Portal sessions.
The frontend redirects to Stripe-hosted pages — no card data touches our server.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import CheckoutRequest, CheckoutResponse, SubscriptionInfo, Plan, SubscriptionStatus
from app.database import get_supabase
from app.config import get_settings
import stripe

router = APIRouter()
bearer = HTTPBearer()


def get_stripe():
    stripe.api_key = get_settings().STRIPE_SECRET_KEY
    return stripe


# ── Map Stripe Price IDs to plan names ───────────────────────────────────────

def price_to_plan(price_id: str) -> str:
    s = get_settings()
    mapping = {
        s.STRIPE_PRICE_PRO_MONTHLY:    "pro",
        s.STRIPE_PRICE_PRO_ANNUAL:     "pro",
        s.STRIPE_PRICE_ELITE_MONTHLY:  "elite",
        s.STRIPE_PRICE_ELITE_ANNUAL:   "elite",
    }
    return mapping.get(price_id, "free")


# ── Create checkout session ───────────────────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    req: CheckoutRequest,
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False))
):
    sb  = get_supabase()
    s   = get_settings()
    st  = get_stripe()

    # Accept token from body OR Authorization header
    token = req.access_token or (credentials.credentials if credentials else None)
    if not token:
        raise HTTPException(401, "Unauthorized")

    # Verify user token
    try:
        user = sb.auth.get_user(token)
    except Exception:
        raise HTTPException(401, "Unauthorized")

    if not user.user or user.user.id != req.user_id:
        raise HTTPException(401, "Unauthorized")

    # Get or create Stripe customer
    profile = sb.table("user_profiles") \
        .select("stripe_customer_id, email") \
        .eq("id", req.user_id) \
        .single() \
        .execute()

    customer_id = profile.data.get("stripe_customer_id") if profile.data else None

    if not customer_id:
        customer = st.Customer.create(
            email    = profile.data.get("email", user.user.email),
            metadata = {"supabase_user_id": req.user_id}
        )
        customer_id = customer.id
        sb.table("user_profiles") \
            .update({"stripe_customer_id": customer_id}) \
            .eq("id", req.user_id) \
            .execute()

    # Create Stripe Checkout session
    success_url = req.success_url or f"{s.FRONTEND_URL}?checkout=success&plan={price_to_plan(req.price_id)}"
    cancel_url  = req.cancel_url  or f"{s.FRONTEND_URL}?checkout=cancelled"

    # Determine checkout mode — use 'payment' for one-time, 'subscription' for recurring
    checkout_mode = getattr(req, 'mode', None) or 'subscription'
    if checkout_mode not in ('subscription', 'payment'):
        checkout_mode = 'subscription'

    try:
        session_params = {
            "customer":              customer_id,
            "mode":                  checkout_mode,
            "payment_method_types":  ["card"],
            "line_items":            [{"price": req.price_id, "quantity": 1}],
            "success_url":           success_url + "&session_id={CHECKOUT_SESSION_ID}",
            "cancel_url":            cancel_url,
            "metadata":              {"supabase_user_id": req.user_id},
            "allow_promotion_codes": True,
        }

        # Only add subscription_data for subscription mode
        if checkout_mode == "subscription":
            session_params["subscription_data"] = {
                "metadata": {"supabase_user_id": req.user_id}
            }

        session = st.checkout.Session.create(**session_params)
    except st.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {e.user_message}")

    return CheckoutResponse(
        checkout_url = session.url,
        session_id   = session.id,
    )


# ── Customer portal (manage billing / cancel) ─────────────────────────────────

@router.post("/portal")
async def customer_portal(
    user_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
):
    sb  = get_supabase()
    s   = get_settings()
    st  = get_stripe()

    try:
        user = sb.auth.get_user(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Unauthorized")

    if not user.user or user.user.id != user_id:
        raise HTTPException(401, "Unauthorized")

    profile = sb.table("user_profiles") \
        .select("stripe_customer_id") \
        .eq("id", user_id) \
        .single() \
        .execute()

    customer_id = profile.data.get("stripe_customer_id") if profile.data else None
    if not customer_id:
        raise HTTPException(404, "No billing account found")

    portal = st.billing_portal.Session.create(
        customer   = customer_id,
        return_url = s.FRONTEND_URL,
    )

    return {"portal_url": portal.url}


# ── Get subscription info ─────────────────────────────────────────────────────

@router.get("/status/{user_id}", response_model=SubscriptionInfo)
async def get_subscription(
    user_id: str,
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
):
    sb = get_supabase()

    try:
        user = sb.auth.get_user(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Unauthorized")

    if not user.user or user.user.id != user_id:
        raise HTTPException(401, "Unauthorized")

    profile = sb.table("user_profiles") \
        .select("plan, subscription_status, subscription_end_date, stripe_customer_id") \
        .eq("id", user_id) \
        .single() \
        .execute()

    if not profile.data:
        raise HTTPException(404, "User not found")

    d = profile.data
    return SubscriptionInfo(
        user_id             = user_id,
        plan                = Plan(d.get("plan", "free")),
        status              = SubscriptionStatus(d.get("subscription_status", "inactive")),
        current_period_end  = d.get("subscription_end_date"),
        stripe_customer_id  = d.get("stripe_customer_id"),
    )
