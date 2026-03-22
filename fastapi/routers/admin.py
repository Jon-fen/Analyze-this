"""
Admin panel routes — plan == "admin" required for all.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from typing import Optional

from deps import templates
from services.session import (
    get_global_stats, get_admin_users, update_user_plan, reset_user_credits,
    get_all_codes, create_code, toggle_code, admin_assign_code,
    get_all_feedback, approve_feedback,
    admin_send_reset, admin_ban_user, admin_delete_user,
    PLAN_LIMITS,
)

router = APIRouter(prefix="/admin")


def _require_admin(request: Request):
    user = getattr(request.state, "user", None)
    if not user or user.get("plan") != "admin":
        return False
    return True


@router.get("", response_class=HTMLResponse)
async def admin_panel(request: Request):
    if not _require_admin(request):
        return RedirectResponse(url="/", status_code=303)
    stats     = get_global_stats()
    users     = get_admin_users()
    codes     = get_all_codes()
    feedbacks = get_all_feedback()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": request.state.user,
        "stats": stats,
        "users": users,
        "codes": codes,
        "feedbacks": feedbacks,
        "plan_limits": PLAN_LIMITS,
    })


@router.post("/user/{user_id}/plan")
async def change_plan(request: Request, user_id: str, plan: str = Form(...)):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok, err = update_user_plan(user_id, plan)
    return JSONResponse({"ok": ok, "error": err})


@router.post("/user/{user_id}/reset-credits")
async def reset_credits(request: Request, user_id: str):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok, err = reset_user_credits(user_id)
    return JSONResponse({"ok": ok, "error": err})


@router.post("/user/{user_id}/assign-code")
async def assign_code(request: Request, user_id: str, code: str = Form(...)):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok, err = admin_assign_code(user_id, code)
    return JSONResponse({"ok": ok, "error": err})


@router.post("/user/{user_id}/send-reset")
async def send_reset(request: Request, user_id: str, email: str = Form(...)):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok, err = admin_send_reset(email)
    return JSONResponse({"ok": ok, "error": err})


@router.post("/user/{user_id}/ban")
async def ban_user(request: Request, user_id: str, ban: str = Form(...)):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok, err = admin_ban_user(user_id, ban.lower() == "true")
    return JSONResponse({"ok": ok, "error": err})


@router.post("/user/{user_id}/delete")
async def delete_user(request: Request, user_id: str):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok, err = admin_delete_user(user_id)
    return JSONResponse({"ok": ok, "error": err})


@router.post("/codes/create")
async def admin_create_code(
    request: Request,
    code: str = Form(...),
    description: str = Form(""),
    grants_plan: str = Form("pro_code"),
    max_uses: int = Form(0),
    expires_at: Optional[str] = Form(None),
):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    exp = expires_at.strip() if expires_at and expires_at.strip() else None
    ok = create_code(code, description, max_uses, grants_plan, exp)
    return JSONResponse({"ok": ok})


@router.post("/codes/{code_id}/toggle")
async def admin_toggle_code(request: Request, code_id: int, active: str = Form(...)):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok = toggle_code(code_id, active.lower() == "true")
    return JSONResponse({"ok": ok})


@router.post("/feedback/{feedback_id}/approve")
async def admin_approve_fb(request: Request, feedback_id: int):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok = approve_feedback(feedback_id, True)
    return JSONResponse({"ok": ok})


@router.post("/feedback/{feedback_id}/reject")
async def admin_reject_fb(request: Request, feedback_id: int):
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok = approve_feedback(feedback_id, False)
    return JSONResponse({"ok": ok})


# ── TEMPORARY DIAGNOSTIC — REMOVE AFTER USE ──────────────────────────────────
@router.get("/diagnose")
async def diagnose(request: Request):
    """Runs the service_key diagnostic test. Admin session required."""
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    import os
    from supabase import create_client
    from config import get_settings
    s = get_settings()
    result = {
        "supabase_url": s.supabase_url[:40] if s.supabase_url else "MISSING",
        "anon_key_prefix": s.supabase_key[:20] if s.supabase_key else "MISSING",
        "service_key_set": bool(s.supabase_service_key),
        "service_key_prefix": s.supabase_service_key[:20] if s.supabase_service_key else "MISSING",
    }
    # Test 1: anon client reads profiles
    try:
        c = create_client(s.supabase_url, s.supabase_key)
        r = c.table("profiles").select("id,email,plan").limit(3).execute()
        result["anon_profiles"] = r.data
    except Exception as e:
        result["anon_profiles_error"] = str(e)
    # Test 2: service_role client reads profiles
    if s.supabase_service_key:
        try:
            c2 = create_client(s.supabase_url, s.supabase_service_key)
            r2 = c2.table("profiles").select("id,email,plan").limit(3).execute()
            result["service_profiles"] = r2.data
        except Exception as e:
            result["service_profiles_error"] = str(e)
    # Test 3: service_role tries UPDATE on a non-existent id
    if s.supabase_service_key:
        try:
            c3 = create_client(s.supabase_url, s.supabase_service_key)
            r3 = c3.table("profiles").update({"plan": "free"}).eq("id", "00000000-0000-0000-0000-000000000000").execute()
            result["update_test_rows_affected"] = len(r3.data) if r3.data else 0
        except Exception as e:
            result["update_test_error"] = str(e)
    return JSONResponse(result)
