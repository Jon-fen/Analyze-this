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
from streamlit_oauth import OAuth2Component

MAX_CV_CHARS = 40_000   # ~15 páginas densas
MAX_CV_CHARS_CAREER = 80_000  # Sin límite para cambio de carrera

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="CV Optimizer ATS", page_icon="🎯", layout="centered")

st.markdown("""
<style>
  /* ── Force light mode with landing palette ── */
  :root, [data-theme="dark"], [data-theme="light"] {
    --background-color: #F7F4EF !important;
    --secondary-background-color: #EDE9E1 !important;
    --text-color: #0F1117 !important;
  }
  .stApp { background-color: #F7F4EF !important; }
  section[data-testid="stSidebar"] {
    background-color: #EDE9E1 !important;
    border-right: 1px solid rgba(0,0,0,0.08) !important;
  }
  section[data-testid="stSidebar"] * { color: #0F1117 !important; }

  /* ── Main content ── */
  .block-container {
    padding-top: 2rem; padding-bottom: 2rem;
    max-width: 820px;
  }

  /* ── Inputs ── */
  .stTextInput input, .stTextArea textarea, .stSelectbox select {
    background: #FFFFFF !important;
    border: 1px solid rgba(0,0,0,0.12) !important;
    color: #0F1117 !important;
    border-radius: 8px !important;
  }

  /* ── Primary buttons ── */
  .stButton > button[kind="primary"], div[data-testid="stDownloadButton"] button {
    background-color: #1B4F8A !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    padding: 0.55rem 1.2rem !important;
  }
  .stButton > button[kind="primary"]:hover { background-color: #2E75B6 !important; }

  /* ── Secondary buttons ── */
  .stButton > button[kind="secondary"] {
    background: white !important;
    border: 1.5px solid #CCC !important;
    color: #0F1117 !important;
    border-radius: 8px !important;
  }

  /* ── Download button full width ── */
  div[data-testid="stDownloadButton"] button {
    font-size: 0.95rem !important;
    padding: 0.6rem 1.5rem !important;
    width: 100% !important;
    border-radius: 8px !important;
  }

  /* ── Cards & callouts ── */
  .coach-card {
    background: #EBF3FB; border-left: 4px solid #1B4F8A;
    padding: 0.75rem 1rem; border-radius: 6px;
    margin-bottom: 0.5rem; font-size: 0.95rem; color: #0F1117;
  }
  .score-explain {
    background: #F0EDE8; border-radius: 8px;
    padding: 0.75rem 1rem; font-size: 0.9rem;
    color: #555; margin-top: 0.5rem;
  }
  .warn-truncate {
    background: #FFF8E1; border-left: 3px solid #C8973A;
    padding: 0.5rem 0.8rem; border-radius: 4px;
    font-size: 0.85rem; color: #555; margin-bottom: 0.5rem;
  }

  /* ── Credit badge ── */
  .credit-badge {
    background: #EBF3FB; border: 1px solid #1B4F8A;
    border-radius: 20px; padding: 0.2rem 0.8rem;
    font-size: 0.85rem; font-weight: 600; color: #1B4F8A;
    display: inline-block;
  }
  .credit-low  { background: #FFF3E0; border-color: #FF9800; color: #E65100; }
  .credit-zero { background: #FFEBEE; border-color: #F44336; color: #B71C1C; }

  /* ── Tabs ── */
  .stTabs [data-baseweb="tab-list"] { background: transparent !important; }
  .stTabs [data-baseweb="tab"] { color: #666 !important; }
  .stTabs [aria-selected="true"] { color: #1B4F8A !important; border-bottom-color: #1B4F8A !important; }

  /* ── Metrics ── */
  [data-testid="metric-container"] {
    background: #FFFFFF; border: 1px solid rgba(0,0,0,0.08);
    border-radius: 10px; padding: 0.8rem 1rem;
  }

  /* ── Hide Streamlit branding ── */
  #MainMenu, footer, header { visibility: hidden; }
  [data-testid="stToolbar"] { display: none; }
</style>
""", unsafe_allow_html=True)

# ─── Secrets ──────────────────────────────────────────────────────────────────
def get_secret(key: str, default=None):
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return default

ANTHROPIC_KEY     = get_secret("ANTHROPIC_API_KEY")
SUPABASE_URL      = get_secret("SUPABASE_URL")
SUPABASE_KEY      = get_secret("SUPABASE_KEY")
GOOGLE_CLIENT_ID  = get_secret("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = get_secret("GOOGLE_CLIENT_SECRET", "")

PLAN_CREDITS = {"free": 10, "pro": 50, "admin": 999999}

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

def send_password_reset(email: str) -> tuple[bool, str]:
    try:
        supabase.auth.reset_password_email(
            email,
            options={"redirect_to": "https://analyze-this-v2.streamlit.app"}
        )
        return True, "✅ Te enviamos un email con el link para restablecer tu contraseña."
    except Exception as e:
        return False, f"No se pudo enviar el email: {e}"

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

# ─── Usage counter ────────────────────────────────────────────────────────────
def get_global_stats() -> dict:
    """Returns total CVs generated and registered users. Cached 5 min."""
    try:
        cvs = supabase.table("history").select("id", count="exact").execute()
        users = supabase.table("profiles").select("id", count="exact").execute()
        return {
            "cvs": cvs.count or 0,
            "users": users.count or 0,
        }
    except Exception:
        return {"cvs": 0, "users": 0}

# ─── Auth wall ────────────────────────────────────────────────────────────────
def show_auth_page():
    st.markdown("""
<div style="text-align:center;padding:1.5rem 0 0.5rem 0">
  <div style="font-size:2.5rem;margin-bottom:0.3rem">🎯</div>
  <h1 style="font-size:1.8rem;font-weight:800;margin:0">CV Optimizer ATS</h1>
  <p style="color:#666;font-size:1rem;margin:0.4rem 0 0 0">
    Sube tu CV completo. Pega la oferta. Descarga el CV listo para enviar.<br>
    <span style="font-size:0.85rem;color:#999">Tu experiencia, optimizada para cada oportunidad.</span>
  </p>
</div>
""", unsafe_allow_html=True)

    # ── Google OAuth button via streamlit-oauth ───────────────────────────
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        oauth2 = OAuth2Component(
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            authorize_endpoint=GOOGLE_AUTH_URL,
            token_endpoint=GOOGLE_TOKEN_URL,
        )
        result = oauth2.authorize_button(
            name="Continuar con Google",
            icon="https://www.google.com/favicon.ico",
            redirect_uri="https://analyze-this-v2.streamlit.app/",
            scope=GOOGLE_SCOPE,
            key="google_oauth",
            extras_params={"prompt": "select_account", "access_type": "offline"},
            use_container_width=True,
        )
        if result and result.get("token"):
            with st.spinner("Iniciando sesión con Google..."):
                handle_google_token(result["token"])

        st.markdown("""<div style="text-align:center;color:#999;
            font-size:0.8rem;margin:0.3rem 0 0.5rem 0">— o usa tu email —</div>""",
            unsafe_allow_html=True)

    # Value prop — why register
    st.markdown("""
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:0.8rem;margin-bottom:1.2rem">
  <div style="background:#EBF3FB;border-radius:10px;padding:0.9rem;text-align:center">
    <div style="font-size:1.4rem">📄</div>
    <div style="font-size:0.8rem;font-weight:600;color:#1B4F8A;margin-top:0.3rem">10 análisis gratis</div>
    <div style="font-size:0.72rem;color:#666;margin-top:0.2rem">por mes, sin tarjeta</div>
  </div>
  <div style="background:#EBF3FB;border-radius:10px;padding:0.9rem;text-align:center">
    <div style="font-size:1.4rem">🎨</div>
    <div style="font-size:0.8rem;font-weight:600;color:#1B4F8A;margin-top:0.3rem">4 templates</div>
    <div style="font-size:0.72rem;color:#666;margin-top:0.2rem">listos para enviar</div>
  </div>
  <div style="background:#EBF3FB;border-radius:10px;padding:0.9rem;text-align:center">
    <div style="font-size:1.4rem">🎤</div>
    <div style="font-size:0.8rem;font-weight:600;color:#1B4F8A;margin-top:0.3rem">Coaching incluido</div>
    <div style="font-size:0.72rem;color:#666;margin-top:0.2rem">carta + entrevista</div>
  </div>
</div>
""", unsafe_allow_html=True)

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

        # Forgot password
        with st.expander("¿Olvidaste tu contraseña?"):
            reset_email = st.text_input("Email de tu cuenta", key="reset_email")
            if st.button("Enviar link de recuperación", key="btn_reset"):
                if not reset_email:
                    st.error("Ingresa tu email.")
                else:
                    with st.spinner("Enviando..."):
                        ok, msg = send_password_reset(reset_email)
                    if ok:
                        st.success(msg)
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
                    st.info("👆 Ahora inicia sesión en la pestaña **🔑 Iniciar sesión** con tu email y contraseña.")
                else:
                    st.error(msg)

    st.markdown("---")
    st.markdown("**Planes disponibles:**")
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.markdown("**🆓 Free**\n5 análisis/mes\nCV descargable\nAnálisis ATS + coaching")
    with c2:
        with st.container(border=True):
            st.markdown("**⭐ Pro**\n50 análisis/mes\nTodo lo de Free\nHistorial completo")
    with c3:
        with st.container(border=True):
            st.markdown("**🏢 Admin**\nUso ilimitado\nPanel de gestión\nVista de todos los usuarios")

    # Social proof counter
    stats = get_global_stats()
    if stats["cvs"] > 0:
        st.markdown("---")
        c1, c2 = st.columns(2)
        with c1:
            st.metric("📄 CVs optimizados", f"{stats['cvs']:,}")
        with c2:
            st.metric("👥 Usuarios registrados", f"{stats['users']:,}")

    st.markdown("---")
    st.markdown("""
<div style="text-align:center;padding:0.5rem">
  <a href="https://ko-fi.com/analyzethis" target="_blank"
     style="display:inline-block;background:#FFDD00;color:#000;font-weight:700;
     padding:0.5rem 1.2rem;border-radius:8px;text-decoration:none;font-size:0.9rem;">
    ☕ ¿Te fue útil? Apoya en Ko-fi
  </a>
  <p style="font-size:0.75rem;color:#999;margin-top:0.4rem">
    Ayuda a mantener el servicio gratuito para todos
  </p>
</div>""", unsafe_allow_html=True)

    if not SUPABASE_URL or not SUPABASE_KEY:
        st.warning("⚠️ Supabase no configurado. Agrega SUPABASE_URL y SUPABASE_KEY en Secrets.")

# ─── Google OAuth via streamlit-oauth ────────────────────────────────────────
GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE     = "openid email profile"

def handle_google_token(token: dict):
    """Takes Google token, signs in to Supabase with the id_token."""
    try:
        id_token = token.get("id_token", "")
        if not id_token:
            st.error("No se pudo obtener el token de Google.")
            return
        # Sign in to Supabase with Google id_token
        res = supabase.auth.sign_in_with_id_token({
            "provider": "google",
            "token": id_token,
        })
        if res and res.user:
            st.session_state["user"] = res.user
            st.session_state["session"] = res.session
            # Create profile if first time
            try:
                existing = get_profile(res.user.id)
                if not existing:
                    supabase.table("profiles").insert({
                        "id": res.user.id,
                        "email": res.user.email,
                        "plan": "free",
                        "credits_used_this_month": 0,
                        "credits_reset_at": datetime.now(timezone.utc).isoformat()
                    }).execute()
            except Exception:
                pass
            st.rerun()
        else:
            st.error("Error al iniciar sesión con Google.")
    except Exception as e:
        st.error(f"Error de autenticación: {e}")

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
def optimize_cv(cv_text: str, job_text: str, max_pages: int, font_size, career_change: bool = False) -> dict:
    api_key = st.session_state.get("user_api_key") or ANTHROPIC_KEY
    limit = MAX_CV_CHARS_CAREER if career_change else MAX_CV_CHARS
    was_truncated = len(cv_text) > limit
    cv_text = cv_text[:limit]

    words_per_page = {9: 700, 10: 600, 10.5: 560, 11: 520, 12: 460}
    max_words = words_per_page.get(float(font_size), 580) * max_pages

    prompt = f"""Eres un experto coach de carrera y especialista en optimización de CVs para sistemas ATS.

{"MODO CAMBIO DE CARRERA — incluye experiencia de TODOS los períodos y reenmarca habilidades transferibles hacia el nuevo rol." if career_change else "Selecciona la experiencia MÁS RECIENTE y relevante para esta oferta específica."}

INSTRUCCIONES:
1. NO inventes nada — solo reorganiza y reescribe lo que existe
2. Integra las palabras clave exactas de la oferta de forma natural
3. Reescribe logros con verbos de acción + impacto medible
4. Respeta el límite de {{max_pages}} página(s) ≈ {{max_words}} palabras
5. Detecta qué ATS probablemente usa la empresa según su nombre/industria:
   - Empresas grandes/corporativas → Workday, SAP SuccessFactors
   - Startups/tech latam → Greenhouse, Lever
   - Empresas chilenas → Buk, Rankmi, Talently
   - Retail/gobierno → sistemas propios básicos
   Adapta el formato y densidad de keywords según ese ATS inferido
6. Evalúa compatibilidad ATS: sin tablas ni columnas que confundan parsers

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
  "ats_detectado": "Nombre del ATS inferido para esta empresa (ej: Workday, Buk, Greenhouse)",
  "ats_razon": "Por qué se adaptó el CV para ese ATS específico",
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

    def call_model(model_id: str) -> dict:
        for attempt in range(2):
            msg = client.messages.create(
                model=model_id,
                max_tokens=5000,
                messages=[{"role": "user", "content": prompt}]
            )
            raw = msg.content[0].text.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise

    # Paso 1: Haiku hace el análisis inicial (costo ~$0.01-0.02)
    result = call_model("claude-haiku-4-5-20251001")
    result["_was_truncated"] = was_truncated
    result["_model_used"] = "haiku"

    # Paso 2: Si score < 60, Opus reanaliza con más profundidad (~$0.15-0.20)
    # Solo ocurre cuando el candidato realmente necesita optimización más inteligente
    if result.get("score_match", 100) < 60:
        result = call_model("claude-opus-4-5-20251101")
        result["_was_truncated"] = was_truncated
        result["_model_used"] = "opus"

    return result

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

# ─── Template definitions ────────────────────────────────────────────────────
TEMPLATES = {
    "Clásico": {
        "icon": "📋",
        "color": "#2E75B6",
        "ideal": "Finanzas · Legal · Gobierno · Roles senior",
        "desc": "Nombre centrado, secciones con línea azul, bullets ordenados. El formato más reconocido y esperado por reclutadores tradicionales.",
        "tags": ["#EBF3FB", "#2E75B6"],
    },
    "Moderno": {
        "icon": "✨",
        "color": "#178ACA",
        "ideal": "Tech · Startups · Marketing · Diseño",
        "desc": "Header con nombre en mayúsculas, secciones con rombos ◆ y flechas ▸. Diseño limpio que destaca sin sacrificar legibilidad ATS.",
        "tags": ["#E8F7FD", "#178ACA"],
    },
    "Ejecutivo": {
        "icon": "🏛️",
        "color": "#1B2A4A",
        "ideal": "Dirección general · C-level · Consultoría · Banca",
        "desc": "Nombre en mayúsculas con título en dorado, separador ancho, tipografía Georgia. Transmite autoridad y trayectoria desde la primera línea.",
        "tags": ["#EDEEF2", "#1B2A4A"],
    },
    "Minimalista": {
        "icon": "⬜",
        "color": "#444444",
        "ideal": "Cualquier sector · Máxima compatibilidad ATS",
        "desc": "Sin colores, sin elementos gráficos. El formato más seguro para sistemas ATS estrictos. Ideal si no sabes qué parser usa la empresa.",
        "tags": ["#F5F5F5", "#444444"],
    },
}

from docx.oxml.ns import qn as _qn
from docx.oxml import OxmlElement as _OxmlElement

def _section_border(p, border_color):
    pPr = p._p.get_or_add_pPr()
    pBdr = _OxmlElement('w:pBdr')
    pPr.append(pBdr)
    bottom = _OxmlElement('w:bottom')
    bottom.set(_qn('w:val'), 'single')
    bottom.set(_qn('w:sz'), '6')
    bottom.set(_qn('w:space'), '1')
    bottom.set(_qn('w:color'), border_color)
    pBdr.append(bottom)

def _hdr(doc, title, color_rgb, fn, fs, border_color, prefix=""):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(fs)
    p.paragraph_format.space_after = Pt(fs * 0.3)
    run = p.add_run(f"{prefix}{title}")
    run.bold = True; run.font.name = fn
    run.font.size = Pt(fs + 1)
    run.font.color.rgb = RGBColor(*color_rgb)
    _section_border(p, border_color)

def _R(run, fn, fs, bold=False, italic=False, color=None):
    run.font.name = fn; run.font.size = Pt(float(fs))
    run.bold = bold; run.italic = italic
    if color: run.font.color.rgb = RGBColor(*color)
    return run

def _exp_block(doc, cv, fn, fs, cargo_color, periodo_color, bullet_prefix, indent_cargo, indent_bullet):
    for exp in cv.get("experiencia", []):
        p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(fs * 0.6)
        p.paragraph_format.left_indent = Inches(indent_cargo)
        _R(p.add_run(exp.get("cargo", "")), fn, fs, bold=True, color=cargo_color)
        p2 = doc.add_paragraph(); p2.paragraph_format.left_indent = Inches(indent_cargo)
        _R(p2.add_run(f"{exp.get('empresa','')}   |   {exp.get('periodo','')}"), fn, fs-1, italic=True, color=periodo_color)
        for logro in exp.get("logros", []):
            pb = doc.add_paragraph(); pb.paragraph_format.left_indent = Inches(indent_bullet)
            pb.paragraph_format.space_after = Pt(2)
            _R(pb.add_run(f"{bullet_prefix}{logro}"), fn, fs)

def build_clasico(cv, fn, fs):
    fs = float(fs)
    doc = DocxDocument(); s = doc.sections[0]
    s.left_margin = s.right_margin = Inches(1.0)
    s.top_margin = Inches(0.8); s.bottom_margin = Inches(0.8)
    DARK=(0x1A,0x1A,0x2E); BLUE=(0x2E,0x75,0xB6); GRAY=(0x66,0x66,0x66)
    def hdr(t): _hdr(doc, t, BLUE, fn, fs, "2E75B6")
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    _R(p.add_run(cv.get("nombre","")), fn, fs+9, bold=True, color=DARK)
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    _R(p.add_run(cv.get("titulo_profesional","")), fn, fs+2, bold=True, color=BLUE)
    parts=[x for x in [cv.get("email"),cv.get("telefono"),cv.get("ubicacion"),cv.get("linkedin")] if x]
    if parts:
        p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        _R(p.add_run("  |  ".join(parts)), fn, fs-1, color=GRAY)
    if cv.get("resumen_profesional"):
        hdr("RESUMEN PROFESIONAL"); _R(doc.add_paragraph().add_run(cv["resumen_profesional"]), fn, fs)
    if cv.get("experiencia"):
        hdr("EXPERIENCIA PROFESIONAL")
        _exp_block(doc, cv, fn, fs, (0,0,0), GRAY, "• ", 0, 0.2)
    if cv.get("educacion"):
        hdr("EDUCACIÓN")
        for edu in cv["educacion"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.5)
            _R(p.add_run(edu.get("titulo","")), fn, fs, bold=True)
            _R(doc.add_paragraph().add_run(f"{edu.get('institucion','')}   |   {edu.get('periodo','')}"), fn, fs-1, italic=True, color=GRAY)
            if edu.get("detalle"): _R(doc.add_paragraph().add_run(edu["detalle"]), fn, fs-1)
    if cv.get("habilidades_tecnicas"):
        hdr("HABILIDADES TÉCNICAS"); _R(doc.add_paragraph().add_run("  •  ".join(cv["habilidades_tecnicas"])), fn, fs)
    if cv.get("habilidades_blandas"):
        hdr("COMPETENCIAS"); _R(doc.add_paragraph().add_run("  •  ".join(cv["habilidades_blandas"])), fn, fs)
    if cv.get("idiomas"):
        hdr("IDIOMAS"); _R(doc.add_paragraph().add_run("  |  ".join(cv["idiomas"])), fn, fs)
    certs=[c for c in cv.get("certificaciones",[]) if c]
    if certs:
        hdr("CERTIFICACIONES")
        for cert in certs: _R(doc.add_paragraph().add_run(f"• {cert}"), fn, fs)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0); return buf

def build_moderno(cv, fn, fs):
    fs = float(fs)
    doc = DocxDocument(); s = doc.sections[0]
    s.left_margin = s.right_margin = Inches(0.75)
    s.top_margin = Inches(0.6); s.bottom_margin = Inches(0.8)
    NAVY=(0x1B,0x4F,0x72); TEAL=(0x17,0x8A,0xCA); GRAY=(0x77,0x77,0x77)
    def hdr(t): _hdr(doc, t, NAVY, fn, fs, "17A8CA", prefix="◆  ")
    _R(doc.add_paragraph().add_run(cv.get("nombre","").upper()), fn, fs+11, bold=True, color=NAVY)
    _R(doc.add_paragraph().add_run(cv.get("titulo_profesional","")), fn, fs+2, bold=True, color=TEAL)
    parts=[]
    for icon,key in [("✉","email"),("✆","telefono"),("⌖","ubicacion"),("in","linkedin")]:
        if cv.get(key): parts.append(f"{icon} {cv[key]}")
    if parts: _R(doc.add_paragraph().add_run("   |   ".join(parts)), fn, fs-1, color=GRAY)
    p_div=doc.add_paragraph(); p_div.paragraph_format.space_after=Pt(8)
    pPr=p_div._p.get_or_add_pPr(); pBdr=_OxmlElement('w:pBdr'); pPr.append(pBdr)
    btm=_OxmlElement('w:bottom')
    for a,v in [('w:val','single'),('w:sz','16'),('w:space','1'),('w:color','1B4F72')]: btm.set(_qn(a),v)
    pBdr.append(btm)
    if cv.get("resumen_profesional"):
        hdr("PERFIL PROFESIONAL")
        p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15)
        _R(p.add_run(cv["resumen_profesional"]), fn, fs)
    if cv.get("experiencia"):
        hdr("EXPERIENCIA")
        for exp in cv["experiencia"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.7); p.paragraph_format.left_indent=Inches(0.15)
            _R(p.add_run(exp.get("cargo","")), fn, fs, bold=True, color=NAVY)
            _R(p.add_run("  —  "), fn, fs); _R(p.add_run(exp.get("empresa","")), fn, fs)
            p2=doc.add_paragraph(); p2.paragraph_format.left_indent=Inches(0.15)
            _R(p2.add_run(exp.get("periodo","")), fn, fs-1, italic=True, color=TEAL)
            for logro in exp.get("logros",[]):
                pb=doc.add_paragraph(); pb.paragraph_format.left_indent=Inches(0.35); pb.paragraph_format.space_after=Pt(2)
                _R(pb.add_run(f"▸  {logro}"), fn, fs)
    if cv.get("educacion"):
        hdr("EDUCACIÓN")
        for edu in cv["educacion"]:
            p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15); p.paragraph_format.space_before=Pt(fs*0.5)
            _R(p.add_run(edu.get("titulo","")), fn, fs, bold=True, color=NAVY)
            _R(p.add_run(f"   |   {edu.get('institucion','')}   |   {edu.get('periodo','')}"), fn, fs-1)
            if edu.get("detalle"):
                p2=doc.add_paragraph(); p2.paragraph_format.left_indent=Inches(0.15); _R(p2.add_run(edu["detalle"]), fn, fs-1)
    if cv.get("habilidades_tecnicas") or cv.get("habilidades_blandas"):
        hdr("HABILIDADES")
        for label,key in [("Técnicas: ","habilidades_tecnicas"),("Competencias: ","habilidades_blandas")]:
            if cv.get(key):
                p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15)
                _R(p.add_run(label), fn, fs, bold=True); _R(p.add_run("  •  ".join(cv[key])), fn, fs)
    if cv.get("idiomas"):
        hdr("IDIOMAS"); p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15)
        _R(p.add_run("  |  ".join(cv["idiomas"])), fn, fs)
    certs=[c for c in cv.get("certificaciones",[]) if c]
    if certs:
        hdr("CERTIFICACIONES")
        for cert in certs:
            p=doc.add_paragraph(); p.paragraph_format.left_indent=Inches(0.15); _R(p.add_run(f"▸  {cert}"), fn, fs)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0); return buf

def build_ejecutivo(cv, fn, fs):
    fs = float(fs)
    sfn = "Georgia" if fn in ["Calibri","Arial","Trebuchet MS"] else fn
    doc = DocxDocument(); s = doc.sections[0]
    s.left_margin = s.right_margin = Inches(1.0)
    s.top_margin = Inches(0.7); s.bottom_margin = Inches(0.8)
    NAVY=(0x1B,0x2A,0x4A); GOLD=(0x8B,0x6C,0x1E); GRAY=(0x55,0x55,0x55)
    def hdr(t): _hdr(doc, t, NAVY, sfn, fs, "1B2A4A")
    p=doc.add_paragraph(); _R(p.add_run(cv.get("nombre","").upper()), sfn, fs+10, bold=True, color=NAVY)
    p2=doc.add_paragraph(); _R(p2.add_run(cv.get("titulo_profesional","")), sfn, fs+1, italic=True, color=GOLD)
    parts=[x for x in [cv.get("email"),cv.get("telefono"),cv.get("ubicacion"),cv.get("linkedin")] if x]
    if parts: _R(doc.add_paragraph().add_run("  ·  ".join(parts)), fn, fs-1, color=GRAY)
    p_div=doc.add_paragraph(); p_div.paragraph_format.space_after=Pt(6)
    pPr=p_div._p.get_or_add_pPr(); pBdr=_OxmlElement('w:pBdr'); pPr.append(pBdr)
    btm=_OxmlElement('w:bottom')
    for a,v in [('w:val','single'),('w:sz','24'),('w:space','1'),('w:color','1B2A4A')]: btm.set(_qn(a),v)
    pBdr.append(btm)
    if cv.get("resumen_profesional"):
        hdr("PERFIL EJECUTIVO"); _R(doc.add_paragraph().add_run(cv["resumen_profesional"]), sfn, fs, italic=True)
    if cv.get("experiencia"):
        hdr("TRAYECTORIA PROFESIONAL")
        for exp in cv["experiencia"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.7)
            _R(p.add_run(f"■  {exp.get('cargo','')}"), sfn, fs, bold=True, color=NAVY)
            _R(p.add_run(f"  ·  {exp.get('empresa','')}"), sfn, fs)
            p2=doc.add_paragraph(); p2.paragraph_format.left_indent=Inches(0.25)
            _R(p2.add_run(exp.get("periodo","")), fn, fs-1, italic=True, color=GRAY)
            for logro in exp.get("logros",[]):
                pb=doc.add_paragraph(); pb.paragraph_format.left_indent=Inches(0.35); pb.paragraph_format.space_after=Pt(2)
                _R(pb.add_run(f"›  {logro}"), sfn, fs)
    if cv.get("educacion"):
        hdr("FORMACIÓN ACADÉMICA")
        for edu in cv["educacion"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.5)
            _R(p.add_run(edu.get("titulo","")), sfn, fs, bold=True, color=NAVY)
            _R(p.add_run(f"  —  {edu.get('institucion','')}  |  {edu.get('periodo','')}"), sfn, fs-1, color=GRAY)
    all_sk=cv.get("habilidades_tecnicas",[])+cv.get("habilidades_blandas",[])
    if all_sk:
        hdr("COMPETENCIAS"); _R(doc.add_paragraph().add_run("  ■  ".join(all_sk)), sfn, fs)
    if cv.get("idiomas"):
        hdr("IDIOMAS"); _R(doc.add_paragraph().add_run("  |  ".join(cv["idiomas"])), sfn, fs)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0); return buf

def build_minimalista(cv, fn, fs):
    fs = float(fs)
    doc = DocxDocument(); s = doc.sections[0]
    s.left_margin = s.right_margin = Inches(1.1)
    s.top_margin = Inches(0.9); s.bottom_margin = Inches(0.9)
    DARK=(0x22,0x22,0x22); MID=(0x44,0x44,0x44); LIGHT=(0x88,0x88,0x88)
    def hdr(t):
        p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*1.2); p.paragraph_format.space_after=Pt(fs*0.2)
        run=p.add_run(t.upper()); run.bold=True; run.font.name=fn; run.font.size=Pt(fs); run.font.color.rgb=RGBColor(*DARK)
        _section_border(p, "AAAAAA")
    _R(doc.add_paragraph().add_run(cv.get("nombre","")), fn, fs+6, bold=True, color=DARK)
    _R(doc.add_paragraph().add_run(cv.get("titulo_profesional","")), fn, fs+0.5, color=MID)
    parts=[x for x in [cv.get("email"),cv.get("telefono"),cv.get("ubicacion"),cv.get("linkedin")] if x]
    if parts: _R(doc.add_paragraph().add_run("  |  ".join(parts)), fn, fs-1, color=LIGHT)
    if cv.get("resumen_profesional"):
        hdr("Resumen"); _R(doc.add_paragraph().add_run(cv["resumen_profesional"]), fn, fs, color=MID)
    if cv.get("experiencia"):
        hdr("Experiencia")
        for exp in cv["experiencia"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.5)
            _R(p.add_run(exp.get("cargo","")), fn, fs, bold=True, color=DARK)
            _R(p.add_run(f"  —  {exp.get('empresa','')}"), fn, fs, color=MID)
            _R(doc.add_paragraph().add_run(exp.get("periodo","")), fn, fs-1, italic=True, color=LIGHT)
            for logro in exp.get("logros",[]):
                pb=doc.add_paragraph(); pb.paragraph_format.left_indent=Inches(0.2); pb.paragraph_format.space_after=Pt(2)
                _R(pb.add_run(f"- {logro}"), fn, fs, color=MID)
    if cv.get("educacion"):
        hdr("Educación")
        for edu in cv["educacion"]:
            p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(fs*0.4)
            _R(p.add_run(edu.get("titulo","")), fn, fs, bold=True, color=DARK)
            _R(p.add_run(f"  —  {edu.get('institucion','')}  ({edu.get('periodo','')}"), fn, fs-1, color=MID)
    all_sk=cv.get("habilidades_tecnicas",[])+cv.get("habilidades_blandas",[])
    if all_sk:
        hdr("Habilidades"); _R(doc.add_paragraph().add_run("  /  ".join(all_sk)), fn, fs, color=MID)
    if cv.get("idiomas"):
        hdr("Idiomas"); _R(doc.add_paragraph().add_run("  |  ".join(cv["idiomas"])), fn, fs, color=MID)
    buf=io.BytesIO(); doc.save(buf); buf.seek(0); return buf

BUILDERS = {
    "Clásico":    build_clasico,
    "Moderno":    build_moderno,
    "Ejecutivo":  build_ejecutivo,
    "Minimalista": build_minimalista,
}

# ─── Next-step tools (carta, entrevista, linkedin) ───────────────────────────
def _run_next_tool(tool: str, nombre: str, titulo: str, resumen: str, skills: str, fn: str, fs):
    api_key = st.session_state.get("user_api_key") or ANTHROPIC_KEY
    job_ctx = st.session_state.get("cv_data", {}).get("titulo_profesional", "este puesto")

    prompts = {
        "carta": f"""Escribe una carta de presentación para el puesto de {titulo}.
Empieza con una idea potente (NO empieces con 'Me postulo para...' ni 'Mi nombre es...').
Conecta la experiencia específica del candidato con las necesidades exactas del puesto.
Termina transmitiendo confianza y con un llamado a la acción natural.
Máximo 200 palabras. Tono profesional pero humano.

Perfil del candidato:
Nombre: {nombre}
Resumen: {resumen}
Habilidades clave: {skills}

Escribe solo la carta, sin títulos ni explicaciones adicionales.""",

        "entrevista": f"""Soy candidato al puesto de {titulo}.
Dame exactamente:
1. Las 8 preguntas más probables en la entrevista para este cargo
2. Para cada pregunta: una estructura de respuesta sólida usando mi experiencia real (método STAR cuando aplique)
3. Al final: 3 preguntas inteligentes que YO le haría al entrevistador para demostrar pensamiento estratégico

Mi perfil:
{resumen}
Habilidades: {skills}

Sé específico y práctico. Evita respuestas genéricas.""",

        "linkedin": f"""Reescribe estas 3 secciones de mi perfil LinkedIn para posicionarme en búsquedas de reclutadores para el puesto de {titulo}:

1. TÍTULO PROFESIONAL (máximo 220 caracteres, incluye keywords del sector)
2. SECCIÓN 'ACERCA DE' (máximo 2.600 caracteres, primera persona, comienza con gancho, termina con CTA)
3. DESCRIPCIÓN DE EXPERIENCIA más reciente (máximo 5 bullets con logros cuantificados)

Mi perfil actual:
{resumen}
Habilidades: {skills}

Haz que cada palabra tenga peso. Optimiza para el algoritmo de LinkedIn y para reclutadores humanos."""
    }

    labels = {
        "carta": "📝 Carta de Presentación",
        "entrevista": "🎤 Preparación de Entrevista",
        "linkedin": "💼 Optimización LinkedIn"
    }

    with st.spinner(f"Generando {labels[tool]}..."):
        try:
            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompts[tool]}]
            )
            result_text = msg.content[0].text.strip()

            st.markdown("---")
            st.subheader(labels[tool])
            st.markdown(result_text)

            # Offer download as txt
            st.download_button(
                label=f"⬇️ Descargar {labels[tool]} (.txt)",
                data=result_text.encode("utf-8"),
                file_name=f"{tool}_{nombre.replace(' ','_')}.txt",
                mime="text/plain",
                use_container_width=False
            )
        except Exception as e:
            st.error(f"Error generando {labels[tool]}: {e}")

# ─── Results display ──────────────────────────────────────────────────────────
def show_results(cv_data, template, fn, fs, max_pages):
    st.markdown("---")
    st.subheader("📊 Análisis de Compatibilidad")
    if cv_data.get("_was_truncated"):
        st.markdown('<div class="warn-truncate">ℹ️ Tu CV era muy extenso. Se analizaron hasta ~15 páginas de tu historial (las más recientes y relevantes). Si activaste el modo cambio de carrera, se procesó el documento completo.</div>', unsafe_allow_html=True)
    model_used = cv_data.get("_model_used", "haiku")
    model_label = "⚡ Haiku (rápido)" if model_used == "haiku" else "🧠 Opus (profundo — score bajo detectado)"
    st.caption(f"Modelo usado: {model_label}")
    ats_detected = cv_data.get("ats_detectado", "")
    ats_ok  = cv_data.get("ats_compatible", True)
    ats_msg = cv_data.get("ats_razon", "")
    score   = cv_data.get("score_match", 0)
    sc_col  = "🟢" if score >= 75 else "🟡" if score >= 55 else "🔴"
    bc, sc = st.columns([1,2])
    with bc:
        if ats_ok: st.success("✅ ATS Compatible")
        else: st.error("❌ No ATS Compatible")
        if ats_detected:
            st.caption(f"🎯 ATS detectado: **{ats_detected}**")
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
    st.subheader("⬇️ Descarga tu CV")
    st.markdown("**El análisis está listo — descarga en cualquier template sin coste adicional:**")
    nombre = cv_data.get("nombre","cv").replace(" ","_")
    dl1, dl2, dl3, dl4 = st.columns(4)
    for col, (tname, builder) in zip([dl1,dl2,dl3,dl4], BUILDERS.items()):
        with col:
            try:
                buf = builder(cv_data, fn, float(fs))
                st.download_button(
                    label=f"⬇️ {tname}",
                    data=buf,
                    file_name=f"CV_ATS_{nombre}_{tname}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"Error {tname}: {e}")
    st.success("✅ ¡Tu CV optimizado está listo!")
    st.caption(f"Tipografía: {fn} · {fs}pt · {max_pages} página(s)")

    # ── ¿Qué sigue? — herramientas complementarias ─────────────────────────
    st.markdown("---")
    st.subheader("🚀 ¿Qué sigue? Prepara el resto de tu postulación")
    st.markdown("Usa el mismo CV y oferta para generar estas herramientas en segundos:")

    nombre_cv  = cv_data.get("nombre", "")
    titulo_cv  = cv_data.get("titulo_profesional", "")
    resumen_cv = cv_data.get("resumen_profesional", "")
    skills_cv  = ", ".join(cv_data.get("habilidades_tecnicas", [])[:6])

    q1, q2, q3 = st.columns(3)

    with q1:
        with st.container(border=True):
            st.markdown("**📝 Carta de presentación**")
            st.caption("Menos de 200 palabras, comienza con una idea potente (no 'Me postulo para...')")
            if st.button("Generar carta", key="btn_carta", use_container_width=True):
                st.session_state["next_tool"] = "carta"
                st.rerun()

    with q2:
        with st.container(border=True):
            st.markdown("**🎤 Prep de entrevista**")
            st.caption("8 preguntas probables + estructura de respuesta basada en tu experiencia")
            if st.button("Preparar entrevista", key="btn_entrevista", use_container_width=True):
                st.session_state["next_tool"] = "entrevista"
                st.rerun()

    with q3:
        with st.container(border=True):
            st.markdown("**💼 Optimizar LinkedIn**")
            st.caption("Título, 'Acerca de' y experiencias reescritos para aparecer en búsquedas de reclutadores")
            if st.button("Optimizar LinkedIn", key="btn_linkedin", use_container_width=True):
                st.session_state["next_tool"] = "linkedin"
                st.rerun()

    # Execute selected tool
    next_tool = st.session_state.get("next_tool")
    if next_tool and cv_data:
        st.session_state.pop("next_tool", None)
        _run_next_tool(next_tool, nombre_cv, titulo_cv, resumen_cv, skills_cv, fn, fs)

# ─── Admin panel ──────────────────────────────────────────────────────────────
def show_admin_panel():
    st.markdown("---")
    with st.expander("🛠️ Panel Admin"):
        stats = get_global_stats()
        a1, a2 = st.columns(2)
        a1.metric("📄 CVs generados (total)", f"{stats['cvs']:,}")
        a2.metric("👥 Usuarios registrados", f"{stats['users']:,}")
        st.markdown("---")
        st.markdown("**Usuarios recientes:**")
        try:
            res = supabase.table("profiles").select("email,plan,credits_used_this_month").order("created_at", desc=True).limit(20).execute()
            if res.data:
                for u in res.data:
                    plan = u.get("plan","free")
                    used = u.get("credits_used_this_month",0)
                    limit = PLAN_CREDITS.get(plan, 5)
                    st.markdown(f"- **{u.get('email','')}** · {plan} · {used}/{limit if plan != 'admin' else '∞'} análisis usados")
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
        credit_label = "∞ análisis" if plan == "admin" else f"{credits_left} análisis restante{'s' if credits_left != 1 else ''}"
        st.markdown(f'<span class="{badge_class}">{plan.upper()} · {credit_label}</span>', unsafe_allow_html=True)

        if plan != "admin":
            st.progress(min(credits_used / monthly_limit, 1.0))
            st.caption(f"{credits_used} / {monthly_limit} análisis usados este mes")

        if credits_left == 0 and plan != "admin":
            st.warning("Sin análisis este mes. Contacta al admin para subir a Pro.")

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
    nombre_usuario = profile.get('email','').split('@')[0]
    st.markdown(f"""
<div style="padding:0.5rem 0 1rem 0">
  <h1 style="font-size:1.7rem;font-weight:800;margin:0">🎯 CV Optimizer ATS</h1>
  <p style="color:#666;margin:0.2rem 0 0 0">
    Hola, <strong>{nombre_usuario}</strong> 👋 — Sube tu CV, pega la oferta, descarga listo.
  </p>
</div>""", unsafe_allow_html=True)

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
        career_change = st.toggle(
            "🔄 Cambio de carrera o industria",
            key="career_change_mode",
            help="Activa esto si estás cambiando de área. Se analizará TODA tu experiencia para encontrar habilidades transferibles, sin importar cuán antigua sea."
        )
        if career_change:
            st.info("Modo cambio de carrera activo — se usará toda tu experiencia para encontrar lo transferible al nuevo rol.")
            st.caption("💡 Sube tu historial completo (hasta 30+ páginas). Toda la experiencia cuenta.")
        else:
            st.caption("💡 Sube tu CV completo — se analizarán hasta ~15 páginas priorizando lo más reciente.")
        cv_file = st.file_uploader("Sube tu CV", type=["pdf","docx"], label_visibility="collapsed")
        cv_text_manual = st.text_area("O pega el texto aquí", height=150,
            placeholder="Pega el contenido de tu CV si no tienes archivo...")
    with col2:
        st.subheader("💼 Oferta Laboral")
        job_url = st.text_input("🔗 Link de la oferta",
            placeholder="https://www.linkedin.com/jobs/...")
        job_description = st.text_area("O pega el texto aquí", height=215,
            placeholder="Pega aquí el texto de la oferta...")

    # ── Template — clickable cards ────────────────────────────────────────
    st.subheader("🎨 Elige tu Template")
    st.markdown("Haz clic en la tarjeta para seleccionarla. **Después de optimizar, descargas los 4 sin costo extra.**")

    if "template_choice" not in st.session_state:
        st.session_state["template_choice"] = "Clásico"

    tc1, tc2, tc3, tc4 = st.columns(4)
    for col, tname in zip([tc1, tc2, tc3, tc4], TEMPLATES.keys()):
        info = TEMPLATES[tname]
        is_sel = st.session_state["template_choice"] == tname
        border_col = info["color"] if is_sel else "#CCCCCC"
        bg_col = info["tags"][0] if is_sel else "#FAFAFA"
        accent = info["color"]
        check = "✅ " if is_sel else ""
        with col:
            st.markdown(f"""
<div style="border:2px solid {border_col};border-radius:12px;
    padding:1rem;background:{bg_col};height:260px;
    display:flex;flex-direction:column;
    transition:all 0.2s;">
  <div style="font-size:1.6rem;margin-bottom:0.3rem;">{info["icon"]}</div>
  <div style="font-weight:700;font-size:1rem;color:{accent};
      margin-bottom:0.2rem;">{check}{tname}</div>
  <div style="font-size:0.72rem;color:#777;margin-bottom:0.5rem;
      font-style:italic;">{info["ideal"]}</div>
  <div style="font-size:0.78rem;color:#444;line-height:1.5;flex:1;overflow:hidden;">
      {info["desc"]}</div>
</div>""", unsafe_allow_html=True)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            if st.button(f"{'✅ Seleccionado' if is_sel else 'Seleccionar'}", key=f"tpl_{tname}",
                         use_container_width=True,
                         type="primary" if is_sel else "secondary"):
                st.session_state["template_choice"] = tname
                st.rerun()

    template = st.session_state["template_choice"]
    st.markdown("---")

    # ── Regenerate only ────────────────────────────────────────────────────
    if st.session_state.get("regen_docx") and st.session_state.get("cv_data"):
        st.session_state["regen_docx"] = False
        show_results(st.session_state["cv_data"], template, font_family, font_size, max_pages)
        st.stop()

    # ── Main optimize button ───────────────────────────────────────────────
    if credits_left == 0 and plan != "admin" and not st.session_state.get("user_api_key"):
        st.button("🚀 Optimizar mi CV", use_container_width=True, disabled=True)
        st.markdown("""<div style="background:#FFF8E1;border-left:4px solid #FFA000;padding:0.8rem 1rem;border-radius:6px;margin-top:0.5rem">
        <strong>Agotaste tus análisis del mes 🎯</strong><br>
        Tu plan Free incluye 10 CVs al mes. ¿Quieres más?<br>
        <a href="mailto:contacto@analyze-this.app" style="color:#1B6CA8">Escríbenos para subir a Pro →</a>
        </div>""", unsafe_allow_html=True)
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
                career_change = st.session_state.get("career_change_mode", False)
                cv_data = optimize_cv(cv_text, final_job, max_pages, font_size, career_change)
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
