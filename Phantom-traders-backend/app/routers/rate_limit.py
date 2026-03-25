"""
Phantom Traders — Server-Side Rate Limiting
Place in: Phantom-traders-backend/app/routers/rate_limit.py

Usage in any router:
  from app.routers.rate_limit import rate_limit
  
  @router.post("/signup")
  async def signup(req: Request):
      await rate_limit(req, "signup", max_requests=3, window_seconds=60)
      ...
"""

from fastapi import HTTPException, Request
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio

# In-memory store — replace with Redis for production multi-instance deploys
_rate_store: dict[str, list[datetime]] = defaultdict(list)
_lock = asyncio.Lock()

RATE_LIMIT_CONFIG = {
    "signup":       {"max": 5,   "window": 60,    "msg": "Too many signup attempts. Wait 1 minute."},
    "login":        {"max": 10,  "window": 60,    "msg": "Too many login attempts. Wait 1 minute."},
    "forgot_pass":  {"max": 3,   "window": 300,   "msg": "Too many reset attempts. Wait 5 minutes."},
    "email_test":   {"max": 5,   "window": 60,    "msg": "Too many email test requests."},
    "email_send":   {"max": 20,  "window": 3600,  "msg": "Email rate limit reached. Try again in 1 hour."},
    "api_general":  {"max": 100, "window": 60,    "msg": "Too many requests. Slow down."},
    "admin":        {"max": 50,  "window": 60,    "msg": "Too many admin requests."},
    "webhook":      {"max": 500, "window": 60,    "msg": "Webhook rate limit exceeded."},
}


def get_client_ip(request: Request) -> str:
    """Get real IP, respecting Cloudflare and proxy headers."""
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit(
    request: Request,
    action: str,
    max_requests: int = None,
    window_seconds: int = None,
):
    """
    Rate limit by IP + action. Raises 429 if limit exceeded.
    Uses config from RATE_LIMIT_CONFIG if max/window not provided.
    """
    config = RATE_LIMIT_CONFIG.get(action, {})
    max_req = max_requests or config.get("max", 60)
    window = window_seconds or config.get("window", 60)
    msg = config.get("msg", "Too many requests. Please try again later.")

    ip = get_client_ip(request)
    key = f"{action}:{ip}"
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=window)

    async with _lock:
        # Clean old entries
        _rate_store[key] = [t for t in _rate_store[key] if t > cutoff]

        if len(_rate_store[key]) >= max_req:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": msg,
                    "retry_after": window,
                }
            )
        _rate_store[key].append(now)


def rate_limit_sync(request: Request, action: str) -> bool:
    """Synchronous check — returns True if rate limited (for non-async contexts)."""
    config = RATE_LIMIT_CONFIG.get(action, {})
    max_req = config.get("max", 60)
    window = config.get("window", 60)
    ip = get_client_ip(request)
    key = f"{action}:{ip}"
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=window)
    _rate_store[key] = [t for t in _rate_store[key] if t > cutoff]
    if len(_rate_store[key]) >= max_req:
        return True
    _rate_store[key].append(now)
    return False
