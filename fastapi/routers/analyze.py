"""
Main analysis routes — core of the product.
"""
import uuid
import time
from typing import Optional
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse

from config import get_settings
from deps import templates
from services.claude import optimize_cv
from services.extractor import extract_pdf, extract_docx, scrape_job_url, is_valid_url
from services.builder import DOCX_BUILDERS, build_cv_pdf, build_analysis_pdf, TEMPLATES_META
from services.session import (
    save_history, save_guest_analysis, save_cv_copy,
    save_feedback, get_global_stats, get_public_reviews,
    consume_credit, PLAN_LIMITS,
)

router = APIRouter()

# ─── In-memory result cache ────────────────────────────────────────────────────
_result_cache: dict = {}
_CACHE_TTL = 3600


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
    user = getattr(request.state, "user", None)
    stats = get_global_stats()
    reviews = get_public_reviews()
    show_auth = request.query_params.get("show_auth") == "1"
    return templates.TemplateResponse(request, "index.html", {
        "user": user,
        "stats": stats,
        "reviews": reviews,
        "show_auth_modal": show_auth,
    })


@router.get("/analyze")
async def analyze_get():
    return RedirectResponse(url="/", status_code=301)


@router.post("/analyze", response_class=HTMLResponse)
async def analyze(
    request: Request,
    cv_file: Optional[UploadFile] = File(None),
    cv_text_raw: str = Form(""),
    job_input: str = Form(""),
    max_pages: int = Form(2),
    font_size: float = Form(11.0),
    font_family: str = Form("Calibri"),
    career_change: Optional[str] = Form(None),
    cv_only: Optional[str] = Form(None),
    output_lang: str = Form("es"),
    save_cv_copy_toggle: Optional[str] = Form(None),
):
    user = getattr(request.state, "user", None)
    settings = get_settings()
    career_change_bool = career_change is not None and career_change.lower() not in ("false", "0", "")
    cv_only_bool = cv_only is not None and cv_only.lower() not in ("false", "0", "")
    save_cv_copy_bool = save_cv_copy_toggle is not None and save_cv_copy_toggle.lower() not in ("false", "0", "")

    def _err(msg, cv_text_raw_val=""):
        return templates.TemplateResponse(request, "index.html", {
            "user": user,
            "error": msg,
            "cv_text_raw": cv_text_raw_val,
            "stats": get_global_stats(),
            "reviews": get_public_reviews(),
        })

    if not settings.anthropic_api_key:
        return _err("No se encontró ANTHROPIC_API_KEY.")

    # ── Guest mode check ───────────────────────────────────────────────────────
    if not user:
        guest_used = request.cookies.get("guest_used", "")
        if guest_used == "1":
            return _err("Ya usaste tu análisis gratuito. Crea una cuenta para continuar.")

    # ── Credits check (logged-in users) ───────────────────────────────────────
    if user and user.get("plan") != "admin":
        if user.get("credits_remaining", 0) <= 0:
            return _err(
                f"Alcanzaste el límite de análisis este mes ({user['credits_limit']} para tu plan). "
                "Apoya en Ko-fi para acceder al plan Pro."
            )

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
                return _err("Formato no soportado. Sube un PDF o DOCX.")
        except Exception as e:
            return _err(f"Error al leer el archivo: {e}")
    elif cv_text_raw.strip():
        cv_text = cv_text_raw.strip()

    if not cv_text:
        return _err("Sube un CV o pega el texto directamente.")

    # ── Extract job text ───────────────────────────────────────────────────────
    job_text = ""
    job_input = job_input.strip()
    if is_valid_url(job_input):
        try:
            job_text = scrape_job_url(job_input)
        except ValueError as e:
            return _err(str(e), cv_text_raw)
    elif job_input:
        job_text = job_input

    if not job_text and not cv_only_bool:
        cv_only_bool = True

    # ── Run Claude ─────────────────────────────────────────────────────────────
    try:
        cv_data = optimize_cv(
            cv_text=cv_text,
            job_text=job_text,
            max_pages=max_pages,
            font_size=font_size,
            api_key=settings.anthropic_api_key,
            career_change=career_change_bool,
            cv_only=cv_only_bool,
            output_lang=output_lang,
        )
    except Exception as e:
        return _err(f"Error al analizar con Claude: {e}")

    # Store font prefs for download
    cv_data["_font_family"] = font_family
    cv_data["_font_size"] = font_size

    result_id = _store_result(cv_data)
    score = cv_data.get("score_match", 0)
    ats_ok = cv_data.get("ats_compatible", True)

    # ── Save history ──────────────────────────────────────────────────────────
    history_id = None
    if user:
        history_id = save_history(
            user["id"],
            cv_data.get("titulo_profesional", ""),
            score,
            ats_ok,
        )
        # Optionally save CV copy
        if save_cv_copy_bool and history_id:
            save_cv_copy(user["id"], history_id, cv_text, cv_data)
        if user.get("plan") != "admin":
            consume_credit(user["id"], user["credits_used"])
    else:
        save_guest_analysis()

    # ── Build response ─────────────────────────────────────────────────────────
    response = templates.TemplateResponse(request, "results.html", {
        "user": user,
        "cv": cv_data,
        "result_id": result_id,
        "templates_meta": TEMPLATES_META,
        "score": score,
        "ats_ok": ats_ok,
        "ats_detected": cv_data.get("ats_detectado", ""),
        "ats_reason": cv_data.get("ats_razon", ""),
        "score_explain": cv_data.get("score_explicacion", ""),
        "score_desglose": cv_data.get("score_desglose", {}),
        "keywords_ok": cv_data.get("keywords_integradas", []),
        "keywords_miss": cv_data.get("keywords_faltantes", []),
        "coaching": cv_data.get("coaching", []),
        "was_truncated": cv_data.get("_was_truncated", False),
        "model_used": cv_data.get("_model_used", "haiku"),
        "is_guest": not bool(user),
        "email_configured": get_settings().email_configured,
    })

    # Set guest cookie if needed
    if not user:
        response.set_cookie("guest_used", "1", max_age=86400, httponly=True, samesite="lax")

    return response


# ─── Download ─────────────────────────────────────────────────────────────────

@router.get("/download/{result_id}")
async def download(request: Request, result_id: str, fmt: str = "docx", template: str = "Clásico"):
    cv_data = _get_result(result_id)
    if not cv_data:
        raise HTTPException(status_code=404, detail="Resultado expirado. Vuelve a analizar tu CV.")

    # Guests: allow analysis_pdf + Clásico PDF only
    user = getattr(request.state, "user", None)
    guest_allowed = fmt == "analysis_pdf" or (fmt == "pdf" and template == "Clásico")
    if not user and not guest_allowed:
        return RedirectResponse(url="/?show_auth=1", status_code=303)

    nombre = cv_data.get("nombre", "CV").replace(" ", "_")
    fn = cv_data.get("_font_family", "Calibri")
    fs = cv_data.get("_font_size", 11.0)

    if fmt == "analysis_pdf":
        buf = build_analysis_pdf(cv_data)
        filename = f"Analisis_ATS_{nombre}.pdf"
        media_type = "application/pdf"
    elif fmt == "docx":
        builder = DOCX_BUILDERS.get(template, DOCX_BUILDERS["Clásico"])
        buf = builder(cv_data, fn=fn, fs=fs)
        filename = f"CV_{nombre}_{template}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fmt == "pdf":
        buf = build_cv_pdf(cv_data, template)
        filename = f"CV_{nombre}_{template}.pdf"
        media_type = "application/pdf"
    else:
        raise HTTPException(status_code=400, detail="Formato no soportado.")

    return StreamingResponse(
        buf,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Feedback endpoint ────────────────────────────────────────────────────────

@router.post("/feedback")
async def feedback(
    request: Request,
    rating: int = Form(...),
    comment: str = Form(""),
    job_title: str = Form(""),
    email: str = Form(""),
):
    user = getattr(request.state, "user", None)
    uid = user["id"] if user else None
    em  = user["email"] if user else email
    ok = save_feedback(uid, em, rating, comment, job_title)
    return JSONResponse({"ok": ok})
