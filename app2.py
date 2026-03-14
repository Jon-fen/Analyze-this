# CV Optimizer ATS — app2.py (v2, con usuarios y créditos)
# Requiere en Streamlit Secrets:
#   ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_KEY

import streamlit as st
import anthropic
import pdfplumber
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import io, json, re, time
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
from datetime import datetime, timezone

MAX_CV_CHARS = 12_000

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CV Optimizer ATS", page_icon="🎯", layout="centered")

st.markdown("""
<style>
.block-container { padding-top: 2rem; padding-bottom: 2rem; }
div[data-testid="stDownloadButton"] button {
    background-color: #1B6CA8; color: white;
    font-size: 1rem; padding: 0.6rem 1.5rem;
    border-radius: 6px; width: 100%; }
.coach-card { background: #F0F9FF; border-left: 4px solid #2E75B6;
              padding: 0.75rem 1rem; border-radius: 4px;
              margin-bottom: 0.5rem; font-size: 0.95rem; }
.score-explain { background: #F8F8F8; border-radius: 8px;
                 padding: 0.75rem 1rem; font-size: 0.9rem;
                 color: #444; margin-top: 0.5rem; }
.credit-badge { background: #E8F5E9; border: 1px solid #4CAF50;
                border-radius: 20px; padding: 0.2rem 0.8rem;
                font-size: 0.85rem; font-weight: 600; color: #2E7D32;
                display: inline-block; }
.credit-low   { background: #FFF3E0; border-color: #FF9800; color: #E65100; }
.credit-zero  { background: #FFEBEE; border-color: #F44336; color: #B71C1C; }
.warn-truncate { background: #FFF8E1; border-left: 3px solid #FFA000;
                 padding: 0.5rem 0.8rem; border-radius: 4px;
                 font-size: 0.85rem; color: #555; margin-bottom: 0.5rem; }
</style>
""", unsafe_allow_html=True)

# ─── Secrets ──────────────────────────────────────────────────────────────────
def get_secret(key: str, default=None):
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default

ANTHROPIC_KEY = get_secret("ANTHROPIC_API_KEY")
SUPABASE_URL  = get_secret("SUPABASE_URL")
SUPABASE_KEY  = get_secret("SUPABASE_KEY")

PLAN_CREDITS = {"free": 5, "pro": 50, "admin": 999999}

# ─── Supabase client ──────────────────────────────────────────────────────────
@st.cache_resource
def get_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = get_supabase()

# ─── Auth helpers ─────────────────────────────────────────────────────────────
def sign_up(email: str, password: str) -> tuple[bool, str]:
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        if res.user:
            # Create profile row with free credits
            supabase.table("profiles").insert({
                "id": res.user.id,
                "email": email,
                "plan": "free",
                "credits_used_this_month": 0,
                "credits_reset_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            return True, "✅ Cuenta creada. Revisa tu email para confirmar."
        return False, "Error al crear cuenta."
    except Exception as e:
        return False, str(e)

def sign_in(email: str, password: str) -> tuple[bool, str]:
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state["user"] = res.user
            st.session_state["session"] = res.session
            return True, ""
        return False, "Credenciales incorrectas."
    except Exception as e:
        return False, "Email o contraseña incorrectos."

def sign_out():
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    for key in ["user","session","cv_data","regen_docx","api_credits_error"]:
        st.session_state.pop(key, None)
    st.rerun()

def get_profile(user_id: str) -> dict:
    try:
        res = supabase.table("profiles").select("*").eq("id", user_id).single().execute()
        return res.data or {}
    except Exception:
        return {}

def get_credits_remaining(profile: dict) -> int:
    plan = profile.get("plan", "free")
    if plan == "admin":
        return 999999
    monthly_limit = PLAN_CREDITS.get(plan, 5)
    used = profile.get("credits_used_this_month", 0)
    # Auto-reset if new month
    reset_at_str = profile.get("credits_reset_at", "")
    try:
        reset_at = datetime.fromisoformat(reset_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if now.month != reset_at.month or now.year != reset_at.year:
            # Reset credits
            supabase.table("profiles").update({
                "credits_used_this_month": 0,
                "credits_reset_at": now.isoformat()
            }).eq("id", profile["id"]).execute()
            used = 0
    except Exception:
        pass
    return max(0, monthly_limit - used)

def consume_credit(user_id: str, current_used: int):
    supabase.table("profiles").update({
        "credits_used_this_month": current_used + 1
    }).eq("id", user_id).execute()

def save_history(user_id: str, job_title: str, score: int, ats_ok: bool):
    try:
        supabase.table("history").insert({
            "user_id": user_id,
            "job_title": job_title[:120],
            "score_match": score,
            "ats_compatible": ats_ok,
            "created_at": datetime.now(timezone.utc).isoformat()
        }).execute()
    except Exception:
        pass

def get_history(user_id: str) -> list:
    try:
        res = (supabase.table("history")
               .select("*")
               .eq("user_id", user_id)
               .order("created_at", desc=True)
               .limit(10)
               .execute())
        return res.data or []
    except Exception:
        return []

# ─── Auth wall ────────────────────────────────────────────────────────────────
def show_auth_page():
    st.title("🎯 CV Optimizer ATS")
    st.markdown("Adapta tu CV a cualquier oferta y supera los filtros automáticos.")
    st.markdown("---")

    tab_login, tab_signup = st.tabs(["🔑 Iniciar sesión", "📝 Crear cuenta"])

    with tab_login:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Contraseña", type="password", key="login_pw")
        if st.button("Entrar", use_container_width=True, key="btn_login"):
            if not email or not password:
                st.error("Completa email y contraseña.")
            else:
                with st.spinner("Verificando..."):
                    ok, msg = sign_in(email, password)
                if ok:
                    st.rerun()
                else:
                    st.error(msg)

    with tab_signup:
        st.markdown("Crea tu cuenta gratuita — incluye **5 optimizaciones por mes**.")
        email2 = st.text_input("Email", key="signup_email")
        password2 = st.text_input("Contraseña (mín. 8 caracteres)", type="password", key="signup_pw")
        password3 = st.text_input("Confirmar contraseña", type="password", key="signup_pw2")
        if st.button("Crear cuenta", use_container_width=True, key="btn_signup"):
            if not email2 or not password2:
                st.error("Completa todos los campos.")
            elif password2 != password3:
                st.error("Las contraseñas no coinciden.")
            elif len(password2) < 8:
                st.error("La contraseña debe tener al menos 8 caracteres.")
            else:
                with st.spinner("Creando cuenta..."):
                    ok, msg = sign_up(email2, password2)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    st.markdown("---")
    st.markdown("**Planes disponibles:**")
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.markdown("**🆓 Free**\n5 optimizaciones/mes\nCV descargable\nAnálisis ATS + coaching")
    with c2:
        with st.container(border=True):
            st.markdown("**⭐ Pro**\n50 optimizaciones/mes\nTodo lo de Free\nHistorial completo")
    with c3:
        with st.container(border=True):
            st.markdown("**🏢 Admin**\nUso ilimitado\nPanel de gestión\nVista de todos los usuarios")

    if not SUPABASE_URL or not SUPABASE_KEY:
        st.warning("⚠️ Supabase no configurado. Agrega SUPABASE_URL y SUPABASE_KEY en Secrets.")

# ─── Extraction helpers ────────────────────────────────────────────────────────
def is_valid_url(url: str) -> bool:
    return bool(re.match(r'^https?://', url.strip()))

def scrape_job_url(url: str) -> str:
    headers = {"User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise ValueError("El sitio tardó demasiado. Pega el texto manualmente.")
    except requests.exceptions.HTTPError as e:
        raise ValueError(f"No se pudo acceder ({e.response.status_code}).")
    except Exception:
        raise ValueError("No se pudo acceder al link.")

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script","style","nav","footer","header","aside","form","noscript","iframe"]):
        tag.decompose()
    text = ""
    for sel in [
        {"class": lambda c: c and any(k in " ".join(c).lower() for k in
            ["job-description","description","vacancy","posting","details","content"])},
        {"id": lambda i: i and any(k in i.lower() for k in ["job-description","description","details"])},
    ]:
        block = soup.find(attrs=sel)
        if block:
            text = block.get_text(separator="\n", strip=True)
            if len(text) > 200:
                break
    if not text or len(text) < 200:
        text = soup.get_text(separator="\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)[:8000]

def extract_pdf(file) -> str:
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    return text.strip()

def extract_docx(file) -> str:
    doc = DocxDocument(file)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

# ─── Claude optimization ──────────────────────────────────────────────────────
def optimize_cv(cv_text: str, job_text: str, max_pages: int, font_size) -> dict:
    api_key = st.session_state.get("user_api_key") or ANTHROPIC_KEY
    was_truncated = len(cv_text) > MAX_CV_CHARS
    cv_text = cv_text[:MAX_CV_CHARS]

    words_per_page = {9: 700, 10: 600, 10.5: 560, 11: 520, 12: 460}
    max_words = words_per_page.get(float(font_size), 580) * max_pages

    prompt = f"""Eres un experto coach de carrera y especialista en optimización de CVs para sistemas ATS.

INSTRUCCIONES:
1. Selecciona SOLO el contenido más relevante para esta oferta — NO inventes nada
2. Integra las palabras clave exactas de la oferta de forma natural
3. Reescribe logros con verbos de acción + impacto medible
4. Respeta el límite de {max_pages} página(s) ≈ {max_words} palabras
5. Evalúa compatibilidad ATS: sin tablas ni columnas que confundan parsers

CV ORIGINAL:
{cv_text}

OFERTA DE TRABAJO:
{job_text}

Responde ÚNICAMENTE con JSON válido, sin backticks:
{{
  "nombre": "nombre completo",
  "titulo_profesional": "título adaptado al puesto",
  "email": "email o vacío",
  "telefono": "teléfono o vacío",
  "linkedin": "URL o vacío",
  "ubicacion": "ciudad, país",
  "resumen_profesional": "3-4 oraciones con keywords ATS.",
  "experiencia": [{{
    "empresa": "nombre",
    "cargo": "cargo",
    "periodo": "mes/año - mes/año",
    "logros": ["Logro cuantificado con keyword ATS"]
  }}],
  "educacion": [{{"institucion":"","titulo":"","periodo":"","detalle":""}}],
  "habilidades_tecnicas": ["skill relevante"],
  "habilidades_blandas": ["máx 4"],
  "idiomas": ["Español - Nativo"],
  "certificaciones": ["solo si existen"],
  "ats_compatible": true,
  "ats_razon": "Una frase sobre compatibilidad ATS",
  "score_match": 82,
  "score_desglose": {{"keywords":88,"experiencia":80,"educacion":75,"habilidades":85}},
  "score_explicacion": "2-3 oraciones sobre el score.",
  "keywords_integradas": ["kw1"],
  "keywords_faltantes": ["kw ausente"],
  "coaching": [
    {{"categoria": "Tu fortaleza clave 💪", "tip": "Qué tiene el candidato valioso y cómo destacarlo."}},
    {{"categoria": "Brecha crítica 🎯", "tip": "Skill que falta y cómo cerrarla con curso/cert específica."}},
    {{"categoria": "Quick win de hoy ⚡", "tip": "Acción concreta en menos de 1 hora para mejorar candidatura."}},
    {{"categoria": "LinkedIn / Marca personal 🔗", "tip": "Qué cambiar en LinkedIn para este rol."}},
    {{"categoria": "Antes de la entrevista 📋", "tip": "Qué investigar y qué narrativa preparar."}}
  ]
}}"""

    client = anthropic.Anthropic(api_key=api_key)
    for attempt in range(2):
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=5000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        try:
            result = json.loads(raw)
            result["_was_truncated"] = was_truncated
            return result
        except json.JSONDecodeError:
            if attempt == 0:
                time.sleep(1)
                continue
            raise

# ─── DOCX helpers ─────────────────────────────────────────────────────────────
def add_section_header(doc, title, color_rgb, fn, body_size, border_color, prefix=""):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(body_size)
    p.paragraph_format.space_after = Pt(body_size * 0.3)
    run = p.add_run(f"{prefix}{title}")
    run.bold = True
    run.font.name = fn
    run.font.size = Pt(body_size + 1)
    run.font.color.rgb = RGBColor(*color_rgb)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    pPr.append(pBdr)
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), border_color)
    pBdr.append(bottom)

def R(run, fn, fs, bold=False, italic=False, color=None):
    run.font.name = fn
    run.font.size = Pt(float(fs))
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)
    return run

def build_classic(cv, fn, fs):
    fs = float(fs)
    doc = DocxDocument()
    s = doc.sections[0]
    s.left_margin = s.right_margin = Inches(1.0)
    s.top_margin = Inches(0.8)
    s.bottom_margin = Inches(0.8)
    DARK=(0x1A,0x1A,0x2E); BLUE=(0x2E,0x75,0xB6); GRAY=(0x66,0x66,0x66)
    def hdr(t): add_section_header(doc, t, BLUE, fn, fs, "2E75B6")
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    R(p.add_run(cv.get("nombre","")), fn, fs+9, bold=True, color=DARK)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    R(p.add_run(cv.get("titulo_profesional","")), fn, fs+2, bold=True, color=BLUE)
    parts=[x for x in [cv.get("email"),cv.get("telefono"),cv.get("ubicacion"),cv.get("linkedin")] if x]
    if parts:
        p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        R(p.add_run("  |  ".join(parts)), fn, fs-1, color=GRAY)
    if cv.get("resumen_profesional"):
        hdr("RESUMEN PROFESIONAL")
        R(doc.add_paragraph().add_run(cv["resumen_profesional"]), fn, fs)
    if cv.get("experiencia"):
        hdr("EXPERIENCIA PROFESIONAL")
        for exp in cv["experiencia"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.6)
            R(p.add_run(exp.get("cargo","")), fn, fs, bold=True)
            p2=doc.add_paragraph()
            R(p2.add_run(f"{exp.get('empresa','')}   |   {exp.get('periodo','')}"), fn, fs-1, italic=True, color=GRAY)
            for logro in exp.get("logros",[]):
                pb=doc.add_paragraph(style="List Bullet")
                pb.paragraph_format.left_indent=Inches(0.2); pb.paragraph_format.space_after=Pt(2)
                R(pb.add_run(logro), fn, fs)
    if cv.get("educacion"):
        hdr("EDUCACIÓN")
        for edu in cv["educacion"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.5)
            R(p.add_run(edu.get("titulo","")), fn, fs, bold=True)
            p2=doc.add_paragraph()
            R(p2.add_run(f"{edu.get('institucion','')}   |   {edu.get('periodo','')}"), fn, fs-1, italic=True, color=GRAY)
            if edu.get("detalle"): R(doc.add_paragraph().add_run(edu["detalle"]), fn, fs-1)
    for label, key, header in [
        (None,"habilidades_tecnicas","HABILIDADES TÉCNICAS"),
        (None,"habilidades_blandas","COMPETENCIAS"),
    ]:
        if cv.get(key):
            hdr(header)
            R(doc.add_paragraph().add_run("  •  ".join(cv[key])), fn, fs)
    if cv.get("idiomas"):
        hdr("IDIOMAS"); R(doc.add_paragraph().add_run("  |  ".join(cv["idiomas"])), fn, fs)
    certs=[c for c in cv.get("certificaciones",[]) if c]
    if certs:
        hdr("CERTIFICACIONES")
        for cert in certs: R(doc.add_paragraph().add_run(f"• {cert}"), fn, fs)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0); return buf

def build_modern(cv, fn, fs):
    fs = float(fs)
    doc = DocxDocument()
    s = doc.sections[0]
    s.left_margin = s.right_margin = Inches(0.75)
    s.top_margin = Inches(0.6)
    s.bottom_margin = Inches(0.8)
    NAVY=(0x1B,0x4F,0x72); TEAL=(0x17,0x8A,0xCA); GRAY=(0x77,0x77,0x77)
    def hdr(t): add_section_header(doc, t, NAVY, fn, fs, "17A8CA", prefix="◆  ")
    R(doc.add_paragraph().add_run(cv.get("nombre","").upper()), fn, fs+11, bold=True, color=NAVY)
    R(doc.add_paragraph().add_run(cv.get("titulo_profesional","")), fn, fs+2, bold=True, color=TEAL)
    parts=[]
    for icon,key in [("✉","email"),("✆","telefono"),("⌖","ubicacion"),("in","linkedin")]:
        if cv.get(key): parts.append(f"{icon} {cv[key]}")
    if parts: R(doc.add_paragraph().add_run("   |   ".join(parts)), fn, fs-1, color=GRAY)
    p_div=doc.add_paragraph(); p_div.paragraph_format.space_after=Pt(8)
    pPr=p_div._p.get_or_add_pPr(); pBdr=OxmlElement('w:pBdr'); pPr.append(pBdr)
    btm=OxmlElement('w:bottom')
    for a,v in [('w:val','single'),('w:sz','16'),('w:space','1'),('w:color','1B4F72')]: btm.set(qn(a),v)
    pBdr.append(btm)
    if cv.get("resumen_profesional"):
        hdr("PERFIL PROFESIONAL")
        p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15)
        R(p.add_run(cv["resumen_profesional"]), fn, fs)
    if cv.get("experiencia"):
        hdr("EXPERIENCIA")
        for exp in cv["experiencia"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.7); p.paragraph_format.left_indent=Inches(0.15)
            R(p.add_run(exp.get("cargo","")), fn, fs, bold=True, color=NAVY)
            R(p.add_run("  —  "), fn, fs)
            R(p.add_run(exp.get("empresa","")), fn, fs)
            p2=doc.add_paragraph(); p2.paragraph_format.left_indent=Inches(0.15)
            R(p2.add_run(exp.get("periodo","")), fn, fs-1, italic=True, color=TEAL)
            for logro in exp.get("logros",[]):
                pb=doc.add_paragraph(); pb.paragraph_format.left_indent=Inches(0.35); pb.paragraph_format.space_after=Pt(2)
                R(pb.add_run(f"▸  {logro}"), fn, fs)
    if cv.get("educacion"):
        hdr("EDUCACIÓN")
        for edu in cv["educacion"]:
            p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15); p.paragraph_format.space_before=Pt(fs*0.5)
            R(p.add_run(edu.get("titulo","")), fn, fs, bold=True, color=NAVY)
            R(p.add_run(f"   |   {edu.get('institucion','')}   |   {edu.get('periodo','')}"), fn, fs-1)
            if edu.get("detalle"):
                p2=doc.add_paragraph(); p2.paragraph_format.left_indent=Inches(0.15)
                R(p2.add_run(edu["detalle"]), fn, fs-1)
    if cv.get("habilidades_tecnicas") or cv.get("habilidades_blandas"):
        hdr("HABILIDADES")
        for label,key in [("Técnicas: ","habilidades_tecnicas"),("Competencias: ","habilidades_blandas")]:
            if cv.get(key):
                p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15)
                R(p.add_run(label), fn, fs, bold=True); R(p.add_run("  •  ".join(cv[key])), fn, fs)
    if cv.get("idiomas"):
        hdr("IDIOMAS")
        p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15)
        R(p.add_run("  |  ".join(cv["idiomas"])), fn, fs)
    certs=[c for c in cv.get("certificaciones",[]) if c]
    if certs:
        hdr("CERTIFICACIONES")
        for cert in certs:
            p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15)
            R(p.add_run(f"▸  {cert}"), fn, fs)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0); return buf

# ─── Results display ──────────────────────────────────────────────────────────
def show_results(cv_data, template, fn, fs, max_pages):
    st.markdown("---")
    st.subheader("📊 Análisis de Compatibilidad")
    if cv_data.get("_was_truncated"):
        st.markdown('<div class="warn-truncate">⚠️ CV muy extenso — se analizaron los primeros 12.000 caracteres. Toda la info relevante fue capturada.</div>', unsafe_allow_html=True)
    ats_ok  = cv_data.get("ats_compatible", True)
    ats_msg = cv_data.get("ats_razon", "")
    score   = cv_data.get("score_match", 0)
    sc_col  = "🟢" if score >= 75 else "🟡" if score >= 55 else "🔴"
    bc, sc = st.columns([1,2])
    with bc:
        if ats_ok: st.success("✅ ATS Compatible")
        else: st.error("❌ No ATS Compatible")
        if ats_msg: st.caption(ats_msg)
    with sc:
        st.metric(f"{sc_col} Match con la oferta (estimado por IA)", f"{score}%")
        explain = cv_data.get("score_explicacion","")
        if explain: st.markdown(f'<div class="score-explain">{explain}</div>', unsafe_allow_html=True)
    desglose = cv_data.get("score_desglose",{})
    if desglose:
        with st.expander("📈 Ver desglose"):
            d1,d2,d3,d4=st.columns(4)
            d1.metric("Keywords",    f"{desglose.get('keywords','-')}%")
            d2.metric("Experiencia", f"{desglose.get('experiencia','-')}%")
            d3.metric("Educación",   f"{desglose.get('educacion','-')}%")
            d4.metric("Habilidades", f"{desglose.get('habilidades','-')}%")
    st.markdown("---")
    k1,k2=st.columns(2)
    with k1:
        kw_ok=cv_data.get("keywords_integradas",[])
        if kw_ok: st.success(f"✅ **Keywords integradas ({len(kw_ok)}):**\n"+", ".join(kw_ok))
    with k2:
        kw_miss=cv_data.get("keywords_faltantes",[])
        if kw_miss: st.warning(f"⚠️ **Keywords ausentes ({len(kw_miss)}):**\n"+", ".join(kw_miss))
    coaching=cv_data.get("coaching",[])
    if coaching:
        st.markdown("---")
        st.subheader("🎯 Tu Plan de Acción")
        st.markdown("Recomendaciones personalizadas para **esta** postulación:")
        for tip in coaching:
            st.markdown(f'<div class="coach-card"><strong>{tip.get("categoria","")}</strong><br>{tip.get("tip","")}</div>', unsafe_allow_html=True)
    st.markdown("---")
    with st.spinner(f"Generando DOCX — {template} · {fn} {fs}pt · {max_pages}p..."):
        try:
            buf = build_classic(cv_data,fn,fs) if template=="Clásico" else build_modern(cv_data,fn,fs)
        except Exception as e:
            st.error(f"Error generando el documento: {e}"); return
    nombre = cv_data.get("nombre","cv").replace(" ","_")
    st.success("✅ ¡Tu CV optimizado está listo!")
    st.download_button(
        label=f"⬇️  Descargar CV — {template} · {fn} {fs}pt  (.docx)",
        data=buf,
        file_name=f"CV_ATS_{nombre}_{template}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# ─── Admin panel ──────────────────────────────────────────────────────────────
def show_admin_panel():
    st.markdown("---")
    with st.expander("🛠️ Panel Admin"):
        st.markdown("**Usuarios recientes:**")
        try:
            res = supabase.table("profiles").select("email,plan,credits_used_this_month").order("created_at", desc=True).limit(20).execute()
            if res.data:
                for u in res.data:
                    plan = u.get("plan","free")
                    used = u.get("credits_used_this_month",0)
                    limit = PLAN_CREDITS.get(plan, 5)
                    st.markdown(f"- **{u.get('email','')}** · {plan} · {used}/{limit if plan != 'admin' else '∞'} créditos usados")
            else:
                st.info("No hay usuarios todavía.")
        except Exception as e:
            st.error(f"Error cargando usuarios: {e}")

# ─── Main app (authenticated) ─────────────────────────────────────────────────
def show_main_app(user, profile):
    plan = profile.get("plan","free")
    credits_left = get_credits_remaining(profile)
    credits_used = profile.get("credits_used_this_month", 0)
    monthly_limit = PLAN_CREDITS.get(plan, 5)

    # ── Sidebar ────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("👤 Mi cuenta")

        # Credit badge
        badge_class = "credit-badge"
        if credits_left == 0:
            badge_class = "credit-badge credit-zero"
        elif credits_left <= 2:
            badge_class = "credit-badge credit-low"

        credit_display = "∞" if plan == "admin" else f"{credits_left}"
        credit_label = "∞ créditos" if plan == "admin" else f"{credits_left} crédito{'s' if credits_left != 1 else ''} restante{'s' if credits_left != 1 else ''}"
        st.markdown(f'<span class="{badge_class}">{plan.upper()} · {credit_label}</span>', unsafe_allow_html=True)

        if plan != "admin":
            st.progress(min(credits_used / monthly_limit, 1.0))
            st.caption(f"{credits_used} / {monthly_limit} usados este mes")

        if credits_left == 0 and plan != "admin":
            st.warning("Sin créditos este mes. Contacta al admin para subir a Pro.")

        # Fallback API key if service has no credits
        if st.session_state.get("api_credits_error"):
            st.warning("Servicio sin saldo. Usa tu propia API Key:")
            user_key = st.text_input("🔑 Tu API Key", type="password")
            if user_key:
                st.session_state["user_api_key"] = user_key

        st.markdown("---")
        st.markdown("**📐 Formato del CV**")
        max_pages = st.slider("Páginas máximas", 1, 3, 2)
        font_family = st.selectbox("Tipografía",
            ["Calibri","Arial","Georgia","Times New Roman","Trebuchet MS"], index=0,
            help="Calibri y Arial son las más amigables con ATS.")
        font_size = st.select_slider("Tamaño de letra", options=[9,10,10.5,11,12], value=10)

        if st.session_state.get("cv_data"):
            st.markdown("---")
            st.info("✅ Análisis guardado. Cambia formato y regenera sin re-llamar a Claude.")
            if st.button("🔄 Regenerar DOCX", use_container_width=True):
                st.session_state["regen_docx"] = True

        st.markdown("---")
        st.markdown("**¿Cómo funciona?**")
        st.markdown("1. Sube tu CV (PDF o DOCX)")
        st.markdown("2. Pega o linkea la oferta")
        st.markdown("3. Configura formato y template")
        st.markdown("4. Descarga tu CV optimizado")
        st.markdown("---")
        if st.button("🚪 Cerrar sesión", use_container_width=True):
            sign_out()
        st.caption("Powered by Claude AI · Anthropic")

    # ── Header ─────────────────────────────────────────────────────────────
    st.title("🎯 CV Optimizer ATS")
    st.markdown(f"Hola, **{profile.get('email','').split('@')[0]}** 👋  Adapta tu CV y supera los filtros automáticos.")

    # ── Admin panel ────────────────────────────────────────────────────────
    if plan == "admin":
        show_admin_panel()

    # ── Historial ──────────────────────────────────────────────────────────
    history = get_history(user.id)
    if history:
        with st.expander(f"📜 Historial de optimizaciones ({len(history)})"):
            for h in history:
                created = h.get("created_at","")[:10]
                score = h.get("score_match",0)
                ats = "✅" if h.get("ats_compatible") else "❌"
                title = h.get("job_title","—")
                sc_col = "🟢" if score >= 75 else "🟡" if score >= 55 else "🔴"
                st.markdown(f"- {created} · **{title}** · {ats} ATS · {sc_col} {score}%")

    # ── Inputs ─────────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📄 Tu CV")
        cv_file = st.file_uploader("Sube tu CV", type=["pdf","docx"], label_visibility="collapsed")
        cv_text_manual = st.text_area("O pega el texto aquí", height=220,
            placeholder="Pega el contenido de tu CV si no tienes archivo...")
    with col2:
        st.subheader("💼 Oferta Laboral")
        job_url = st.text_input("🔗 Link de la oferta",
            placeholder="https://www.linkedin.com/jobs/...")
        job_description = st.text_area("O pega el texto aquí", height=215,
            placeholder="Pega aquí el texto de la oferta...")

    # ── Template ───────────────────────────────────────────────────────────
    st.subheader("🎨 Template del CV")
    tc1,tc2=st.columns(2)
    with tc1:
        with st.container(border=True):
            st.markdown("**📋 Clásico**")
            st.markdown("Formato tradicional. Finanzas, legal, gobierno, roles senior.")
    with tc2:
        with st.container(border=True):
            st.markdown("**✨ Moderno**")
            st.markdown("Header destacado. Tech, startups, marketing.")
    template = st.radio("Template:", ["Clásico","Moderno"], horizontal=True, label_visibility="collapsed")
    st.markdown("---")

    # ── Regenerate only ────────────────────────────────────────────────────
    if st.session_state.get("regen_docx") and st.session_state.get("cv_data"):
        st.session_state["regen_docx"] = False
        show_results(st.session_state["cv_data"], template, font_family, font_size, max_pages)
        st.stop()

    # ── Main optimize button ───────────────────────────────────────────────
    if credits_left == 0 and plan != "admin" and not st.session_state.get("user_api_key"):
        st.button("🚀 Optimizar mi CV", use_container_width=True, disabled=True)
        st.error("Sin créditos este mes. Contacta al admin para subir a Pro.")
        st.stop()

    if st.button("🚀 Optimizar mi CV", use_container_width=True):
        # Resolve job text
        final_job = job_description.strip()
        if job_url.strip():
            if not is_valid_url(job_url):
                st.warning("⚠️ El link no parece válido.")
            else:
                with st.spinner("🔍 Leyendo la oferta desde el link..."):
                    try:
                        scraped = scrape_job_url(job_url.strip())
                        if scraped:
                            final_job = scraped
                            st.success(f"✅ Oferta leída ({len(scraped):,} caracteres)")
                        else:
                            st.warning("No se pudo extraer texto del link.")
                    except ValueError as e:
                        st.warning(str(e))

        if not final_job:
            st.error("⚠️ Pega la oferta o ingresa un link válido.")
            st.stop()

        # Extract CV
        cv_text = ""
        if cv_file:
            with st.spinner("📄 Extrayendo texto del archivo..."):
                try:
                    cv_text = extract_pdf(cv_file) if cv_file.name.lower().endswith(".pdf") \
                              else extract_docx(cv_file)
                except Exception as e:
                    st.error(f"Error al leer el archivo: {e}"); st.stop()

        if cv_text_manual.strip():
            cv_text = cv_text_manual.strip() if not cv_text else cv_text + "\n" + cv_text_manual.strip()

        if not cv_text:
            st.error("⚠️ Sube un CV o pega el texto."); st.stop()

        # Call Claude
        with st.spinner("🤖 Analizando compatibilidad, keywords y preparando coaching..."):
            try:
                cv_data = optimize_cv(cv_text, final_job, max_pages, font_size)
                st.session_state["cv_data"] = cv_data
                st.session_state["api_credits_error"] = False
                # Consume credit and save history
                consume_credit(user.id, credits_used)
                save_history(
                    user.id,
                    cv_data.get("titulo_profesional", "Rol desconocido"),
                    cv_data.get("score_match", 0),
                    cv_data.get("ats_compatible", True)
                )
            except json.JSONDecodeError:
                st.error("Error procesando respuesta. Intenta nuevamente."); st.stop()
            except anthropic.AuthenticationError:
                st.error("API Key inválida."); st.stop()
            except anthropic.RateLimitError:
                st.session_state["api_credits_error"] = True
                st.error("⚠️ Servicio sin saldo. Ingresa tu API Key en el panel lateral.")
                st.rerun()
            except Exception as e:
                st.error(f"Error inesperado: {e}"); st.stop()

        show_results(cv_data, template, font_family, font_size, max_pages)

    st.markdown("---")
    st.caption("CV Optimizer ATS · Powered by Claude AI · Anthropic")

# ─── Router ───────────────────────────────────────────────────────────────────
if not supabase:
    st.error("⚠️ Supabase no configurado. Agrega SUPABASE_URL y SUPABASE_KEY en Secrets de Streamlit.")
    st.info("Mientras tanto, usa **app.py** (versión sin usuarios).")
    st.stop()

user = st.session_state.get("user")

if not user:
    show_auth_page()
else:
    profile = get_profile(user.id)
    if not profile:
        st.error("Error cargando perfil. Intenta cerrar sesión y volver a entrar.")
        if st.button("Cerrar sesión"):
            sign_out()
    else:
        show_main_app(user, profile)


# Setup SQL está en setup.sql — ejecutar en Supabase SQL Editor antes de usar la app.
