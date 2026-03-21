"""
Admin panel routes — plan == "admin" required for all.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from typing import Optional

from deps import templates
from services.session import (
    get_global_stats, get_admin_users, update_user_plan, reset_user_credits,
    get_all_codes, create_code, toggle_code,
    get_all_feedback, approve_feedback,
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
    stats    = get_global_stats()
    users    = get_admin_users()
    codes    = get_all_codes()
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
        return JSONResponse({"ok": False})
    ok = update_user_plan(user_id, plan)
    return JSONResponse({"ok": ok})


@router.post("/user/{user_id}/reset-credits")
async def reset_credits(request: Request, user_id: str):
    if not _require_admin(request):
        return JSONResponse({"ok": False})
    ok = reset_user_credits(user_id)
    return JSONResponse({"ok": ok})


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
        return JSONResponse({"ok": False})
    exp = expires_at.strip() if expires_at and expires_at.strip() else None
    ok = create_code(code, description, max_uses, grants_plan, exp)
    return JSONResponse({"ok": ok})


@router.post("/codes/{code_id}/toggle")
async def admin_toggle_code(request: Request, code_id: int, active: str = Form(...)):
    if not _require_admin(request):
        return JSONResponse({"ok": False})
    ok = toggle_code(code_id, active.lower() == "true")
    return JSONResponse({"ok": ok})


@router.post("/feedback/{feedback_id}/approve")
async def admin_approve_fb(request: Request, feedback_id: int):
    if not _require_admin(request):
        return JSONResponse({"ok": False})
    ok = approve_feedback(feedback_id, True)
    return JSONResponse({"ok": ok})


@router.post("/feedback/{feedback_id}/reject")
async def admin_reject_fb(request: Request, feedback_id: int):
    if not _require_admin(request):
        return JSONResponse({"ok": False})
    ok = approve_feedback(feedback_id, False)
    return JSONResponse({"ok": ok})
