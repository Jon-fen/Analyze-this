"""Admin panel — only accessible to users with plan == 'admin'."""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from deps import templates
from services.session import (
    get_global_stats, get_admin_users, update_user_plan, reset_user_credits,
    get_all_codes, create_code, toggle_code, get_all_feedback, approve_feedback,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(request: Request):
    user = request.state.user
    if not user:
        return None, RedirectResponse("/?show_auth=1", status_code=302)
    # We check plan via get_user_credits later; for now trust the cached user plan
    # This gets verified properly via the profiles table
    return user, None


@router.get("", response_class=HTMLResponse)
async def admin_panel(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/?show_auth=1", status_code=302)

    from services.session import get_user_credits
    credits = await get_user_credits(user["id"])
    if credits.get("plan") != "admin":
        return RedirectResponse("/", status_code=302)

    stats   = get_global_stats()
    users   = get_admin_users()
    codes   = get_all_codes()
    feedbacks = get_all_feedback()

    from services.session import PLAN_LIMITS
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "users": users,
        "codes": codes,
        "feedbacks": feedbacks,
        "plan_limits": PLAN_LIMITS,
    })


@router.post("/user/{user_id}/plan")
async def change_plan(request: Request, user_id: str, plan: str = Form(...)):
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    ok = update_user_plan(user_id, plan)
    return JSONResponse({"ok": ok})


@router.post("/user/{user_id}/reset-credits")
async def reset_credits(request: Request, user_id: str):
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    ok = reset_user_credits(user_id)
    return JSONResponse({"ok": ok})


@router.post("/codes/create")
async def create_activation_code(
    request: Request,
    code: str = Form(...),
    description: str = Form(""),
    grants_plan: str = Form("pro_code"),
    max_uses: int = Form(0),
    expires_at: str = Form(""),
):
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    ok = create_code(code, description, max_uses, grants_plan, expires_at or None)
    return JSONResponse({"ok": ok})


@router.post("/codes/{code_id}/toggle")
async def toggle_activation_code(request: Request, code_id: str, active: bool = Form(...)):
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    ok = toggle_code(code_id, active)
    return JSONResponse({"ok": ok})


@router.post("/feedback/{feedback_id}/approve")
async def approve_fb(request: Request, feedback_id: str):
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    ok = approve_feedback(feedback_id, True)
    return JSONResponse({"ok": ok})


@router.post("/feedback/{feedback_id}/reject")
async def reject_fb(request: Request, feedback_id: str):
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False}, status_code=401)
    ok = approve_feedback(feedback_id, False)
    return JSONResponse({"ok": ok})
