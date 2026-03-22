"""
Auth routes: set-session, callback, logout, reset-password, activate-code.
"""
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from config import get_settings
from deps import templates
from services.session import ensure_profile, validate_and_use_code, RAILWAY_URL

router = APIRouter(prefix="/auth")

COOKIE_MAX_ACCESS  = 86_400        # 24 h
COOKIE_MAX_REFRESH = 86_400 * 30   # 30 days


@router.post("/set-session")
async def set_session(request: Request):
    """Browser JS calls this after Supabase PKCE exchange or OAuth."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid body"}, status_code=400)

    access  = body.get("access_token", "")
    refresh = body.get("refresh_token", "")
    user_id = body.get("user_id", "")
    email   = body.get("email", "")
    display = body.get("display_name", "")

    if not access:
        return JSONResponse({"ok": False, "error": "missing token"}, status_code=400)

    if user_id and email:
        ensure_profile(user_id, email, display)

    response = JSONResponse({"ok": True})
    response.set_cookie("sb_access_token",  access,  max_age=COOKIE_MAX_ACCESS,  httponly=True, samesite="lax", secure=True)
    response.set_cookie("sb_refresh_token", refresh, max_age=COOKIE_MAX_REFRESH, httponly=True, samesite="lax", secure=True)
    return response


@router.get("/callback", response_class=HTMLResponse)
async def auth_callback(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(request, "auth_callback.html", {
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_KEY": settings.supabase_key,
        "RAILWAY_URL": RAILWAY_URL,
    })


@router.post("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("sb_access_token")
    response.delete_cookie("sb_refresh_token")
    return response


@router.post("/reset-password")
async def reset_password(email: str = Form(...)):
    try:
        from supabase import create_client
        s = get_settings()
        sb = create_client(s.supabase_url, s.supabase_key)
        redirect = RAILWAY_URL + "/auth/callback?type=recovery"
        sb.auth.reset_password_email(email, options={"redirect_to": redirect})
        return JSONResponse({"ok": True, "msg": "Email enviado. Revisa tu bandeja."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})


@router.get("/update-password", response_class=HTMLResponse)
async def update_password_form(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(request, "update_password.html", {
        "SUPABASE_URL": settings.supabase_url,
        "SUPABASE_KEY": settings.supabase_key,
    })


@router.post("/activate-code")
async def activate_code(request: Request, code: str = Form(...)):
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse({"ok": False, "error": "Debes iniciar sesión primero."})
    ok, msg = validate_and_use_code(user["id"], code)
    return JSONResponse({"ok": ok, "msg": msg})
