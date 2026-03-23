# ══════════════════════════════════════════════════════════════
# Phantom Traders — Stripe Webhook Handler
# ══════════════════════════════════════════════════════════════
#
# Add this to your FastAPI backend (phantom-traders-backend).
# 
# SETUP:
# 1. pip install stripe
# 2. Add these env vars on Render:
#      STRIPE_SECRET_KEY       = sk_live_...
#      STRIPE_WEBHOOK_SECRET   = whsec_...
#      SUPABASE_URL            = https://gzdhauxqrfbhbrfcscna.supabase.co
#      SUPABASE_SERVICE_KEY    = eyJ... (service_role key, NOT anon key)
#
# 3. In Stripe Dashboard → Developers → Webhooks → Add endpoint:
#      URL: https://phantom-traders-backend.onrender.com/webhooks/stripe
#      Events to listen for:
#        - checkout.session.completed
#        - customer.subscription.created
#        - customer.subscription.updated
#        - customer.subscription.deleted
#        - invoice.payment_succeeded
#
# 4. Copy the webhook signing secret (whsec_...) into STRIPE_WEBHOOK_SECRET
#
# ══════════════════════════════════════════════════════════════

import os
import stripe
import httpx
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()

STRIPE_SECRET_KEY     = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
SUPABASE_URL          = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY  = os.getenv("SUPABASE_SERVICE_KEY", "")

stripe.api_key = STRIPE_SECRET_KEY

# ── Map Stripe price IDs to plan names ────────────────────────
# Update these with your actual Stripe price IDs
PRICE_TO_PLAN = {
    # Pro plan
    "price_pro_monthly":      "pro",
    "price_pro_annual":       "pro",
    # Elite plan  
    "price_elite_monthly":    "elite",
    "price_elite_annual":     "elite",
    # Portfolio Manager subscription
    "price_portfolio_monthly": "pro",
    "price_portfolio_annual":  "pro",
}

# Fallback: if price ID not in map, determine from product metadata or amount
def resolve_plan(price_id: str, amount: int = 0) -> str:
    """Resolve a Stripe price ID to a plan name."""
    if price_id in PRICE_TO_PLAN:
        return PRICE_TO_PLAN[price_id]
    # Try to fetch the price from Stripe and check product metadata
    try:
        price = stripe.Price.retrieve(price_id, expand=["product"])
        product = price.get("product", {})
        if isinstance(product, dict):
            meta_plan = product.get("metadata", {}).get("plan")
            if meta_plan in ("pro", "elite"):
                return meta_plan
            name = (product.get("name") or "").lower()
            if "elite" in name or "all access" in name or "expert" in name:
                return "elite"
            if "pro" in name or "portfolio" in name:
                return "pro"
    except Exception:
        pass
    # Amount-based fallback
    if amount >= 3500:  # $35+
        return "elite"
    elif amount >= 1500:  # $15+
        return "pro"
    return "pro"  # default to pro for any paid


async def update_supabase_plan(user_id: str, plan: str, stripe_customer_id: str = None):
    """Update the user's plan in Supabase profiles table."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print(f"[WARN] Supabase not configured — skipping plan update for {user_id}")
        return False

    update_data = {"plan": plan}
    if stripe_customer_id:
        update_data["stripe_customer_id"] = stripe_customer_id

    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.patch(url, json=update_data, headers=headers)
        if resp.status_code in (200, 204):
            print(f"[OK] Updated {user_id} → plan={plan}")
            return True
        else:
            print(f"[ERR] Supabase update failed: {resp.status_code} {resp.text}")
            return False


async def find_user_by_email(email: str) -> str | None:
    """Look up a user_id in profiles by email."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/profiles?email=eq.{email}&select=id"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            rows = resp.json()
            if rows and len(rows) > 0:
                return rows[0]["id"]
    return None


async def find_user_by_stripe_customer(customer_id: str) -> str | None:
    """Look up a user_id in profiles by stripe_customer_id."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None
    url = f"{SUPABASE_URL}/rest/v1/profiles?stripe_customer_id=eq.{customer_id}&select=id"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            rows = resp.json()
            if rows and len(rows) > 0:
                return rows[0]["id"]
    return None


# ══════════════════════════════════════════════════════════════
# WEBHOOK ENDPOINT
# ══════════════════════════════════════════════════════════════

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify webhook signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data = event["data"]["object"]

    print(f"[STRIPE] {event_type} — {event.get('id', '?')}")

    # ── checkout.session.completed ─────────────────────────────
    if event_type == "checkout.session.completed":
        customer_id = data.get("customer")
        customer_email = data.get("customer_email") or data.get("customer_details", {}).get("email")
        user_id = data.get("metadata", {}).get("user_id")  # passed from frontend
        amount = data.get("amount_total", 0)
        mode = data.get("mode")  # "payment" or "subscription"

        # Determine plan from line items
        plan = "pro"
        line_items = data.get("line_items", {}).get("data", [])
        if not line_items:
            # Fetch line items from Stripe
            try:
                session = stripe.checkout.Session.retrieve(data["id"], expand=["line_items"])
                line_items = session.get("line_items", {}).get("data", [])
            except Exception:
                pass

        for item in line_items:
            price_id = item.get("price", {}).get("id", "")
            plan = resolve_plan(price_id, amount)
            break  # use the first line item

        # If no plan resolved from line items, use amount
        if not line_items:
            plan = resolve_plan("", amount)

        # Find the user
        if not user_id and customer_id:
            user_id = await find_user_by_stripe_customer(customer_id)
        if not user_id and customer_email:
            user_id = await find_user_by_email(customer_email)

        if user_id:
            await update_supabase_plan(user_id, plan, customer_id)
        else:
            print(f"[WARN] checkout.session.completed but no user found. email={customer_email} customer={customer_id}")

    # ── customer.subscription.created / updated ────────────────
    elif event_type in ("customer.subscription.created", "customer.subscription.updated"):
        customer_id = data.get("customer")
        status = data.get("status")  # active, past_due, canceled, etc.
        items = data.get("items", {}).get("data", [])

        plan = "pro"
        for item in items:
            price_id = item.get("price", {}).get("id", "")
            plan = resolve_plan(price_id)
            break

        # Only activate if subscription is active
        if status in ("active", "trialing"):
            user_id = await find_user_by_stripe_customer(customer_id)
            if user_id:
                await update_supabase_plan(user_id, plan, customer_id)
            else:
                print(f"[WARN] subscription event but no user for customer={customer_id}")
        elif status in ("canceled", "unpaid", "past_due"):
            # Downgrade to free
            user_id = await find_user_by_stripe_customer(customer_id)
            if user_id:
                await update_supabase_plan(user_id, "free", customer_id)
                print(f"[OK] Downgraded {user_id} to free (subscription {status})")

    # ── customer.subscription.deleted ──────────────────────────
    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        user_id = await find_user_by_stripe_customer(customer_id)
        if user_id:
            await update_supabase_plan(user_id, "free", customer_id)
            print(f"[OK] Subscription deleted — {user_id} downgraded to free")

    # ── invoice.payment_succeeded (renewal) ────────────────────
    elif event_type == "invoice.payment_succeeded":
        customer_id = data.get("customer")
        # Only care about subscription invoices (not one-time)
        subscription_id = data.get("subscription")
        if subscription_id:
            lines = data.get("lines", {}).get("data", [])
            plan = "pro"
            for line in lines:
                price_id = line.get("price", {}).get("id", "")
                plan = resolve_plan(price_id)
                break
            user_id = await find_user_by_stripe_customer(customer_id)
            if user_id:
                await update_supabase_plan(user_id, plan, customer_id)

    return {"status": "ok"}


# ══════════════════════════════════════════════════════════════
# /auth/me ENDPOINT — returns user plan for frontend
# ══════════════════════════════════════════════════════════════

@router.get("/auth/me")
async def auth_me(request: Request):
    """Return the user's current plan from Supabase."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = auth_header.replace("Bearer ", "")

    # Verify token with Supabase
    url = f"{SUPABASE_URL}/auth/v1/user"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {token}",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid token")
        user_data = resp.json()
        user_id = user_data.get("id")

    if not user_id:
        raise HTTPException(status_code=401, detail="No user ID")

    # Fetch plan from profiles
    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=plan,stripe_customer_id"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return {"plan": rows[0].get("plan", "free"), "user_id": user_id}

    return {"plan": "free", "user_id": user_id}
