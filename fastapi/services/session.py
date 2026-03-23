"""
Supabase data layer — auth, credits, history, feedback, admin, codes.
"""
from __future__ import annotations
import json
import re
import secrets
import string
import httpx
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import Request
from supabase import create_client, Client

from config import get_settings

RAILWAY_URL = "https://analyze-this-production.up.railway.app"
PLAN_LIMITS = {"free": 5, "pro_code": 10, "pro": 50, "admin": 999_999}
COUNTER_BASE_CVS = 10_000
COUNTER_BASE_USERS = 1_000


def _sb() -> Client:
    s = get_settings()
    if not s.supabase_url or not s.supabase_key:
        raise RuntimeError("Supabase not configured")
    return create_client(s.supabase_url, s.supabase_key)


def _sb_admin() -> Client:
    """Uses service_role key to bypass RLS for admin writes. Falls back to anon key."""
    s = get_settings()
    key = s.supabase_service_key or s.supabase_key
    if not s.supabase_url or not key:
        raise RuntimeError("Supabase not configured")
    return create_client(s.supabase_url, key)


# ─── Session validation ────────────────────────────────────────────────────────

def validate_session(request: Request) -> Tuple[Optional[dict], Optional[dict]]:
    """Returns (user_dict | None, new_tokens | None)."""
    access = request.cookies.get("sb_access_token")
    refresh = request.cookies.get("sb_refresh_token")
    if not access:
        return None, None
    try:
        sb = _sb()
        res = sb.auth.get_user(access)
        user = res.user
        if not user:
            raise Exception("no user")
        profile = _get_profile(sb, str(user.id))
        return _build_user_dict(sb, user, profile), None
    except Exception:
        if not refresh:
            return None, None
        try:
            sb = _sb()
            res = sb.auth.refresh_session(refresh)
            session = res.session
            if not session:
                return None, None
            user = res.user or session.user
            profile = _get_profile(sb, str(user.id))
            return _build_user_dict(sb, user, profile), {
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
            }
        except Exception:
            return None, None


def _get_profile(sb: Client, user_id: str) -> dict:
    try:
        res = sb.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
        return res.data or {}
    except Exception:
        return {}


def _generate_ref_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))


def _build_user_dict(sb: Client, user, profile: dict) -> dict:
    plan = profile.get("plan", "free")
    used = profile.get("credits_used_this_month", 0)
    limit = PLAN_LIMITS.get(plan, 5)
    # Monthly reset — if new month, reset counter in DB too
    reset_str = profile.get("credits_reset_at", "")
    if reset_str:
        try:
            reset_dt = datetime.fromisoformat(reset_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if now.month != reset_dt.month or now.year != reset_dt.year:
                try:
                    sb.table("profiles").update({
                        "credits_used_this_month": 0,
                        "credits_reset_at": now.isoformat(),
                    }).eq("id", str(user.id)).execute()
                except Exception:
                    pass
                used = 0
        except Exception:
            pass
    remaining = 999_999 if plan == "admin" else max(0, limit - used)
    meta = getattr(user, "user_metadata", None) or {}
    if isinstance(meta, dict):
        display = profile.get("display_name") or meta.get("display_name") or meta.get("full_name") or ""
    else:
        display = profile.get("display_name") or ""
    return {
        "id": str(user.id),
        "email": getattr(user, "email", "") or "",
        "display_name": display,
        "plan": plan,
        "credits_used": used,
        "credits_limit": limit,
        "credits_remaining": remaining,
        "referral_code": profile.get("referral_code", ""),
        "referred_by": profile.get("referred_by", ""),
    }


# ─── Profile management ────────────────────────────────────────────────────────

def ensure_profile(user_id: str, email: str, display_name: str = "", referred_by: str = "") -> None:
    try:
        sb = _sb_admin()
        existing = sb.table("profiles").select("id,referral_code").eq("id", user_id).maybe_single().execute()
        if not existing.data:
            # Generate unique referral code
            ref_code = _generate_ref_code()
            for _ in range(5):
                check = sb.table("profiles").select("id").eq("referral_code", ref_code).maybe_single().execute()
                if not check.data:
                    break
                ref_code = _generate_ref_code()
            row = {
                "id": user_id,
                "email": email,
                "display_name": display_name,
                "plan": "free",
                "credits_used_this_month": 0,
                "credits_reset_at": datetime.now(timezone.utc).isoformat(),
                "referral_code": ref_code,
            }
            if referred_by:
                row["referred_by"] = referred_by.upper()[:8]
            sb.table("profiles").insert(row).execute()
            print(f"[ensure_profile] created {email} ref_code={ref_code}", flush=True)

            # Give +1 analysis to the referral code owner
            if referred_by:
                try:
                    owner = sb.table("profiles")\
                        .select("id,credits_used_this_month")\
                        .eq("referral_code", referred_by.upper()[:8])\
                        .maybe_single().execute()
                    if owner.data:
                        current = owner.data.get("credits_used_this_month", 0)
                        sb.table("profiles").update({
                            "credits_used_this_month": max(0, current - 1)
                        }).eq("referral_code", referred_by.upper()[:8]).execute()
                        print(f"[referral] +1 crédito para owner de {referred_by}", flush=True)
                except Exception as e:
                    print(f"[referral ERROR] {e}", flush=True)
        elif existing.data and not existing.data.get("referral_code"):
            ref_code = _generate_ref_code()
            try:
                sb.table("profiles").update({"referral_code": ref_code}).eq("id", user_id).execute()
            except Exception:
                pass
    except Exception as e:
        print(f"[ensure_profile ERROR] {e}", flush=True)


# ─── Credits ──────────────────────────────────────────────────────────────────

def consume_credit(user_id: str, current_used: int) -> None:
    try:
        _sb().table("profiles").update({
            "credits_used_this_month": current_used + 1,
        }).eq("id", user_id).execute()
    except Exception:
        pass


# ─── History ──────────────────────────────────────────────────────────────────

def save_history(user_id: str, job_title: str, score: int, ats_ok: bool, cv_filename: str = "") -> Optional[int]:
    try:
        row = {
            "user_id": user_id,
            "job_title": (job_title or "")[:120],
            "score_match": score,
            "ats_compatible": ats_ok,
            "outcome": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if cv_filename:
            row["cv_filename"] = cv_filename[:200]
        res = _sb_admin().table("history").insert(row).execute()
        if res.data:
            rid = res.data[0].get("id")
            print(f"[save_history] OK id={rid}", flush=True)
            return rid
        print(f"[save_history] No data returned", flush=True)
    except Exception as e:
        print(f"[save_history ERROR] user={user_id} error={e}", flush=True)
    return None


def save_guest_analysis() -> None:
    try:
        _sb().table("guest_analyses").insert({
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass


def update_outcome(history_id: int, outcome: str) -> bool:
    try:
        _sb_admin().table("history").update({"outcome": outcome}).eq("id", history_id).execute()
        return True
    except Exception as e:
        print(f"[update_outcome ERROR] {e}", flush=True)
        return False


def get_history(user_id: str) -> list:
    try:
        res = (
            _sb_admin().table("history")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"[get_history ERROR] {e}", flush=True)
        return []


# ─── CV Storage ───────────────────────────────────────────────────────────────

def save_cv_copy(user_id: str, history_id, cv_original: str, cv_data: dict) -> bool:
    try:
        result = _sb_admin().table("cv_storage").insert({
            "user_id": user_id,
            "history_id": history_id,
            "cv_original_snippet": cv_original[:5000],
            "cv_generated": json.dumps(cv_data, ensure_ascii=False)[:20000],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        ok = bool(result.data)
        print(f"[save_cv_copy] ok={ok}", flush=True)
        return ok
    except Exception as e:
        print(f"[save_cv_copy ERROR] user={user_id} history={history_id} error={e}", flush=True)
        return False


# ─── Feedback ─────────────────────────────────────────────────────────────────

def save_feedback(user_id: Optional[str], email: str, rating: int, comment: str, job_title: str) -> bool:
    try:
        _sb().table("feedback").insert({
            "user_id": user_id,
            "email": email,
            "rating": rating,
            "comment": comment[:500],
            "job_title": (job_title or "")[:120],
            "approved": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception:
        return False


def get_public_reviews() -> list:
    try:
        res = (
            _sb().table("feedback")
            .select("rating,comment,job_title,created_at")
            .eq("approved", True)
            .order("created_at", desc=True)
            .limit(6)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def get_all_feedback() -> list:
    try:
        res = (
            _sb().table("feedback")
            .select("*")
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def approve_feedback(feedback_id, approve: bool) -> bool:
    try:
        _sb().table("feedback").update({"approved": approve}).eq("id", feedback_id).execute()
        return True
    except Exception:
        return False


# ─── Global stats ─────────────────────────────────────────────────────────────

def get_global_stats() -> dict:
    try:
        sb = _sb()
        cvs = sb.table("history").select("id", count="exact").execute()
        guest = sb.table("guest_analyses").select("id", count="exact").execute()
        users = sb.table("profiles").select("id", count="exact").execute()
        total_cvs = (cvs.count or 0) + (guest.count or 0)
        return {
            "cvs": total_cvs + COUNTER_BASE_CVS,
            "users": (users.count or 0) + COUNTER_BASE_USERS,
        }
    except Exception:
        return {"cvs": COUNTER_BASE_CVS, "users": COUNTER_BASE_USERS}


# ─── Activation codes ─────────────────────────────────────────────────────────

def _sanitize_code(raw: str) -> str:
    """Extract code from a referral URL or clean the raw code string."""
    raw = (raw or "").strip()
    match = re.search(r'[?&]ref=([A-Z0-9]+)', raw, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return re.sub(r'[^A-Z0-9]', '', raw.upper())[:20]


def validate_and_use_code(user_id: str, code: str) -> Tuple[bool, str]:
    try:
        code = _sanitize_code(code)
        sb = _sb()
        res = sb.table("activation_codes").select("*").eq("code", code).maybe_single().execute()
        row = res.data
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
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp_dt:
                return False, "Este código ha expirado."
        plan = row.get("grants_plan", "pro_code")
        _sb_admin().table("profiles").update({
            "plan": plan,
            "activation_code": code,
            "credits_used_this_month": 0,
        }).eq("id", user_id).execute()
        sb.table("activation_codes").update({"uses_count": used + 1}).eq("code", code).execute()
        label = PLAN_LIMITS.get(plan, 10)
        return True, f"✅ Código activado. Ahora tienes {label} análisis por mes."
    except Exception:
        return False, "Código inválido."


def get_all_codes() -> list:
    try:
        res = _sb().table("activation_codes").select("*").order("created_at", desc=True).execute()
        return res.data or []
    except Exception:
        return []


def create_code(code: str, description: str, max_uses: int, grants_plan: str, expires_at: Optional[str]) -> bool:
    try:
        _sb().table("activation_codes").insert({
            "code": code.strip().upper(),
            "description": description,
            "max_uses": max_uses if max_uses > 0 else None,
            "grants_plan": grants_plan,
            "uses_count": 0,
            "active": True,
            "expires_at": expires_at or None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True
    except Exception:
        return False


def toggle_code(code_id, active: bool) -> bool:
    try:
        _sb().table("activation_codes").update({"active": active}).eq("id", code_id).execute()
        return True
    except Exception:
        return False


# ─── Admin ────────────────────────────────────────────────────────────────────

def get_admin_users() -> list:
    try:
        res = (
            _sb_admin().table("profiles")
            .select("*")
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def update_user_plan(user_id: str, plan: str) -> Tuple[bool, str]:
    try:
        s = get_settings()
        if not s.supabase_service_key:
            return False, "SUPABASE_SERVICE_KEY no configurada — el cambio de plan requiere permisos de administrador"
        result = _sb_admin().table("profiles").update({"plan": plan}).eq("id", user_id).execute()
        if not result.data:
            return False, f"0 rows updated — user_id={user_id} no encontrado en profiles, o la clave service_role no tiene permisos"
        return True, ""
    except Exception as e:
        return False, str(e)


def reset_user_credits(user_id: str) -> Tuple[bool, str]:
    try:
        _sb_admin().table("profiles").update({
            "credits_used_this_month": 0,
            "credits_reset_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()
        return True, ""
    except Exception as e:
        return False, str(e)


def admin_assign_code(user_id: str, code: str) -> Tuple[bool, str]:
    """Assign an activation code to a user and update their plan."""
    try:
        s = get_settings()
        if not s.supabase_service_key:
            return False, "SUPABASE_SERVICE_KEY no configurada"
        code_upper = code.strip().upper()
        sb = _sb_admin()
        row = sb.table("activation_codes").select("*").eq("code", code_upper).maybe_single().execute()
        if not row or not row.data:
            return False, f"Código '{code_upper}' no encontrado"
        if not row.data.get("active", True):
            return False, f"Código '{code_upper}' no está activo"
        plan = row.data.get("grants_plan", "pro_code")
        result = sb.table("profiles").update({
            "plan": plan,
            "activation_code": code_upper,
            "credits_used_this_month": 0,
        }).eq("id", user_id).execute()
        if not result.data:
            return False, f"0 rows updated — user_id={user_id} no encontrado en profiles"
        sb.table("activation_codes").update({
            "uses_count": (row.data.get("uses_count") or 0) + 1,
        }).eq("code", code_upper).execute()
        return True, ""
    except Exception as e:
        return False, str(e)


def _auth_admin_headers() -> dict:
    """Returns headers for direct Supabase auth admin REST calls."""
    s = get_settings()
    key = s.supabase_service_key
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": "application/json",
    }


def _auth_admin_url(path: str) -> str:
    s = get_settings()
    return f"{s.supabase_url}/auth/v1/admin/{path}"


def admin_send_reset(user_email: str) -> Tuple[bool, str]:
    """Send password reset email to a user via Supabase /auth/v1/recover (actually sends email)."""
    try:
        s = get_settings()
        key = s.supabase_service_key or s.supabase_key
        redirect = f"{RAILWAY_URL}/auth/callback?type=recovery"
        resp = httpx.post(
            f"{s.supabase_url}/auth/v1/recover",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"email": user_email},
            params={"redirect_to": redirect},
            timeout=10,
        )
        if resp.status_code >= 400:
            return False, resp.text
        return True, ""
    except Exception as e:
        return False, str(e)


def admin_ban_user(user_id: str, ban: bool) -> Tuple[bool, str]:
    """Ban or unban a user via Supabase auth admin REST API."""
    try:
        s = get_settings()
        if not s.supabase_service_key:
            return False, "SUPABASE_SERVICE_KEY no configurada"
        ban_duration = "876600h" if ban else "none"
        resp = httpx.put(
            _auth_admin_url(f"users/{user_id}"),
            headers=_auth_admin_headers(),
            json={"ban_duration": ban_duration},
            timeout=10,
        )
        if resp.status_code >= 400:
            return False, resp.text
        return True, ""
    except Exception as e:
        return False, str(e)


def admin_delete_user(user_id: str) -> Tuple[bool, str]:
    """Permanently delete a user: related tables + profiles + Supabase Auth."""
    try:
        s = get_settings()
        if not s.supabase_service_key:
            return False, "SUPABASE_SERVICE_KEY no configurada"
        sb = _sb_admin()
        # 1. Clean related tables (order matters for FK)
        for table in ("cv_storage", "feedback", "history"):
            try:
                sb.table(table).delete().eq("user_id", user_id).execute()
            except Exception:
                pass
        # 2. Delete profile
        try:
            sb.table("profiles").delete().eq("id", user_id).execute()
        except Exception:
            pass
        # 3. Delete from Supabase Auth via REST API
        resp = httpx.delete(
            _auth_admin_url(f"users/{user_id}"),
            headers=_auth_admin_headers(),
            timeout=10,
        )
        # 404 = already gone from Auth — still success
        if resp.status_code >= 400 and resp.status_code != 404:
            return False, f"Auth delete failed ({resp.status_code}): {resp.text}"
        return True, ""
    except Exception as e:
        return False, str(e)


def admin_fix_orphan(email: str) -> Tuple[bool, str]:
    """Find orphan user in Auth (no profile) by email and delete from Auth."""
    try:
        s = get_settings()
        if not s.supabase_service_key:
            return False, "SUPABASE_SERVICE_KEY no configurada"
        resp = httpx.get(
            _auth_admin_url("users"),
            headers=_auth_admin_headers(),
            params={"filter": f"email.eq.{email}"},
            timeout=10,
        )
        if resp.status_code >= 400:
            return False, resp.text
        users_data = resp.json()
        users_list = users_data.get("users", users_data) if isinstance(users_data, dict) else users_data
        if not users_list:
            return False, f"No se encontró usuario con email {email} en Auth"
        user_id = users_list[0].get("id")
        if not user_id:
            return False, "No se pudo obtener el ID del usuario"
        # Verify it's truly an orphan (no profile)
        sb = _sb_admin()
        profile = sb.table("profiles").select("id").eq("id", user_id).maybe_single().execute()
        if profile.data:
            return False, f"Usuario {email} SÍ tiene profile — usa delete normal desde el panel"
        del_resp = httpx.delete(
            _auth_admin_url(f"users/{user_id}"),
            headers=_auth_admin_headers(),
            timeout=10,
        )
        if del_resp.status_code >= 400 and del_resp.status_code != 404:
            return False, f"Error eliminando: {del_resp.text}"
        return True, f"Usuario huérfano {email} eliminado. Ya puede re-registrarse."
    except Exception as e:
        return False, str(e)
