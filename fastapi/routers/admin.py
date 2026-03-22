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
    admin_send_reset, admin_ban_user, admin_delete_user, admin_fix_orphan,
    PLAN_LIMITS, _sb_admin,
)
from services.email_service import send_notification_email

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
    return templates.TemplateResponse(request, "admin.html", {
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
    if ok:
        try:
            profile = _sb_admin().table("profiles").select("email").eq("id", user_id).maybe_single().execute()
            email = (profile.data or {}).get("email", "")
            if email:
                plan_label = PLAN_LIMITS.get(plan, plan)
                send_notification_email(
                    email,
                    "Tu plan en Analyze-This ha cambiado",
                    f"""<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
                    <h2 style="color:#1B4F8A">Analyze-This · CV Optimizer ATS</h2>
                    <p>Hola,</p>
                    <p>Tu plan ha sido actualizado a <strong>{plan.upper()}</strong> ({plan_label} análisis/mes).</p>
                    <p>Inicia sesión en <a href="https://analyze-this-production.up.railway.app">Analyze-This</a> para usar tus nuevos créditos.</p>
                    <p style="font-size:12px;color:#888">Si crees que esto es un error, responde a este email.</p>
                    </div>""",
                )
        except Exception:
            pass
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


@router.post("/user/fix-orphan")
async def fix_orphan_user(request: Request, email: str = Form(...)):
    """Delete orphan Auth user (no profile) so email can re-register."""
    if not _require_admin(request):
        return JSONResponse({"ok": False, "error": "no auth"})
    ok, err = admin_fix_orphan(email)
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

