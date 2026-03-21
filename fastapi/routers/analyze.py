"""
Main analysis routes — Phase 2 with auth + credits.
"""
import uuid
import time
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse

from config import get_settings
from deps import templates
from services.claude import optimize_cv
from services.extractor import extract_pdf, extract_docx, scrape_job_url, is_valid_url
from services.builder import DOCX_BUILDERS, build_cv_pdf, TEMPLATES_META
from services.session import get_user_credits, consume_credit

router = APIRouter()

# ─── In-memory result cache ────────────────────────────────────────────────────
_result_cache: dict = {}
_CACHE_TTL = 3600  # 1 hour


def _store_result(cv_data: dict) -> str:
    result_id = str(uuid.uuid4())
    _result_cache[result_id] = {"data": cv_data, "ts": time.time()}
    now = time.time()
    expired = [k for k, v in _result_cache.items() if now - v["ts"] > _CACHE_TTL]
    for k in expired:
        del _result_cache[k]
    return result_id


def _get_result(result_id: str) -> Optional[dict]:
    entry = _result_cache.get(result_id)
    if not entry:
        return None
    if time.time() - entry["ts"] > _CACHE_TTL:
        del _result_cache[result_id]
        return None
    return entry["data"]


# ─── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user": request.state.user,
    })


@router.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    cv_file: Optional[UploadFile] = File(None),
    cv_text_raw: str = Form(""),
    job_input: str = Form(""),
    max_pages: int = Form(2),
    font_size: float = Form(11.0),
    career_change: bool = Form(False),
    cv_only: bool = Form(False),
    output_lang: str = Form("es"),
):
    settings = get_settings()
    user = request.state.user

    if not settings.anthropic_api_key:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": user,
            "error": "No se encontró ANTHROPIC_API_KEY. Configura la variable de entorno.",
        })

    # ── Credit / guest limit check ─────────────────────────────────────────────
    if user:
        credits = await get_user_credits(user["id"])
        if credits["credits_remaining"] <= 0:
            plan_labels = {
                "free": "gratuito (5/mes)",
                "pro_code": "Pro Code (10/mes)",
                "pro": "Pro (50/mes)",
            }
            label = plan_labels.get(credits["plan"], credits["plan"])
            return templates.TemplateResponse("index.html", {
                "request": request,
                "user": user,
                "error": (
                    f"Has usado todos tus análisis del mes — plan {label}. "
                    "Actualiza tu plan para continuar."
                ),
            })
    else:
        # Guests: 1 free analysis per session
        guest_count = int(request.cookies.get("guest_analyses_count", "0"))
        if guest_count >= 1:
            return templates.TemplateResponse("index.html", {
                "request": request,
                "user": user,
                "error": "Has agotado tu análisis gratuito. Crea una cuenta para continuar.",
                "show_auth_modal": True,
            })

    # ── Extract CV text ────────────────────────────────────────────────────────
    cv_text = ""
    if cv_file and cv_file.filename:
        file_bytes = await cv_file.read()
        fname = cv_file.filename.lower()
        try:
            if fname.endswith(".pdf"):
                cv_text = extract_pdf(file_bytes)
            elif fname.endswith(".docx"):
                cv_text = extract_docx(file_bytes)
            else:
                return templates.TemplateResponse("index.html", {
                    "request": request,
                    "user": user,
                    "error": "Formato de CV no soportado. Sube un PDF o DOCX.",
                })
        except Exception as e:
            return templates.TemplateResponse("index.html", {
                "request": request,
                "user": user,
                "error": f"Error al leer el archivo: {e}",
            })
    elif cv_text_raw.strip():
        cv_text = cv_text_raw.strip()

    if not cv_text:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": user,
            "error": "Sube un CV o pega el texto directamente.",
        })

    # ── Extract job text ───────────────────────────────────────────────────────
    job_text = ""
    job_input = job_input.strip()
    if is_valid_url(job_input):
        try:
            job_text = scrape_job_url(job_input)
        except ValueError as e:
            return templates.TemplateResponse("index.html", {
                "request": request,
                "user": user,
                "error": str(e),
                "cv_text_raw": cv_text_raw,
            })
    elif job_input:
        job_text = job_input

    if not job_text and not cv_only:
        cv_only = True

    # ── Run Claude ─────────────────────────────────────────────────────────────
    try:
        cv_data = optimize_cv(
            cv_text=cv_text,
            job_text=job_text,
            max_pages=max_pages,
            font_size=font_size,
            api_key=settings.anthropic_api_key,
            career_change=career_change,
            cv_only=cv_only,
            output_lang=output_lang,
        )
    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "user": user,
            "error": f"Error al analizar con Claude: {e}",
        })

    result_id = _store_result(cv_data)

    # ── Consume credit ─────────────────────────────────────────────────────────
    if user:
        await consume_credit(user["id"])

    resp = templates.TemplateResponse("results.html", {
        "request": request,
        "user": user,
        "cv": cv_data,
        "result_id": result_id,
        "templates_meta": TEMPLATES_META,
        "score": cv_data.get("score_match", 0),
        "ats_ok": cv_data.get("ats_compatible", True),
        "ats_detected": cv_data.get("ats_detectado", ""),
        "ats_reason": cv_data.get("ats_razon", ""),
        "score_explain": cv_data.get("score_explicacion", ""),
        "score_desglose": cv_data.get("score_desglose", {}),
        "keywords_ok": cv_data.get("keywords_integradas", []),
        "keywords_miss": cv_data.get("keywords_faltantes", []),
        "coaching": cv_data.get("coaching", []),
        "was_truncated": cv_data.get("_was_truncated", False),
        "model_used": cv_data.get("_model_used", "haiku"),
    })

    # Track guest's free analysis (cookie allows download later)
    if not user:
        resp.set_cookie("guest_analyses_count", "1", max_age=86400, samesite="lax", httponly=False)
        resp.set_cookie("guest_result_id", result_id, max_age=86400, samesite="lax", httponly=False)

    return resp


@router.get("/download/{result_id}")
async def download(request: Request, result_id: str, fmt: str = "docx", template: str = "Clásico"):
    user = request.state.user
    guest_result_id = request.cookies.get("guest_result_id", "")

    # Auth check: logged in OR downloading their own guest-session result
    if not user and result_id != guest_result_id:
        return RedirectResponse(
            f"/?show_auth=1&next=/download/{result_id}%3Ffmt%3D{fmt}%26template%3D{quote(template)}",
            status_code=302,
        )

    cv_data = _get_result(result_id)
    if not cv_data:
        raise HTTPException(status_code=404, detail="Resultado expirado. Vuelve a analizar tu CV.")

    nombre = cv_data.get("nombre", "CV").replace(" ", "_")

    if fmt == "docx":
        builder = DOCX_BUILDERS.get(template, DOCX_BUILDERS["Clásico"])
        buf = builder(cv_data)
        filename = f"CV_{nombre}_{template}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fmt == "pdf":
        buf = build_cv_pdf(cv_data, template)
        filename = f"CV_{nombre}_{template}.pdf"
        media_type = "application/pdf"
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado. Usa 'docx' o 'pdf'.")

    return StreamingResponse(
        buf,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
