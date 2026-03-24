"""
Phantom Traders — Stripe Webhook Email Triggers
Add this logic to your existing subscriptions.py webhook handler.

When a checkout completes, fire the upgrade email automatically.
When signup completes, fire the welcome email.
"""

import httpx
import os

BACKEND_URL = "https://phantom-traders-backend.onrender.com"
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "pt_internal_secret")

PLAN_AMOUNTS = {
    # Monthly
    "price_1TEP4MBGuYguz5hxXzb1akTk": ("pro",   "$20.00", "monthly"),
    "price_1TEP5hBGuYguz5hxtAK7qJvV": ("elite",  "$50.00", "monthly"),
    # Annual
    "price_1TEP51BGuYguz5hxDOO0UhRP": ("pro",   "$199.00", "annual"),
    "price_1TEP7OBGuYguz5hxSsqoGm8U": ("elite",  "$499.00", "annual"),
}


async def trigger_welcome_email(email: str, first_name: str):
    """Call after successful signup in your auth route."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BACKEND_URL}/api/email/welcome",
                json={"email": email, "first_name": first_name or "Trader"},
                headers={"x-internal-secret": INTERNAL_SECRET},
                timeout=10,
            )
    except Exception as e:
        print(f"Welcome email trigger error: {e}")


async def trigger_upgrade_email(email: str, first_name: str, price_id: str):
    """Call from Stripe webhook on checkout.session.completed."""
    plan_info = PLAN_AMOUNTS.get(price_id)
    if not plan_info:
        return
    plan, amount, billing = plan_info
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BACKEND_URL}/api/email/upgrade",
                json={
                    "email": email,
                    "first_name": first_name or "Trader",
                    "plan": plan,
                    "amount": amount,
                    "billing": billing,
                },
                headers={"x-internal-secret": INTERNAL_SECRET},
                timeout=10,
            )
    except Exception as e:
        print(f"Upgrade email trigger error: {e}")


async def trigger_alert_email(email: str, first_name: str, symbol: str, condition: str, target: float, current_price: float):
    """Call when an alert triggers in your price monitoring logic."""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{BACKEND_URL}/api/email/alert",
                json={
                    "email": email,
                    "first_name": first_name or "Trader",
                    "symbol": symbol,
                    "condition": condition,
                    "target": target,
                    "current_price": current_price,
                },
                headers={"x-internal-secret": INTERNAL_SECRET},
                timeout=10,
            )
    except Exception as e:
        print(f"Alert email trigger error: {e}")


# ── Stripe webhook integration snippet ───────────────────────
# Add this to your existing checkout.session.completed handler:
#
# @app.post("/api/subscriptions/webhook")
# async def stripe_webhook(request: Request):
#     ...existing code...
#     if event["type"] == "checkout.session.completed":
#         session = event["data"]["object"]
#         customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
#         price_id = session["line_items"]["data"][0]["price"]["id"]  # if expanded
#         # OR get price_id from metadata if you store it there
#         if customer_email and price_id:
#             await trigger_upgrade_email(customer_email, "Trader", price_id)
#     ...
