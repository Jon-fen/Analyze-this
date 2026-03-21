"""Auth routes — session management via Supabase JS client + server-side cookies."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from deps import templates

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_cookies(response, access_token: str, refresh_token: str):
    response.set_cookie(
        "sb_access_token", access_token,
        httponly=True, max_age=3600, samesite="lax",
    )
    response.set_cookie(
        "sb_refresh_token", refresh_token,
        httponly=True, max_age=86400 * 30, samesite="lax",
    )


def _clear_cookies(response):
    response.delete_cookie("sb_access_token", samesite="lax")
    response.delete_cookie("sb_refresh_token", samesite="lax")


@router.post("/set-session")
async def set_session(request: Request):
    """
    Called by the Supabase JS client after a successful auth event
    (email/password login, magic link, or Google OAuth).
    Stores the tokens as HTTP-only cookies.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    access_token = body.get("access_token", "")
    refresh_token = body.get("refresh_token", "")
    if not access_token:
        return JSONResponse({"ok": False, "error": "Missing token"}, status_code=400)

    resp = JSONResponse({"ok": True})
    _set_cookies(resp, access_token, refresh_token)
    return resp


@router.get("/callback", response_class=HTMLResponse)
async def auth_callback(request: Request):
    """
    Supabase redirects here after Google OAuth and magic-link clicks.
    A tiny JS snippet uses the Supabase JS client to exchange the code
    for a session and then calls /auth/set-session to persist the tokens.
    """
    return templates.TemplateResponse("auth_callback.html", {"request": request})


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    _clear_cookies(resp)
    return resp
