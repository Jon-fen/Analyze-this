"""Session utilities — token validation, credits, history, feedback, admin helpers."""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import Request
from supabase import create_client, Client
from config import get_settings

logger = logging.getLogger(__name__)

PLAN_LIMITS = {"free": 5, "pro_code": 10, "pro": 50, "admin": 999_999}
COUNTER_BASE_CVS   = 10_000
COUNTER_BASE_USERS = 1_000


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
    """Reads cookies, validates with Supabase. Returns (user | None, new_tokens | None)."""
    settings = get_settings()
    if not settings.supabase_url:
        return None, None

    token = request.cookies.get("sb_access_token")
    refresh = request.cookies.get("sb_refresh_token")
    if not token:
        return None, None

    client = get_supabase()

    try:
        res = client.auth.get_user(token)
        if res and res.user:
            return _user_dict(res.user), None
    except Exception:
        pass

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


# ─── Profile ───────────────────────────────────────────────────────────────────

def ensure_profile(user_id: str, email: str, display_name: str = "") -> None:
    """Create profile row on first login if it doesn't exist."""
    settings = get_settings()
    if not settings.supabase_url:
        return
    client = get_supabase()
    try:
        res = client.table("profiles").select("id").eq("id", user_id).maybe_single().execute()
        if not res or not res.data:
            client.table("profiles").insert({
                "id": user_id,
                "email": email,
                "display_name": display_name or email.split("@")[0],
                "plan": "free",
                "credits_used_this_month": 0,
                "credits_reset_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
    except Exception as e:
        logger.warning("ensure_profile error: %s", e)


# ─── Credits ──────────────────────────────────────────────────────────────────

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
        limit = PLAN_LIMITS.get(plan, 5)
        used = profile.get("credits_used_this_month", 0) or 0

        reset_str = profile.get("credits_reset_at")
        if reset_str:
            try:
                reset_dt = datetime.fromisoformat(reset_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if now.month != reset_dt.month or now.year != reset_dt.year:
                    client.table("profiles").update({
                        "credits_used_this_month": 0,
                        "credits_reset_at": now.isoformat(),
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


# ─── History ──────────────────────────────────────────────────────────────────

def save_history(user_id: str, job_title: str, score: int, ats_ok: bool):
    """Returns the new history row id so outcome can be updated later."""
    settings = get_settings()
    if not settings.supabase_url:
        return None
    client = get_supabase()
    try:
        res = client.table("history").insert({
            "user_id": user_id,
            "job_title": (job_title or "")[:120],
            "score_match": score,
            "ats_compatible": ats_ok,
            "outcome": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        if res.data:
            return res.data[0].get("id")
        return None
    except Exception as e:
        logger.warning("save_history error: %s", e)
        return None


def save_guest_analysis() -> None:
    """Record a guest analysis in the guest_analyses table."""
    settings = get_settings()
    if not settings.supabase_url:
        return
    client = get_supabase()
    try:
        client.table("guest_analyses").insert({
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("save_guest_analysis error: %s", e)


def update_outcome(history_id, outcome: str) -> bool:
    settings = get_settings()
    if not settings.supabase_url:
        return False
    client = get_supabase()
    try:
        client.table("history").update({"outcome": outcome}).eq("id", history_id).execute()
        return True
    except Exception as e:
        logger.warning("update_outcome error: %s", e)
        return False


def get_history(user_id: str) -> list:
    settings = get_settings()
    if not settings.supabase_url:
        return []
    client = get_supabase()
    try:
        res = (client.table("history")
               .select("*")
               .eq("user_id", user_id)
               .order("created_at", desc=True)
               .limit(10)
               .execute())
        return res.data or []
    except Exception as e:
        logger.warning("get_history error: %s", e)
        return []


# ─── Feedback ─────────────────────────────────────────────────────────────────

def save_feedback(user_id, email: str, rating: int, comment: str, job_title: str) -> bool:
    settings = get_settings()
    if not settings.supabase_url:
        return False
    client = get_supabase()
    try:
        client.table("feedback").insert({
            "user_id": user_id,
            "email": email,
            "rating": rating,
            "comment": (comment or "")[:500],
            "job_title": (job_title or "")[:120],
            "approved": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as e:
        logger.warning("save_feedback error: %s", e)
        return False


def get_public_reviews() -> list:
    settings = get_settings()
    if not settings.supabase_url:
        return []
    client = get_supabase()
    try:
        res = (client.table("feedback")
               .select("rating,comment,job_title,created_at")
               .eq("approved", True)
               .order("created_at", desc=True)
               .limit(6)
               .execute())
        return res.data or []
    except Exception:
        return []


def get_all_feedback() -> list:
    settings = get_settings()
    if not settings.supabase_url:
        return []
    client = get_supabase()
    try:
        res = (client.table("feedback")
               .select("*")
               .order("created_at", desc=True)
               .limit(50)
               .execute())
        return res.data or []
    except Exception:
        return []


def approve_feedback(feedback_id, approve: bool) -> bool:
    settings = get_settings()
    if not settings.supabase_url:
        return False
    client = get_supabase()
    try:
        client.table("feedback").update({"approved": approve}).eq("id", feedback_id).execute()
        return True
    except Exception:
        return False


# ─── Global stats ─────────────────────────────────────────────────────────────

def get_global_stats() -> dict:
    settings = get_settings()
    if not settings.supabase_url:
        return {"cvs": COUNTER_BASE_CVS, "users": COUNTER_BASE_USERS}
    client = get_supabase()
    try:
        cvs = client.table("history").select("id", count="exact").execute()
        users = client.table("profiles").select("id", count="exact").execute()
        return {
            "cvs":   (cvs.count or 0)   + COUNTER_BASE_CVS,
            "users": (users.count or 0) + COUNTER_BASE_USERS,
        }
    except Exception:
        return {"cvs": COUNTER_BASE_CVS, "users": COUNTER_BASE_USERS}


# ─── Activation codes ─────────────────────────────────────────────────────────

def validate_and_use_code(user_id: str, code: str) -> tuple:
    settings = get_settings()
    if not settings.supabase_url:
        return False, "Servicio no disponible."
    client = get_supabase()
    try:
        code = code.strip().upper()
        res = client.table("activation_codes").select("*").eq("code", code).maybe_single().execute()
        row = res.data if res else None
        if not row:
            return False, "Código inválido."
        if not row.get("active", True):
            return False, "Este código ya no está activo."
        max_uses = row.get("max_uses")
        used = row.get("uses_count", 0)
        if max_uses and used >= max_uses:
            return False, "Este código ya alcanzó su límite de usos."
        expires = row.get("expires_at")
        if expires:
            try:
                exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > exp_dt:
                    return False, "Este código ha expirado."
            except ValueError:
                pass
        plan = row.get("grants_plan", "pro_code")
        client.table("profiles").update({
            "plan": plan,
            "activation_code": code,
            "credits_used_this_month": 0,
        }).eq("id", user_id).execute()
        client.table("activation_codes").update({
            "uses_count": used + 1,
        }).eq("code", code).execute()
        limit = PLAN_LIMITS.get(plan, 10)
        return True, f"¡Código activado! Ahora tienes {limit} análisis por mes."
    except Exception as e:
        logger.warning("validate_and_use_code error: %s", e)
        return False, "Código inválido."


def get_all_codes() -> list:
    settings = get_settings()
    if not settings.supabase_url:
        return []
    client = get_supabase()
    try:
        res = client.table("activation_codes").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def create_code(code: str, description: str, max_uses: int, grants_plan: str, expires_at) -> bool:
    settings = get_settings()
    if not settings.supabase_url:
        return False
    client = get_supabase()
    try:
        client.table("activation_codes").insert({
            "code": code.strip().upper(),
            "description": description,
            "max_uses": max_uses if max_uses > 0 else None,
            "grants_plan": grants_plan,
            "uses_count": 0,
            "active": True,
            "expires_at": expires_at if expires_at else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception as e:
        logger.warning("create_code error: %s", e)
        return False


def toggle_code(code_id, active: bool) -> bool:
    settings = get_settings()
    if not settings.supabase_url:
        return False
    client = get_supabase()
    try:
        client.table("activation_codes").update({"active": active}).eq("id", code_id).execute()
        return True
    except Exception:
        return False


# ─── Admin helpers ─────────────────────────────────────────────────────────────

def get_admin_users() -> list:
    settings = get_settings()
    if not settings.supabase_url:
        return []
    client = get_supabase()
    try:
        res = (client.table("profiles")
               .select("id,email,display_name,plan,credits_used_this_month,activation_code,created_at")
               .order("created_at", desc=True)
               .limit(20)
               .execute())
        return res.data or []
    except Exception as e:
        logger.warning("get_admin_users error: %s", e)
        return []


def update_user_plan(user_id: str, plan: str) -> bool:
    settings = get_settings()
    if not settings.supabase_url:
        return False
    client = get_supabase()
    try:
        client.table("profiles").update({"plan": plan}).eq("id", user_id).execute()
        return True
    except Exception:
        return False


def reset_user_credits(user_id: str) -> bool:
    settings = get_settings()
    if not settings.supabase_url:
        return False
    client = get_supabase()
    try:
        client.table("profiles").update({
            "credits_used_this_month": 0,
            "credits_reset_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()
        return True
    except Exception:
        return False
