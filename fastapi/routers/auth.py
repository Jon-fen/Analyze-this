"""Auth routes — session management via Supabase JS client + server-side cookies."""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from supabase import create_client
from config import get_settings
from deps import templates
from services.session import ensure_profile, validate_and_use_code

router = APIRouter(prefix="/auth", tags=["auth"])

RAILWAY_URL = "https://analyze-this-production.up.railway.app"


def _sb():
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_key)


def _set_cookies(response, access_token: str, refresh_token: str):
    response.set_cookie("sb_access_token", access_token, httponly=True, max_age=86400, samesite="lax")
    response.set_cookie("sb_refresh_token", refresh_token, httponly=True, max_age=86400 * 30, samesite="lax")


def _clear_cookies(response):
    response.delete_cookie("sb_access_token", samesite="lax")
    response.delete_cookie("sb_refresh_token", samesite="lax")


@router.post("/set-session")
async def set_session(request: Request):
    """
    Called by the Supabase JS client after successful auth (login, magic link, OAuth).
    Also creates the profile row on first login.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    access_token  = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "")
    user_id       = body.get("user_id", "")
    email         = body.get("email", "")
    display_name  = body.get("display_name", "")

    if not access_token:
        return JSONResponse({"ok": False, "error": "Missing token"}, status_code=400)

    # Create profile if first-ever login
    if user_id and email:
        ensure_profile(user_id, email, display_name)

    resp = JSONResponse({"ok": True})
    _set_cookies(resp, access_token, refresh_token)
    return resp


@router.get("/callback", response_class=HTMLResponse)
async def auth_callback(request: Request):
    """Handles Google OAuth and magic-link callbacks via Supabase JS SDK."""
    return templates.TemplateResponse("auth_callback.html", {"request": request})


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    _clear_cookies(resp)
    return resp


@router.post("/reset-password")
async def reset_password(email: str = Form(...)):
    """Send password reset email."""
    settings = get_settings()
    if not settings.supabase_url:
        return JSONResponse({"ok": False, "error": "Servicio no disponible."})
    try:
        client = _sb()
        client.auth.reset_password_email(
            email,
            options={"redirect_to": f"{RAILWAY_URL}/auth/callback"},
        )
        return JSONResponse({"ok": True, "message": "Te enviamos un email con el link de recuperación."})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@router.post("/activate-code")
async def activate_code(request: Request, code: str = Form(...)):
    """Apply an activation code to the logged-in user's account."""
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False, "error": "Debes iniciar sesión primero."}, status_code=401)
    ok, msg = validate_and_use_code(user["id"], code)
    return JSONResponse({"ok": ok, "message": msg})
