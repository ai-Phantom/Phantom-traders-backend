"""
models/user.py — Pydantic models for request/response validation.
"""
from pydantic import BaseModel, EmailStr
from typing import Optional
from enum import Enum


class Plan(str, Enum):
    FREE  = "free"
    PRO   = "pro"
    ELITE = "elite"


class SubscriptionStatus(str, Enum):
    ACTIVE    = "active"
    CANCELLED = "cancelled"
    PAST_DUE  = "past_due"
    TRIALING  = "trialing"
    INACTIVE  = "inactive"


# ── Auth ──────────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    plan: Plan


# ── Checkout ──────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    price_id: str
    user_id: str
    access_token: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    mode: Optional[str] = None


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


# ── Subscription ──────────────────────────────────────────────────────────────

class SubscriptionInfo(BaseModel):
    user_id: str
    plan: Plan
    status: SubscriptionStatus
    current_period_end: Optional[str] = None
    cancel_at_period_end: bool = False
    stripe_customer_id: Optional[str] = None


# ── Discord ───────────────────────────────────────────────────────────────────

class DiscordLinkRequest(BaseModel):
    user_id: str
    discord_user_id: str


class DiscordLinkResponse(BaseModel):
    success: bool
    roles_assigned: list[str]
    message: str
