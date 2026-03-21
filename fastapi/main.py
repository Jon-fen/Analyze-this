from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response

from config import get_settings
from deps import templates
from routers import analyze
from routers import auth as auth_router
from services.session import validate_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Expose Supabase public config to all Jinja2 templates as globals
    settings = get_settings()
    templates.env.globals["SUPABASE_URL"] = settings.supabase_url
    templates.env.globals["SUPABASE_KEY"] = settings.supabase_key
    yield


app = FastAPI(
    title="Analyze-This · CV Optimizer ATS",
    description="Optimiza tu CV para cualquier oferta laboral con IA",
    version="2.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(analyze.router)
app.include_router(auth_router.router)


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    """Attaches request.state.user to every request, refreshes tokens if needed."""
    request.state.user = None
    new_tokens = None

    # Skip expensive Supabase call for static assets
    if not request.url.path.startswith("/static"):
        user, new_tokens = await validate_session(request)
        request.state.user = user

    response: Response = await call_next(request)

    # Persist refreshed tokens if they were rotated
    if new_tokens:
        response.set_cookie(
            "sb_access_token", new_tokens["access_token"],
            httponly=True, max_age=3600, samesite="lax",
        )
        response.set_cookie(
            "sb_refresh_token", new_tokens["refresh_token"],
            httponly=True, max_age=86400 * 30, samesite="lax",
        )

    return response
