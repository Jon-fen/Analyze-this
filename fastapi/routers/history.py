"""
History routes: GET /historial, POST /history/{id}/outcome
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services.session import get_history, update_outcome

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/historial", response_class=HTMLResponse)
async def historial(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        return RedirectResponse(url="/?show_auth=1", status_code=303)
    history = get_history(user["id"])
    return templates.TemplateResponse("historial.html", {
        "request": request,
        "user": user,
        "history": history,
    })


@router.post("/history/{history_id}/outcome")
async def save_outcome(request: Request, history_id: int, outcome: str = Form(...)):
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse({"ok": False, "error": "no auth"})
    ok = update_outcome(history_id, outcome)
    return JSONResponse({"ok": ok})
