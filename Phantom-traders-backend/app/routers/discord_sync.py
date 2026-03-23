"""
routers/discord_sync.py
Links a user's Discord account and assigns the correct server role
based on their Phantom Traders subscription plan.

Role hierarchy:
  free   → Rookie
  pro    → Pro Trader  (+ keep Trader if earned)
  elite  → Elite       (+ keep Pro Trader + Trader)

Plan roles are additive — getting Pro doesn't remove Trader.
Cancellation removes Pro Trader / Elite but keeps community roles.
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import DiscordLinkRequest, DiscordLinkResponse
from app.database import get_supabase
from app.config import get_settings
import httpx
import logging

router = APIRouter()
bearer = HTTPBearer()
logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


# ── HTTP client for Discord API ───────────────────────────────────────────────

def discord_headers():
    return {
        "Authorization": f"Bot {get_settings().DISCORD_BOT_TOKEN}",
        "Content-Type":  "application/json",
    }


# ── Assign role based on plan ─────────────────────────────────────────────────

async def assign_discord_role(discord_user_id: str, plan: str):
    """
    Assign the correct Discord role and remove incompatible plan roles.
    Called automatically after any subscription change.
    """
    s = get_settings()
    guild = s.DISCORD_GUILD_ID
    headers = discord_headers()

    # Plan → role mapping
    plan_roles = {
        "pro":   s.DISCORD_ROLE_PRO_TRADER,
        "elite": s.DISCORD_ROLE_ELITE,
    }

    # Roles to remove when downgrading
    all_plan_roles = [s.DISCORD_ROLE_PRO_TRADER, s.DISCORD_ROLE_ELITE]

    async with httpx.AsyncClient() as client:
        assigned = []
        removed  = []

        if plan in ("pro", "elite"):
            role_id = plan_roles[plan]

            # Add the new plan role
            resp = await client.put(
                f"{DISCORD_API}/guilds/{guild}/members/{discord_user_id}/roles/{role_id}",
                headers=headers
            )
            if resp.status_code in (200, 204):
                assigned.append(role_id)
            else:
                logger.warning(f"Failed to add role {role_id}: {resp.status_code} {resp.text}")

            # If upgrading to Elite, also add Pro Trader role
            if plan == "elite":
                resp2 = await client.put(
                    f"{DISCORD_API}/guilds/{guild}/members/{discord_user_id}/roles/{s.DISCORD_ROLE_PRO_TRADER}",
                    headers=headers
                )
                if resp2.status_code in (200, 204):
                    assigned.append(s.DISCORD_ROLE_PRO_TRADER)

        else:
            # Downgraded to free — remove all plan roles, keep Rookie
            for role_id in all_plan_roles:
                resp = await client.delete(
                    f"{DISCORD_API}/guilds/{guild}/members/{discord_user_id}/roles/{role_id}",
                    headers=headers
                )
                if resp.status_code in (200, 204):
                    removed.append(role_id)

        return {"assigned": assigned, "removed": removed}


# ── Ensure Rookie role on join ────────────────────────────────────────────────

async def assign_rookie_role(discord_user_id: str):
    s = get_settings()
    headers = discord_headers()

    async with httpx.AsyncClient() as client:
        await client.put(
            f"{DISCORD_API}/guilds/{s.DISCORD_GUILD_ID}/members/{discord_user_id}/roles/{s.DISCORD_ROLE_ROOKIE}",
            headers=headers
        )


# ── Link Discord account endpoint ─────────────────────────────────────────────

@router.post("/link", response_model=DiscordLinkResponse)
async def link_discord(
    req: DiscordLinkRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer)
):
    sb = get_supabase()

    # Verify user token
    try:
        user = sb.auth.get_user(credentials.credentials)
    except Exception:
        raise HTTPException(401, "Unauthorized")

    if not user.user or user.user.id != req.user_id:
        raise HTTPException(401, "Unauthorized")

    # Get user's current plan
    profile = sb.table("user_profiles") \
        .select("plan") \
        .eq("id", req.user_id) \
        .single() \
        .execute()

    plan = profile.data.get("plan", "free") if profile.data else "free"

    # Save Discord ID
    sb.table("user_profiles").update({
        "discord_user_id":     req.discord_user_id,
        "discord_role_synced": False,
    }).eq("id", req.user_id).execute()

    # Assign Rookie role first (everyone gets this)
    await assign_rookie_role(req.discord_user_id)

    # Then assign plan role
    result = await assign_discord_role(req.discord_user_id, plan)

    # Mark as synced
    sb.table("user_profiles").update({
        "discord_role_synced": True
    }).eq("id", req.user_id).execute()

    all_assigned = ["rookie"] + result.get("assigned", [])

    return DiscordLinkResponse(
        success        = True,
        roles_assigned = all_assigned,
        message        = f"Discord linked and {plan} role assigned successfully",
    )


# ── Manual re-sync endpoint (for support / fixing stuck roles) ────────────────

@router.post("/sync/{user_id}")
async def force_sync_discord(
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
        .select("discord_user_id, plan") \
        .eq("id", user_id) \
        .single() \
        .execute()

    if not profile.data:
        raise HTTPException(404, "User not found")

    discord_id = profile.data.get("discord_user_id")
    plan       = profile.data.get("plan", "free")

    if not discord_id:
        raise HTTPException(400, "No Discord account linked")

    result = await assign_discord_role(discord_id, plan)

    return {
        "success":  True,
        "plan":     plan,
        "assigned": result.get("assigned", []),
        "removed":  result.get("removed", []),
    }


# ── Get Discord link status ───────────────────────────────────────────────────

@router.get("/status/{user_id}")
async def discord_status(
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
        .select("discord_user_id, discord_role_synced, plan") \
        .eq("id", user_id) \
        .single() \
        .execute()

    if not profile.data:
        raise HTTPException(404, "User not found")

    return {
        "linked":       bool(profile.data.get("discord_user_id")),
        "role_synced":  profile.data.get("discord_role_synced", False),
        "plan":         profile.data.get("plan", "free"),
    }
