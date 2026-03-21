"""History routes — /historial and outcome updates."""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from deps import templates
from services.session import get_history, update_outcome

router = APIRouter(tags=["history"])


@router.get("/historial", response_class=HTMLResponse)
async def historial(request: Request):
    user = request.state.user
    if not user:
        return RedirectResponse("/?show_auth=1", status_code=302)

    history = get_history(user["id"])
    return templates.TemplateResponse("historial.html", {
        "request": request,
        "user": user,
        "history": history,
    })


@router.post("/history/{history_id}/outcome")
async def set_outcome(request: Request, history_id: str, outcome: str = Form(...)):
    user = request.state.user
    if not user:
        return JSONResponse({"ok": False, "error": "No autenticado."}, status_code=401)
    ok = update_outcome(history_id, outcome)
    return JSONResponse({"ok": ok})
