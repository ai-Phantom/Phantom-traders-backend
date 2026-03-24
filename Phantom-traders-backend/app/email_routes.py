"""
Phantom Traders — Email API Routes
Place in: Phantom-traders-backend/app/email_routes.py
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from app.email_service import (
    send_welcome_email,
    send_upgrade_email,
    send_alert_email,
    send_weekly_digest,
)
import os

router = APIRouter(prefix="/api/email", tags=["email"])

INTERNAL_SECRET = os.environ.get("INTERNAL_SECRET", "pt_internal_secret")


def verify_internal(x_internal_secret: str = Header(None)):
    if x_internal_secret != INTERNAL_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


class WelcomeEmailRequest(BaseModel):
    email: str
    first_name: str

class UpgradeEmailRequest(BaseModel):
    email: str
    first_name: str
    plan: str
    amount: str
    billing: str = "monthly"

class AlertEmailRequest(BaseModel):
    email: str
    first_name: str
    symbol: str
    condition: str
    target: float
    current_price: float

class WeeklyDigestRequest(BaseModel):
    email: str
    first_name: str
    portfolio_value: float
    week_change: float
    week_change_pct: float
    top_mover: Optional[dict] = None


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


@router.post("/test")
async def test_email(email: str, x_internal_secret: str = Header(None)):
    verify_internal(x_internal_secret)
    ok = send_welcome_email(email, "Trader")
    return {"status": "sent" if ok else "failed"}
