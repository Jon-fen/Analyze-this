"""Next-step tools — carta, entrevista, linkedin. Return JSON with text + PDF download."""
import anthropic
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response
from config import get_settings
from services.builder import build_branded_pdf

router = APIRouter(prefix="/tools", tags=["tools"])


def _run_claude(prompt: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


TOOL_LABELS = {
    "carta":       "Carta de Presentación",
    "entrevista":  "Preparación de Entrevista",
    "linkedin":    "Optimización LinkedIn",
}


def _make_prompt(tool: str, nombre: str, titulo: str, resumen: str, skills: str) -> str:
    if tool == "carta":
        return f"""Escribe una carta de presentación para el puesto de {titulo}.
Empieza con una idea potente (NO empieces con "Me postulo para..." ni "Mi nombre es...").
Conecta la experiencia específica del candidato con las necesidades exactas del puesto.
Termina transmitiendo confianza y con un llamado a la acción natural.
Máximo 200 palabras. Tono profesional pero humano.

Perfil del candidato:
Nombre: {nombre}
Resumen: {resumen}
Habilidades clave: {skills}

Escribe solo la carta, sin títulos ni explicaciones adicionales."""

    if tool == "entrevista":
        return f"""Soy candidato al puesto de {titulo}.
Dame exactamente:
1. Las 8 preguntas más probables en la entrevista para este cargo
2. Para cada pregunta: una estructura de respuesta sólida usando mi experiencia real (método STAR cuando aplique)
3. Al final: 3 preguntas inteligentes que YO le haría al entrevistador para demostrar pensamiento estratégico

Mi perfil:
{resumen}
Habilidades: {skills}

Sé específico y práctico. Evita respuestas genéricas."""

    if tool == "linkedin":
        return f"""Reescribe estas 3 secciones de mi perfil LinkedIn para posicionarme en búsquedas de reclutadores para el puesto de {titulo}:

1. TÍTULO PROFESIONAL (máximo 220 caracteres, incluye keywords del sector)
2. SECCIÓN 'ACERCA DE' (máximo 2.600 caracteres, primera persona, comienza con gancho, termina con CTA)
3. DESCRIPCIÓN DE EXPERIENCIA más reciente (máximo 5 bullets con logros cuantificados)

Mi perfil actual:
{resumen}
Habilidades: {skills}

Haz que cada palabra tenga peso. Optimiza para el algoritmo de LinkedIn y para reclutadores humanos."""

    return ""


@router.post("/generate")
async def generate_tool(request: Request):
    """
    Body JSON: { tool, nombre, titulo, resumen, skills }
    Returns: { ok, text }
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return JSONResponse({"ok": False, "error": "API key no configurada."}, status_code=500)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    tool    = body.get("tool", "")
    nombre  = body.get("nombre", "")
    titulo  = body.get("titulo", "")
    resumen = body.get("resumen", "")
    skills  = body.get("skills", "")

    if tool not in TOOL_LABELS:
        return JSONResponse({"ok": False, "error": f"Herramienta '{tool}' no válida."}, status_code=400)

    prompt = _make_prompt(tool, nombre, titulo, resumen, skills)
    try:
        text = _run_claude(prompt, settings.anthropic_api_key)
        return JSONResponse({"ok": True, "text": text, "label": TOOL_LABELS[tool]})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/pdf")
async def tool_pdf(request: Request):
    """
    Body JSON: { tool, text, nombre }
    Returns: PDF file download.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Invalid JSON"}, status_code=400)

    tool   = body.get("tool", "")
    text   = body.get("text", "")
    nombre = body.get("nombre", "")
    title  = TOOL_LABELS.get(tool, tool.capitalize())

    try:
        buf = build_branded_pdf(title, text, nombre)
        filename = f"{tool}_{nombre.replace(' ', '_')}.pdf"
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
