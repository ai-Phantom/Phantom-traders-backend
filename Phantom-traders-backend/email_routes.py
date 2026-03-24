"""
Phantom Traders — Email API Routes
Add these routes to your main FastAPI app on Render.

In your main.py:
  from email_routes import router as email_router
  app.include_router(email_router)
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, EmailStr
from typing import Optional
from email_service import (
    send_welcome_email,
    send_upgrade_email,
    send_alert_email,
    send_weekly_digest,
)
import os

router = APIRouter(prefix="/api/email", tags=["email"])

# Internal secret to prevent abuse — set INTERNAL_SECRET in Render env vars
INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "pt_internal_secret")


def verify_internal(x_internal_secret: str = Header(None)):
    if x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Request models ────────────────────────────────────────────

class WelcomeEmailRequest(BaseModel):
    email: str
    first_name: str

class UpgradeEmailRequest(BaseModel):
    email: str
    first_name: str
    plan: str           # "pro" or "elite"
    amount: str         # e.g. "$20.00"
    billing: str = "monthly"

class AlertEmailRequest(BaseModel):
    email: str
    first_name: str
    symbol: str
    condition: str      # "above" or "below"
    target: float
    current_price: float

class WeeklyDigestRequest(BaseModel):
    email: str
    first_name: str
    portfolio_value: float
    week_change: float
    week_change_pct: float
    top_mover: Optional[dict] = None


# ── Routes ────────────────────────────────────────────────────

@router.post("/welcome")
async def welcome_email(req: WelcomeEmailRequest, x_internal_secret: str = Header(None)):
    verify_internal(x_internal_secret)
    ok = send_welcome_email(req.email, req.first_name)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send welcome email")
    return {"status": "sent"}


@router.post("/upgrade")
async def upgrade_email(req: UpgradeEmailRequest, x_internal_secret: str = Header(None)):
    verify_internal(x_internal_secret)
    ok = send_upgrade_email(req.email, req.first_name, req.plan, req.amount, req.billing)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send upgrade email")
    return {"status": "sent"}


@router.post("/alert")
async def alert_email(req: AlertEmailRequest, x_internal_secret: str = Header(None)):
    verify_internal(x_internal_secret)
    ok = send_alert_email(req.email, req.first_name, req.symbol, req.condition, req.target, req.current_price)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send alert email")
    return {"status": "sent"}


@router.post("/weekly-digest")
async def weekly_digest(req: WeeklyDigestRequest, x_internal_secret: str = Header(None)):
    verify_internal(x_internal_secret)
    ok = send_weekly_digest(req.email, req.first_name, req.portfolio_value, req.week_change, req.week_change_pct, req.top_mover)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send weekly digest")
    return {"status": "sent"}


# ── Test endpoint (remove in production) ─────────────────────

@router.post("/test")
async def test_email(email: str, x_internal_secret: str = Header(None)):
    """Send a test welcome email to verify Resend is working."""
    verify_internal(x_internal_secret)
    ok = send_welcome_email(email, "Trader")
    return {"status": "sent" if ok else "failed"}
