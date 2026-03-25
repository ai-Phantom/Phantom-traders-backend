"""
Phantom Traders — Admin Auth Hardening
Place in: Phantom-traders-backend/app/routers/admin_auth.py

Usage:
  from app.routers.admin_auth import require_admin
  
  @router.get("/admin/users")
  async def get_users(admin=Depends(require_admin)):
      ...
"""

from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.database import get_supabase
import os

bearer = HTTPBearer(auto_error=False)

ADMIN_EMAILS = set(
    os.environ.get("ADMIN_EMAILS", "phantom.aiconsulting@gmail.com").split(",")
)


async def require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    """
    Dependency that verifies the request comes from an admin user.
    Checks:
    1. Valid Supabase JWT token
    2. Email is in ADMIN_EMAILS list
    3. Session is active
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")

    sb = get_supabase()
    try:
        user = sb.auth.get_user(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if not user.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if user.user.email not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")

    return user.user


async def require_internal(request: Request):
    """
    Verify request comes from internal services via secret header.
    Use for email endpoints, cron jobs, etc.
    """
    secret = (
        request.headers.get("x-internal-secret") or
        request.headers.get("X-Internal-Secret")
    )
    expected = os.environ.get("INTERNAL_SECRET", "pt_internal_secret")
    if secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


async def require_stripe_webhook(request: Request):
    """Verify Stripe webhook signature — already handled in stripe_webhooks.py."""
    pass
