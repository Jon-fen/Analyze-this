"""
Email sending routes: POST /email/send-cv, POST /email/send-report
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse
from typing import Optional

from services.email_service import send_pdf_email
from services.builder import build_analysis_pdf, build_branded_pdf

router = APIRouter(prefix="/email")

# Import the result cache from analyze router
def _get_cached_result(result_id: str):
    from routers.analyze import _get_result
    return _get_result(result_id)


@router.post("/send-cv")
async def send_cv_email(
    request: Request,
    result_id: str = Form(...),
    to_email: str = Form(...),
    fmt: str = Form("analysis_pdf"),
    template: str = Form("Clásico"),
):
    """Send CV analysis PDF or CV PDF by email."""
    cv_data = _get_cached_result(result_id)
    if not cv_data:
        return JSONResponse({"ok": False, "error": "Resultado expirado. Vuelve a analizar tu CV."})

    nombre = cv_data.get("nombre", "CV")

    if fmt == "analysis_pdf":
        buf = build_analysis_pdf(cv_data)
        filename = f"Analisis_ATS_{nombre.replace(' ', '_')}.pdf"
        subject = f"Análisis ATS de {nombre} · Analyze-This"
    else:
        from services.builder import build_cv_pdf
        buf = build_cv_pdf(cv_data, template)
        filename = f"CV_{nombre.replace(' ', '_')}_{template}.pdf"
        subject = f"CV optimizado de {nombre} · Analyze-This"

    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <h2 style="color: #1B4F8A;">Analyze-This · CV Optimizer ATS</h2>
      <p>Hola,</p>
      <p>Te enviamos el documento adjunto generado por <strong>Analyze-This</strong>.</p>
      <p>El archivo adjunto es: <strong>{filename}</strong></p>
      <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
      <p style="font-size: 12px; color: #888;">
        Generado en <a href="https://analyze-this-production.up.railway.app">analyze-this-production.up.railway.app</a>
      </p>
    </div>
    """

    ok, err = send_pdf_email(to_email, subject, body, buf, filename)
    return JSONResponse({"ok": ok, "error": err if not ok else ""})


@router.post("/send-report")
async def send_report_email(
    request: Request,
    result_id: str = Form(...),
    to_email: str = Form(...),
    tool_type: str = Form(...),  # "carta", "entrevista", "linkedin"
    content: str = Form(...),
):
    """Send a carta/entrevista/linkedin report as PDF by email."""
    cv_data = _get_cached_result(result_id)
    nombre = cv_data.get("nombre", "Candidato") if cv_data else "Candidato"

    titles = {
        "carta": "Carta de Presentación",
        "entrevista": "Preparación de Entrevista",
        "linkedin": "Optimización LinkedIn",
    }
    title = titles.get(tool_type, tool_type.capitalize())
    filename = f"{title.replace(' ', '_')}_{nombre.replace(' ', '_')}.pdf"
    subject = f"{title} · {nombre} · Analyze-This"

    buf = build_branded_pdf(title, content, nombre)
    body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <h2 style="color: #1B4F8A;">Analyze-This · CV Optimizer ATS</h2>
      <p>Hola,</p>
      <p>Adjuntamos tu <strong>{title}</strong> personalizado.</p>
      <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
      <p style="font-size: 12px; color: #888;">
        Generado en <a href="https://analyze-this-production.up.railway.app">analyze-this-production.up.railway.app</a>
      </p>
    </div>
    """
    ok, err = send_pdf_email(to_email, subject, body, buf, filename)
    return JSONResponse({"ok": ok, "error": err if not ok else ""})
