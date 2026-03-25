"""
routers/auth.py — Signup, login, and profile endpoints.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import SignupRequest, LoginRequest, AuthResponse, Plan
from app.database import get_supabase
from app.config import get_settings
from app.routers.email_service import send_welcome_email
import httpx

router  = APIRouter()
bearer  = HTTPBearer()


@router.post("/signup", response_model=AuthResponse)
async def signup(req: SignupRequest):
    sb = get_supabase()

    # 1. Create user in Supabase Auth
    user_id = None
    try:
        result = sb.auth.sign_up({
            "email":    req.email,
            "password": req.password,
            "options": {
                "data": {"full_name": req.full_name or ""}
            }
        })
        if result.user:
            user_id = result.user.id
    except Exception as e:
        err_str = str(e).lower()
        # If user already exists, try to get their ID and continue
        if "already" in err_str or "registered" in err_str or "exists" in err_str:
            try:
                existing = sb.table("user_profiles").select("id").eq("email", req.email).single().execute()
                if existing.data:
                    user_id = existing.data["id"]
            except Exception:
                pass
        else:
            raise HTTPException(400, f"Signup failed: {str(e)}")

    if not user_id:
        raise HTTPException(400, "Signup failed — please try again")

    # 2. Upsert user profile row
    try:
        sb.table("user_profiles").upsert({
            "id":                  user_id,
            "email":               req.email,
            "full_name":           req.full_name or "",
            "plan":                "free",
            "subscription_status": "inactive",
            "stripe_customer_id":  None,
            "discord_user_id":     None,
            "discord_role_synced": False,
        }, {"on_conflict": "id"}).execute()
    except Exception as e:
        print(f"Profile upsert error (non-fatal): {e}")

    # 3. Send welcome email
    try:
        first_name = (req.full_name or req.email).split()[0].capitalize()
        send_welcome_email(req.email, first_name)
        print(f"Welcome email sent to {req.email}")
    except Exception as e:
        print(f"Welcome email failed (non-fatal): {e}")

    return AuthResponse(
        access_token = "",
        user_id      = user_id,
        email        = req.email,
        plan         = Plan.FREE,
    )


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


@router.get("/me")
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    sb = get_supabase()

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


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    sb = get_supabase()
    sb.auth.sign_out()
    return {"success": True}
