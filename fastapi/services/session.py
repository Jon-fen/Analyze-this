"""Session utilities — token validation, credits, Supabase client."""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import Request
from supabase import create_client, Client
from config import get_settings

logger = logging.getLogger(__name__)


def get_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_key)


def _user_dict(user) -> dict:
    meta = user.user_metadata or {}
    display_name = (
        meta.get("display_name")
        or meta.get("full_name")
        or (user.email or "").split("@")[0]
    )
    return {"id": user.id, "email": user.email, "display_name": display_name}


async def validate_session(request: Request) -> tuple:
    """
    Reads cookies, validates with Supabase.
    Returns (user_dict | None, new_tokens | None).
    new_tokens is set when a refresh occurred and new cookies must be saved.
    """
    settings = get_settings()
    if not settings.supabase_url:
        return None, None

    token = request.cookies.get("sb_access_token")
    refresh = request.cookies.get("sb_refresh_token")
    if not token:
        return None, None

    client = get_supabase()

    # 1. Try current access token
    try:
        res = client.auth.get_user(token)
        if res and res.user:
            return _user_dict(res.user), None
    except Exception:
        pass

    # 2. Token expired — try refresh
    if not refresh:
        return None, None
    try:
        res = client.auth.refresh_session(refresh)
        if res and res.session:
            return _user_dict(res.user), {
                "access_token": res.session.access_token,
                "refresh_token": res.session.refresh_token,
            }
    except Exception:
        pass

    return None, None


async def get_user_credits(user_id: str) -> dict:
    """Returns plan + credit info from the profiles table."""
    settings = get_settings()
    default = {"plan": "free", "credits_used": 0, "credits_limit": 5, "credits_remaining": 5}
    if not settings.supabase_url:
        return default

    client = get_supabase()
    try:
        res = client.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
        if not res or not res.data:
            return default

        profile = res.data
        plan = profile.get("plan", "free")
        plan_limits = {"free": 5, "pro_code": 10, "pro": 50, "admin": 999_999}
        limit = plan_limits.get(plan, 5)
        used = profile.get("credits_used_this_month", 0) or 0

        # Monthly reset
        reset_str = profile.get("credits_reset_at")
        if reset_str:
            try:
                reset_dt = datetime.fromisoformat(reset_str.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > reset_dt:
                    next_reset = reset_dt + timedelta(days=30)
                    client.table("profiles").update({
                        "credits_used_this_month": 0,
                        "credits_reset_at": next_reset.isoformat(),
                    }).eq("id", user_id).execute()
                    used = 0
            except (ValueError, AttributeError):
                pass

        return {
            "plan": plan,
            "credits_used": used,
            "credits_limit": limit,
            "credits_remaining": max(0, limit - used),
        }
    except Exception as e:
        logger.warning("get_user_credits error: %s", e)
        return default


async def consume_credit(user_id: str) -> None:
    """Increments credits_used_this_month by 1."""
    settings = get_settings()
    if not settings.supabase_url:
        return
    client = get_supabase()
    try:
        res = client.table("profiles").select("credits_used_this_month").eq("id", user_id).maybe_single().execute()
        current = (res.data or {}).get("credits_used_this_month", 0) or 0
        client.table("profiles").update({"credits_used_this_month": current + 1}).eq("id", user_id).execute()
    except Exception as e:
        logger.warning("consume_credit error: %s", e)
