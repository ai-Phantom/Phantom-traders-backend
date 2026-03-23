"""
routers/auth.py — Signup, login, and profile endpoints.
Supabase handles the actual password hashing and JWT generation.
We just call their API and store extra profile data in our own table.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import SignupRequest, LoginRequest, AuthResponse, Plan
from app.database import get_supabase
from app.config import get_settings
import httpx

router  = APIRouter()
bearer  = HTTPBearer()


# ── Signup ────────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=AuthResponse)
async def signup(req: SignupRequest):
    sb = get_supabase()

    # 1. Create user in Supabase Auth
    try:
        result = sb.auth.sign_up({
            "email":    req.email,
            "password": req.password,
            "options": {
                "data": {"full_name": req.full_name or ""}
            }
        })
    except Exception as e:
        raise HTTPException(400, f"Signup failed: {str(e)}")

    if not result.user:
        raise HTTPException(400, "Signup failed — please try again")

    user_id = result.user.id

    # 2. Insert user profile row (free plan by default)
    sb.table("user_profiles").insert({
        "id":                  user_id,
        "email":               req.email,
        "full_name":           req.full_name or "",
        "plan":                "free",
        "subscription_status": "inactive",
        "stripe_customer_id":  None,
        "discord_user_id":     None,
        "discord_role_synced": False,
    }).execute()

    return AuthResponse(
        access_token = result.session.access_token if result.session else "",
        user_id      = user_id,
        email        = req.email,
        plan         = Plan.FREE,
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    sb = get_supabase()

    try:
        result = sb.auth.sign_in_with_password({
            "email":    req.email,
            "password": req.password,
        })
    except Exception as e:
        raise HTTPException(401, "Invalid email or password")

    if not result.user or not result.session:
        raise HTTPException(401, "Invalid email or password")

    # Fetch plan from profile
    profile = sb.table("user_profiles") \
        .select("plan") \
        .eq("id", result.user.id) \
        .single() \
        .execute()

    plan = profile.data.get("plan", "free") if profile.data else "free"

    return AuthResponse(
        access_token = result.session.access_token,
        user_id      = result.user.id,
        email        = result.user.email,
        plan         = Plan(plan),
    )


# ── Get current user profile ──────────────────────────────────────────────────

@router.get("/me")
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    sb = get_supabase()

    # Verify the JWT and get user
    try:
        user = sb.auth.get_user(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Invalid or expired token")

    if not user.user:
        raise HTTPException(401, "Unauthorized")

    profile = sb.table("user_profiles") \
        .select("*") \
        .eq("id", user.user.id) \
        .single() \
        .execute()

    return {
        "user_id":             user.user.id,
        "email":               user.user.email,
        "plan":                profile.data.get("plan", "free"),
        "subscription_status": profile.data.get("subscription_status", "inactive"),
        "full_name":           profile.data.get("full_name", ""),
        "discord_linked":      bool(profile.data.get("discord_user_id")),
    }


# ── Logout ────────────────────────────────────────────────────────────────────

@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    sb = get_supabase()
    sb.auth.sign_out()
    return {"success": True}
