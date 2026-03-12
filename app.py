import streamlit as st
import anthropic
import pdfplumber
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import io
import json
import requests
from bs4 import BeautifulSoup

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CV Optimizer ATS",
    page_icon="🎯",
    layout="centered"
)

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
</style>
""", unsafe_allow_html=True)

# ─── Header ───────────────────────────────────────────────────────────────────
st.title("🎯 CV Optimizer ATS")
st.markdown("Adapta tu CV a cualquier oferta laboral y supera los filtros automáticos.")

# ─── API Key ──────────────────────────────────────────────────────────────────
def get_api_key():
    try:
        return st.secrets["ANTHROPIC_API_KEY"]
    except (KeyError, FileNotFoundError):
        return None

_secret_key = get_api_key()

with st.sidebar:
    st.header("⚙️ Configuración")

    if _secret_key:
        api_key = _secret_key
        if st.session_state.get("api_credits_error"):
            st.warning("Servicio sin saldo. Puedes usar tu propia API Key:")
            user_key = st.text_input("🔑 Tu Anthropic API Key", type="password")
            if user_key:
                api_key = user_key
    else:
        st.warning("⚠️ Ingresa tu API Key de Anthropic")
        api_key = st.text_input("🔑 Anthropic API Key", type="password",
                                 help="Obtén tu key en console.anthropic.com")

    st.markdown("---")

    # ── Format controls ────────────────────────────────────────────────────
    st.markdown("**📐 Formato del CV**")

    max_pages = st.slider("Páginas máximas", min_value=1, max_value=3, value=2,
                           help="Claude seleccionará el contenido más relevante para ajustarse a este límite.")

    font_family = st.selectbox(
        "Tipografía",
        options=["Calibri", "Arial", "Georgia", "Times New Roman", "Helvetica"],
        index=0,
        help="Calibri y Arial son las más amigables con los ATS."
    )

    font_size = st.select_slider(
        "Tamaño de letra",
        options=[9, 10, 10.5, 11, 12],
        value=10,
        help="Los títulos se ajustan proporcionalmente."
    )

    st.markdown("---")
    st.markdown("**¿Cómo funciona?**")
    st.markdown("1. Sube tu CV (PDF o DOCX)")
    st.markdown("2. Pega o linkea la oferta")
    st.markdown("3. Configura formato y template")
    st.markdown("4. Descarga tu CV optimizado")
    st.markdown("---")
    st.caption("Powered by Claude AI · Anthropic")

# ─── Inputs ───────────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Tu CV")
    cv_file = st.file_uploader("Sube tu CV", type=["pdf", "docx"],
                                label_visibility="collapsed")
    cv_text_manual = st.text_area(
        "O pega el texto aquí",
        height=220,
        placeholder="Pega el contenido de tu CV si no tienes archivo...",
    )

with col2:
    st.subheader("💼 Oferta Laboral")
    job_url = st.text_input(
        "🔗 Link de la oferta",
        placeholder="https://www.linkedin.com/jobs/... o cualquier portal",
    )
    job_description = st.text_area(
        "O pega el texto aquí",
        height=215,
        placeholder="Pega aquí el texto de la oferta...\nMientras más completa, mejor la optimización.",
    )

# ─── Template selector ────────────────────────────────────────────────────────
st.subheader("🎨 Template del CV")
t_col1, t_col2 = st.columns(2)
with t_col1:
    with st.container(border=True):
        st.markdown("**📋 Clásico**")
        st.markdown("Formato tradicional. Ideal para finanzas, legal, gobierno y roles senior.")
with t_col2:
    with st.container(border=True):
        st.markdown("**✨ Moderno**")
        st.markdown("Diseño limpio con header destacado. Ideal para tech, startups y marketing.")

template = st.radio("Template:", ["Clásico", "Moderno"],
                    horizontal=True, label_visibility="collapsed")
st.markdown("---")

# ─── URL scraper ──────────────────────────────────────────────────────────────
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
        raise ValueError(f"No se pudo acceder ({e.response.status_code}). Pega el texto manualmente.")
    except Exception:
        raise ValueError("No se pudo acceder al link. Verifica la URL o pega el texto.")

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script","style","nav","footer","header","aside","form","noscript","iframe"]):
        tag.decompose()

    selectors = [
        {"class": lambda c: c and any(k in " ".join(c).lower() for k in
                                       ["job-description","description","vacancy","posting","details","content"])},
        {"id": lambda i: i and any(k in i.lower() for k in ["job-description","description","details"])},
    ]
    text = ""
    for sel in selectors:
        block = soup.find(attrs=sel)
        if block:
            text = block.get_text(separator="\n", strip=True)
            if len(text) > 200:
                break
    if not text or len(text) < 200:
        text = soup.get_text(separator="\n", strip=True)

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)[:8000]

# ─── File extraction ──────────────────────────────────────────────────────────
def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"
    return text.strip()

def extract_text_from_docx(file):
    doc = DocxDocument(file)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

# ─── Claude optimization ──────────────────────────────────────────────────────
def optimize_cv(api_key, cv_text, job_text, max_pages, font_size):
    client = anthropic.Anthropic(api_key=api_key)

    words_per_page = {9: 700, 10: 600, 10.5: 560, 11: 520, 12: 460}
    max_words = words_per_page.get(font_size, 580) * max_pages

    prompt = f"""Eres un experto coach de carrera y especialista en optimización de CVs para sistemas ATS (Applicant Tracking Systems).

Analiza el CV y la oferta laboral. Debes:
1. Seleccionar y adaptar SOLO el contenido más relevante para esta oferta (el CV puede ser extenso — prioriza sin inventar)
2. Integrar las palabras clave exactas de la oferta de forma natural
3. Reescribir los logros con verbos de acción cuantificados cuando sea posible
4. Respetar el límite de {max_pages} página(s) (~{max_words} palabras en el cuerpo del CV)
5. Evaluar si el CV resultante pasará filtros ATS automáticos

CV ORIGINAL:
{cv_text}

OFERTA DE TRABAJO:
{job_text}

Devuelve ÚNICAMENTE JSON válido (sin backticks, sin texto extra):
{{
  "nombre": "nombre completo",
  "titulo_profesional": "título adaptado exactamente al puesto",
  "email": "email si existe en el CV",
  "telefono": "teléfono si existe",
  "linkedin": "URL LinkedIn si existe",
  "ubicacion": "ciudad, país",

  "resumen_profesional": "Párrafo potente de 3-4 oraciones conectando la experiencia del candidato con los requisitos clave del puesto. Incluir keywords ATS de la oferta.",

  "experiencia": [
    {{
      "empresa": "nombre empresa",
      "cargo": "título del cargo",
      "periodo": "mes/año - mes/año o Actual",
      "logros": [
        "Verbo de acción + tarea/proyecto + impacto medible con keyword ATS integrada",
        "Otro logro cuantificado relevante para la oferta",
        "Máximo 3-4 logros por cargo, solo los más relevantes para esta oferta"
      ]
    }}
  ],

  "educacion": [
    {{
      "institucion": "nombre",
      "titulo": "título obtenido",
      "periodo": "años",
      "detalle": "mención si aplica, o dejar vacío"
    }}
  ],

  "habilidades_tecnicas": ["solo skills mencionados o inferibles del CV que son relevantes para la oferta"],
  "habilidades_blandas": ["máximo 4 competencias clave para el rol"],
  "idiomas": ["Español - Nativo", "Inglés - B2 (ejemplo)"],
  "certificaciones": ["solo si existen en el CV"],

  "ats_compatible": true,
  "ats_razon": "Frase breve explicando por qué sí o no pasa filtros ATS",

  "score_match": 82,
  "score_desglose": {{
    "keywords": 90,
    "experiencia": 80,
    "educacion": 75,
    "habilidades": 85
  }},
  "score_explicacion": "2-3 oraciones: qué hace fuerte al candidato para este rol y qué reduce el score.",

  "keywords_integradas": ["keyword1", "keyword2"],
  "keywords_faltantes": ["keyword importante ausente"],

  "coaching": [
    {{
      "categoria": "Tu fortaleza clave",
      "tip": "Qué tiene el candidato que es realmente valioso para este rol y cómo destacarlo."
    }},
    {{
      "categoria": "Brecha crítica",
      "tip": "Skill o experiencia que falta y cómo cerrar esa brecha: curso, certificación o proyecto concreto."
    }},
    {{
      "categoria": "Quick win",
      "tip": "Una acción concreta que puede hacer HOY para mejorar su candidatura para este rol."
    }},
    {{
      "categoria": "LinkedIn / Marca personal",
      "tip": "Sugerencia concreta para reforzar su perfil LinkedIn o presencia digital para este tipo de rol."
    }},
    {{
      "categoria": "Próximo paso",
      "tip": "Qué hacer después de enviar el CV: cómo investigar la empresa, networking relevante, qué preparar para la entrevista."
    }}
  ]
}}"""

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

    return json.loads(raw)

# ─── DOCX helpers ─────────────────────────────────────────────────────────────
def add_section_header(doc, title, color_rgb, font_name, body_size, border_color, prefix=""):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(body_size * 1.0)
    p.paragraph_format.space_after = Pt(body_size * 0.3)
    run = p.add_run(f"{prefix}{title}")
    run.bold = True
    run.font.name = font_name
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
    return p

def set_run(run, font_name, size, bold=False, italic=False, color=None):
    run.font.name = font_name
    run.font.size = Pt(float(size))
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)
    return run

# ─── Template Clásico ─────────────────────────────────────────────────────────
def build_classic(cv, font_name, font_size):
    fs = float(font_size)
    doc = DocxDocument()
    sec = doc.sections[0]
    sec.left_margin = Inches(1.0)
    sec.right_margin = Inches(1.0)
    sec.top_margin = Inches(0.8)
    sec.bottom_margin = Inches(0.8)

    DARK = (0x1A, 0x1A, 0x2E)
    BLUE = (0x2E, 0x75, 0xB6)
    GRAY = (0x66, 0x66, 0x66)

    def hdr(title):
        return add_section_header(doc, title, BLUE, font_name, fs, "2E75B6")

    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(cv.get("nombre", "")), font_name, fs+9, bold=True, color=DARK)

    # Title
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_run(p.add_run(cv.get("titulo_profesional", "")), font_name, fs+2, bold=True, color=BLUE)

    # Contact
    parts = [x for x in [cv.get("email"), cv.get("telefono"),
                          cv.get("ubicacion"), cv.get("linkedin")] if x]
    if parts:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run(p.add_run("  |  ".join(parts)), font_name, fs-1, color=GRAY)

    if cv.get("resumen_profesional"):
        hdr("RESUMEN PROFESIONAL")
        p = doc.add_paragraph()
        set_run(p.add_run(cv["resumen_profesional"]), font_name, fs)

    if cv.get("experiencia"):
        hdr("EXPERIENCIA PROFESIONAL")
        for exp in cv["experiencia"]:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(fs * 0.6)
            set_run(p.add_run(exp.get("cargo", "")), font_name, fs, bold=True)
            p2 = doc.add_paragraph()
            set_run(p2.add_run(f"{exp.get('empresa','')}   |   {exp.get('periodo','')}"),
                    font_name, fs-1, italic=True, color=GRAY)
            for logro in exp.get("logros", []):
                pb = doc.add_paragraph(style="List Bullet")
                pb.paragraph_format.left_indent = Inches(0.2)
                pb.paragraph_format.space_after = Pt(2)
                set_run(pb.add_run(logro), font_name, fs)

    if cv.get("educacion"):
        hdr("EDUCACIÓN")
        for edu in cv["educacion"]:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(fs * 0.5)
            set_run(p.add_run(edu.get("titulo", "")), font_name, fs, bold=True)
            p2 = doc.add_paragraph()
            set_run(p2.add_run(f"{edu.get('institucion','')}   |   {edu.get('periodo','')}"),
                    font_name, fs-1, italic=True, color=GRAY)
            if edu.get("detalle"):
                p3 = doc.add_paragraph()
                set_run(p3.add_run(edu["detalle"]), font_name, fs-1)

    if cv.get("habilidades_tecnicas"):
        hdr("HABILIDADES TÉCNICAS")
        p = doc.add_paragraph()
        set_run(p.add_run("  •  ".join(cv["habilidades_tecnicas"])), font_name, fs)

    if cv.get("habilidades_blandas"):
        hdr("COMPETENCIAS")
        p = doc.add_paragraph()
        set_run(p.add_run("  •  ".join(cv["habilidades_blandas"])), font_name, fs)

    if cv.get("idiomas"):
        hdr("IDIOMAS")
        p = doc.add_paragraph()
        set_run(p.add_run("  |  ".join(cv["idiomas"])), font_name, fs)

    certs = [c for c in cv.get("certificaciones", []) if c]
    if certs:
        hdr("CERTIFICACIONES")
        for cert in certs:
            p = doc.add_paragraph()
            set_run(p.add_run(f"• {cert}"), font_name, fs)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ─── Template Moderno ─────────────────────────────────────────────────────────
def build_modern(cv, font_name, font_size):
    fs = float(font_size)
    doc = DocxDocument()
    sec = doc.sections[0]
    sec.left_margin = Inches(0.75)
    sec.right_margin = Inches(0.75)
    sec.top_margin = Inches(0.6)
    sec.bottom_margin = Inches(0.8)

    NAVY = (0x1B, 0x4F, 0x72)
    TEAL = (0x17, 0x8A, 0xCA)
    GRAY = (0x77, 0x77, 0x77)

    def section_hdr(title):
        add_section_header(doc, title, NAVY, font_name, fs, "17A8CA", prefix="◆  ")

    # Name
    p = doc.add_paragraph()
    set_run(p.add_run(cv.get("nombre", "").upper()), font_name, fs+11, bold=True, color=NAVY)

    # Title
    p = doc.add_paragraph()
    set_run(p.add_run(cv.get("titulo_profesional", "")), font_name, fs+2, bold=True, color=TEAL)

    # Contact
    parts = []
    if cv.get("email"):     parts.append(f"✉ {cv['email']}")
    if cv.get("telefono"):  parts.append(f"✆ {cv['telefono']}")
    if cv.get("ubicacion"): parts.append(f"⌖ {cv['ubicacion']}")
    if cv.get("linkedin"):  parts.append(f"in {cv['linkedin']}")
    if parts:
        p = doc.add_paragraph()
        set_run(p.add_run("   |   ".join(parts)), font_name, fs-1, color=GRAY)

    # Divider
    p_div = doc.add_paragraph()
    p_div.paragraph_format.space_after = Pt(8)
    pPr = p_div._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    pPr.append(pBdr)
    btm = OxmlElement('w:bottom')
    btm.set(qn('w:val'), 'single')
    btm.set(qn('w:sz'), '16')
    btm.set(qn('w:space'), '1')
    btm.set(qn('w:color'), '1B4F72')
    pBdr.append(btm)

    if cv.get("resumen_profesional"):
        section_hdr("PERFIL PROFESIONAL")
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.15)
        set_run(p.add_run(cv["resumen_profesional"]), font_name, fs)

    if cv.get("experiencia"):
        section_hdr("EXPERIENCIA")
        for exp in cv["experiencia"]:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(fs * 0.7)
            p.paragraph_format.left_indent = Inches(0.15)
            set_run(p.add_run(exp.get("cargo", "")), font_name, fs, bold=True, color=NAVY)
            set_run(p.add_run("  —  "), font_name, fs)
            set_run(p.add_run(exp.get("empresa", "")), font_name, fs)
            p2 = doc.add_paragraph()
            p2.paragraph_format.left_indent = Inches(0.15)
            set_run(p2.add_run(exp.get("periodo", "")), font_name, fs-1, italic=True, color=TEAL)
            for logro in exp.get("logros", []):
                pb = doc.add_paragraph()
                pb.paragraph_format.left_indent = Inches(0.35)
                pb.paragraph_format.space_after = Pt(2)
                set_run(pb.add_run(f"▸  {logro}"), font_name, fs)

    if cv.get("educacion"):
        section_hdr("EDUCACIÓN")
        for edu in cv["educacion"]:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            p.paragraph_format.space_before = Pt(fs * 0.5)
            set_run(p.add_run(edu.get("titulo", "")), font_name, fs, bold=True, color=NAVY)
            set_run(p.add_run(f"   |   {edu.get('institucion','')}   |   {edu.get('periodo','')}"), font_name, fs-1)
            if edu.get("detalle"):
                p2 = doc.add_paragraph()
                p2.paragraph_format.left_indent = Inches(0.15)
                set_run(p2.add_run(edu["detalle"]), font_name, fs-1)

    if cv.get("habilidades_tecnicas") or cv.get("habilidades_blandas"):
        section_hdr("HABILIDADES")
        if cv.get("habilidades_tecnicas"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            set_run(p.add_run("Técnicas: "), font_name, fs, bold=True)
            set_run(p.add_run("  •  ".join(cv["habilidades_tecnicas"])), font_name, fs)
        if cv.get("habilidades_blandas"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            set_run(p.add_run("Competencias: "), font_name, fs, bold=True)
            set_run(p.add_run("  •  ".join(cv["habilidades_blandas"])), font_name, fs)

    if cv.get("idiomas"):
        section_hdr("IDIOMAS")
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.15)
        set_run(p.add_run("  |  ".join(cv["idiomas"])), font_name, fs)

    certs = [c for c in cv.get("certificaciones", []) if c]
    if certs:
        section_hdr("CERTIFICACIONES")
        for cert in certs:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            set_run(p.add_run(f"▸  {cert}"), font_name, fs)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ─── Main action ──────────────────────────────────────────────────────────────
if st.button("🚀 Optimizar mi CV", use_container_width=True):
    if not api_key:
        st.error("⚠️ No hay API Key disponible.")
        st.stop()

    # Resolve job text
    final_job = job_description.strip()
    if job_url.strip():
        with st.spinner("🔍 Leyendo la oferta desde el link..."):
            try:
                scraped = scrape_job_url(job_url.strip())
                if scraped:
                    final_job = scraped
                    st.success(f"✅ Oferta leída ({len(scraped)} caracteres extraídos)")
                else:
                    st.warning("No se pudo extraer texto del link. Usando el texto pegado.")
            except ValueError as e:
                st.warning(str(e))

    if not final_job:
        st.error("⚠️ Pega la oferta de trabajo o ingresa un link válido.")
        st.stop()

    # Extract CV text
    cv_text = ""
    if cv_file:
        with st.spinner("Extrayendo texto del archivo..."):
            try:
                if cv_file.name.lower().endswith(".pdf"):
                    cv_text = extract_text_from_pdf(cv_file)
                elif cv_file.name.lower().endswith(".docx"):
                    cv_text = extract_text_from_docx(cv_file)
            except Exception as e:
                st.error(f"Error al leer el archivo: {e}")
                st.stop()

    if cv_text_manual.strip():
        cv_text = cv_text_manual.strip() if not cv_text else cv_text + "\n" + cv_text_manual.strip()

    if not cv_text:
        st.error("⚠️ Sube un archivo CV o pega el texto manualmente.")
        st.stop()

    # Optimize with Claude
    with st.spinner("🤖 Claude está analizando tu CV y preparando tu reporte de coaching..."):
        try:
            cv_data = optimize_cv(api_key, cv_text, final_job, max_pages, font_size)
            st.session_state["api_credits_error"] = False
        except json.JSONDecodeError:
            st.error("Error procesando la respuesta. Intenta nuevamente.")
            st.stop()
        except anthropic.AuthenticationError:
            st.error("API Key inválida.")
            st.stop()
        except anthropic.RateLimitError:
            st.session_state["api_credits_error"] = True
            st.error("⚠️ Servicio sin saldo. Puedes ingresar tu API Key en el panel lateral.")
            st.rerun()
        except Exception as e:
            st.error(f"Error inesperado: {e}")
            st.stop()

    # ── Results ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📊 Análisis de Compatibilidad")

    # ATS badge + score side by side
    ats_ok = cv_data.get("ats_compatible", True)
    ats_razon = cv_data.get("ats_razon", "")
    score = cv_data.get("score_match", 0)
    score_color = "🟢" if score >= 75 else "🟡" if score >= 55 else "🔴"

    badge_col, score_col = st.columns([1, 2])
    with badge_col:
        if ats_ok:
            st.success("✅ ATS Compatible")
        else:
            st.error("❌ No ATS Compatible")
        if ats_razon:
            st.caption(ats_razon)

    with score_col:
        st.metric(f"{score_color} Match con la oferta", f"{score}%")
        explain = cv_data.get("score_explicacion", "")
        if explain:
            st.markdown(f'<div class="score-explain">{explain}</div>', unsafe_allow_html=True)

    # Score breakdown
    desglose = cv_data.get("score_desglose", {})
    if desglose:
        with st.expander("📈 Ver desglose del score"):
            d1, d2, d3, d4 = st.columns(4)
            d1.metric("Keywords", f"{desglose.get('keywords', '-')}%")
            d2.metric("Experiencia", f"{desglose.get('experiencia', '-')}%")
            d3.metric("Educación", f"{desglose.get('educacion', '-')}%")
            d4.metric("Habilidades", f"{desglose.get('habilidades', '-')}%")

    # Keywords
    st.markdown("---")
    k1, k2 = st.columns(2)
    with k1:
        kw_ok = cv_data.get("keywords_integradas", [])
        if kw_ok:
            st.success(f"✅ **Keywords integradas ({len(kw_ok)}):**\n" + ", ".join(kw_ok))
    with k2:
        kw_miss = cv_data.get("keywords_faltantes", [])
        if kw_miss:
            st.warning(f"⚠️ **Keywords ausentes ({len(kw_miss)}):**\n" + ", ".join(kw_miss))

    # Coaching — shown openly, not hidden in expander
    coaching = cv_data.get("coaching", [])
    if coaching:
        st.markdown("---")
        st.subheader("🎯 Tu Plan de Acción")
        st.markdown("Recomendaciones personalizadas para maximizar tus chances en **esta** postulación:")
        for tip_item in coaching:
            cat = tip_item.get("categoria", "")
            tip_txt = tip_item.get("tip", "")
            st.markdown(
                f'<div class="coach-card"><strong>{cat}</strong><br>{tip_txt}</div>',
                unsafe_allow_html=True
            )

    # Generate DOCX
    st.markdown("---")
    with st.spinner(f"Generando CV — {template} · {font_family} {font_size}pt · {max_pages} página(s)..."):
        try:
            if template == "Clásico":
                buf = build_classic(cv_data, font_family, font_size)
            else:
                buf = build_modern(cv_data, font_family, font_size)
        except Exception as e:
            st.error(f"Error generando el documento: {e}")
            st.stop()

    nombre = cv_data.get("nombre", "cv").replace(" ", "_")
    st.success("✅ ¡Tu CV optimizado está listo!")
    st.download_button(
        label=f"⬇️  Descargar CV — Template {template} · {font_family} {font_size}pt  (.docx)",
        data=buf,
        file_name=f"CV_ATS_{nombre}_{template}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

st.markdown("---")
st.caption("CV Optimizer ATS · Powered by Claude AI · Anthropic")
