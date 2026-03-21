from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response, JSONResponse

from config import get_settings
from deps import templates
from routers import analyze
from routers import auth as auth_router
from routers import tools as tools_router
from routers import history as history_router
from routers import admin as admin_router
from services.session import validate_session, save_feedback


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.include_router(tools_router.router)
app.include_router(history_router.router)
app.include_router(admin_router.router)


@app.post("/feedback")
async def post_feedback(request: Request):
    """Save quality feedback from results page."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    user     = request.state.user
    rating   = body.get("rating", 5)
    comment  = body.get("comment", "")
    job_title = body.get("job_title", "")
    email    = (user or {}).get("email", body.get("email", ""))
    user_id  = (user or {}).get("id")

    ok = save_feedback(user_id, email, rating, comment, job_title)
    return JSONResponse({"ok": ok})


@app.middleware("http")
async def session_middleware(request: Request, call_next):
    """Attaches request.state.user to every request, refreshes tokens if needed."""
    request.state.user = None
    new_tokens = None

    if not request.url.path.startswith("/static"):
        user, new_tokens = await validate_session(request)
        request.state.user = user

    response: Response = await call_next(request)

    if new_tokens:
        response.set_cookie("sb_access_token", new_tokens["access_token"],
                            httponly=True, max_age=86400, samesite="lax")
        response.set_cookie("sb_refresh_token", new_tokens["refresh_token"],
                            httponly=True, max_age=86400 * 30, samesite="lax")

    return response
