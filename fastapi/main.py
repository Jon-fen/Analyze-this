from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response

from config import get_settings
from deps import templates                        # shared instance
from services.session import validate_session
from routers import analyze, auth, tools, history, admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inject Supabase config into the shared templates env ONCE at startup.
    # Because every router imports `templates` from deps.py (same object),
    # these globals are visible in every template that is rendered.
    s = get_settings()
    templates.env.globals["SUPABASE_URL"] = s.supabase_url
    templates.env.globals["SUPABASE_KEY"] = s.supabase_key
    yield


app = FastAPI(
    title="Analyze-This · CV Optimizer ATS",
    description="Optimiza tu CV para cualquier oferta laboral con IA",
    version="2.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Session middleware ────────────────────────────────────────────────────────

@app.middleware("http")
async def session_middleware(request: Request, call_next):
    user, new_tokens = validate_session(request)
    request.state.user = user
    response: Response = await call_next(request)
    if new_tokens:
        response.set_cookie("sb_access_token",  new_tokens["access_token"],  max_age=86400,      httponly=True, samesite="lax", secure=True)
        response.set_cookie("sb_refresh_token", new_tokens["refresh_token"], max_age=86400 * 30, httponly=True, samesite="lax", secure=True)
    return response


# ─── Routers ──────────────────────────────────────────────────────────────────

app.include_router(auth.router)
app.include_router(tools.router)
app.include_router(history.router)
app.include_router(admin.router)
app.include_router(analyze.router)   # last — catches "/" and "/analyze"
