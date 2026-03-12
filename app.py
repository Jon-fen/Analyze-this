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

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CV Optimizer ATS",
    page_icon="🎯",
    layout="centered"
)

st.markdown("""
<style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .score-box { background: #F0F9FF; border-left: 4px solid #2E75B6;
                 padding: 1rem; border-radius: 4px; margin: 1rem 0; }
    div[data-testid="stDownloadButton"] button {
        background-color: #1B6CA8; color: white;
        font-size: 1rem; padding: 0.6rem 1.5rem;
        border-radius: 6px; width: 100%; }
</style>
""", unsafe_allow_html=True)

# ─── Header ───────────────────────────────────────────────────────────────────
st.title("🎯 CV Optimizer ATS")
st.markdown("Adapta tu CV a cualquier oferta laboral y supera los filtros automáticos.")

# ─── API Key ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuración")
    api_key = st.text_input("🔑 Anthropic API Key", type="password",
                             help="Obtén tu key en console.anthropic.com")
    st.markdown("---")
    st.markdown("**¿Cómo funciona?**")
    st.markdown("1. Sube tu CV (PDF o DOCX)")
    st.markdown("2. Pega la oferta de trabajo")
    st.markdown("3. Elige el template")
    st.markdown("4. Descarga tu CV optimizado")
    st.markdown("---")
    st.caption("Powered by Claude AI · Anthropic")

# ─── Input columns ────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("📄 Tu CV")
    cv_file = st.file_uploader("Sube tu CV", type=["pdf", "docx"],
                                label_visibility="collapsed")
    cv_text_manual = st.text_area(
        "O pega el texto aquí",
        height=220,
        placeholder="Pega el contenido de tu CV si no tienes archivo...",
        label_visibility="visible"
    )

with col2:
    st.subheader("💼 Oferta Laboral")
    job_description = st.text_area(
        "Pega la descripción del puesto",
        height=300,
        placeholder="Pega aquí el texto completo de la oferta a la que postulas...\n\nMientras más completa, mejor será la optimización.",
        label_visibility="collapsed"
    )

# ─── Template selector ────────────────────────────────────────────────────────
st.subheader("🎨 Template del CV")
t_col1, t_col2 = st.columns(2)

with t_col1:
    with st.container(border=True):
        st.markdown("**📋 Clásico**")
        st.markdown("Formato tradicional, ideal para finanzas, legal, gobierno y roles senior.")

with t_col2:
    with st.container(border=True):
        st.markdown("**✨ Moderno**")
        st.markdown("Diseño limpio con header destacado, ideal para tech, startups y marketing.")

template = st.radio("Selecciona template:", ["Clásico", "Moderno"],
                    horizontal=True, label_visibility="collapsed")

st.markdown("---")

# ─── Text extraction ──────────────────────────────────────────────────────────
def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text.strip()

def extract_text_from_docx(file):
    doc = DocxDocument(file)
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

# ─── Claude optimization ──────────────────────────────────────────────────────
def optimize_cv(api_key, cv_text, job_text):
    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""Eres un experto en optimización de CVs para sistemas ATS (Applicant Tracking Systems).

Analiza el CV y la oferta laboral proporcionados. Tu objetivo es:
1. Reorganizar y reescribir el contenido del CV para maximizar el match con la oferta
2. Integrar las palabras clave exactas de la oferta de forma natural
3. Cuantificar logros cuando sea posible
4. Priorizar la experiencia más relevante

CV ORIGINAL:
{cv_text}

OFERTA DE TRABAJO:
{job_text}

Devuelve ÚNICAMENTE el siguiente JSON válido, sin texto adicional ni backticks:
{{
  "nombre": "nombre completo de la persona",
  "titulo_profesional": "título adaptado exactamente al puesto ofrecido",
  "email": "email si está en el CV",
  "telefono": "teléfono si está en el CV",
  "linkedin": "URL LinkedIn si existe",
  "ubicacion": "ciudad y país",
  "resumen_profesional": "Párrafo de 3-4 oraciones que conecte la experiencia del candidato con los requisitos específicos del puesto. Incluir keywords clave de la oferta.",
  "experiencia": [
    {{
      "empresa": "nombre de la empresa",
      "cargo": "título del cargo",
      "periodo": "mes/año - mes/año o Actual",
      "logros": [
        "Logro 1 reescrito con verbos de acción y keywords ATS relevantes",
        "Logro 2 con métricas cuando sea posible",
        "Logro 3"
      ]
    }}
  ],
  "educacion": [
    {{
      "institucion": "nombre institución",
      "titulo": "título obtenido",
      "periodo": "años",
      "detalle": "mención honores, tesis relevante u otro detalle si aplica"
    }}
  ],
  "habilidades_tecnicas": ["skill relevante 1", "skill 2", "..."],
  "habilidades_blandas": ["competencia 1", "competencia 2"],
  "idiomas": ["Español - Nativo", "Inglés - B2"],
  "certificaciones": ["certificación 1 si existe"],
  "keywords_integradas": ["keyword1 de la oferta que se integró", "keyword2"],
  "keywords_faltantes": ["keyword importante que no pudo integrarse por falta de evidencia"],
  "score_match": 78,
  "sugerencias": [
    "Sugerencia concreta para mejorar el perfil para este tipo de rol",
    "Curso o certificación recomendada"
  ]
}}"""

    msg = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = msg.content[0].text.strip()

    # Clean if model adds backticks
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    return json.loads(raw)

# ─── Helper: section header with bottom border ────────────────────────────────
def add_section_header(doc, title, color_rgb, font_size=11, border_color="2E75B6", prefix=""):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(3)
    run = p.add_run(f"{prefix}{title}")
    run.bold = True
    run.font.size = Pt(font_size)
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

# ─── Template Clásico ─────────────────────────────────────────────────────────
def build_classic(cv):
    doc = DocxDocument()
    sec = doc.sections[0]
    sec.left_margin = Inches(1.0)
    sec.right_margin = Inches(1.0)
    sec.top_margin = Inches(0.8)
    sec.bottom_margin = Inches(0.8)

    DARK = (0x1A, 0x1A, 0x2E)
    BLUE = (0x2E, 0x75, 0xB6)
    GRAY = (0x66, 0x66, 0x66)

    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(cv.get("nombre", ""))
    r.bold = True
    r.font.size = Pt(20)
    r.font.color.rgb = RGBColor(*DARK)

    # Professional title
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(cv.get("titulo_profesional", ""))
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor(*BLUE)
    r.bold = True

    # Contact
    parts = [x for x in [cv.get("email"), cv.get("telefono"),
                          cv.get("ubicacion"), cv.get("linkedin")] if x]
    if parts:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("  |  ".join(parts))
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(*GRAY)

    # Summary
    if cv.get("resumen_profesional"):
        add_section_header(doc, "RESUMEN PROFESIONAL", BLUE)
        p = doc.add_paragraph(cv["resumen_profesional"])
        p.runs[0].font.size = Pt(10)

    # Experience
    if cv.get("experiencia"):
        add_section_header(doc, "EXPERIENCIA PROFESIONAL", BLUE)
        for exp in cv["experiencia"]:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            r = p.add_run(exp.get("cargo", ""))
            r.bold = True
            r.font.size = Pt(10)

            p2 = doc.add_paragraph()
            r2 = p2.add_run(f"{exp.get('empresa', '')}   |   {exp.get('periodo', '')}")
            r2.italic = True
            r2.font.size = Pt(9)
            r2.font.color.rgb = RGBColor(*GRAY)

            for logro in exp.get("logros", []):
                pb = doc.add_paragraph(style="List Bullet")
                pb.paragraph_format.left_indent = Inches(0.2)
                pb.paragraph_format.space_after = Pt(2)
                pb.add_run(logro).font.size = Pt(9)

    # Education
    if cv.get("educacion"):
        add_section_header(doc, "EDUCACIÓN", BLUE)
        for edu in cv["educacion"]:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(5)
            r = p.add_run(edu.get("titulo", ""))
            r.bold = True
            r.font.size = Pt(10)
            p2 = doc.add_paragraph()
            r2 = p2.add_run(f"{edu.get('institucion', '')}   |   {edu.get('periodo', '')}")
            r2.italic = True
            r2.font.size = Pt(9)
            r2.font.color.rgb = RGBColor(*GRAY)
            if edu.get("detalle"):
                p3 = doc.add_paragraph(edu["detalle"])
                p3.runs[0].font.size = Pt(9)

    # Technical skills
    if cv.get("habilidades_tecnicas"):
        add_section_header(doc, "HABILIDADES TÉCNICAS", BLUE)
        p = doc.add_paragraph("  •  ".join(cv["habilidades_tecnicas"]))
        p.runs[0].font.size = Pt(9)

    # Soft skills
    if cv.get("habilidades_blandas"):
        add_section_header(doc, "COMPETENCIAS", BLUE)
        p = doc.add_paragraph("  •  ".join(cv["habilidades_blandas"]))
        p.runs[0].font.size = Pt(9)

    # Languages
    if cv.get("idiomas"):
        add_section_header(doc, "IDIOMAS", BLUE)
        p = doc.add_paragraph("  |  ".join(cv["idiomas"]))
        p.runs[0].font.size = Pt(9)

    # Certifications
    certs = [c for c in cv.get("certificaciones", []) if c]
    if certs:
        add_section_header(doc, "CERTIFICACIONES", BLUE)
        for cert in certs:
            p = doc.add_paragraph(f"• {cert}")
            p.runs[0].font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ─── Template Moderno ─────────────────────────────────────────────────────────
def build_modern(cv):
    doc = DocxDocument()
    sec = doc.sections[0]
    sec.left_margin = Inches(0.75)
    sec.right_margin = Inches(0.75)
    sec.top_margin = Inches(0.6)
    sec.bottom_margin = Inches(0.8)

    NAVY  = (0x1B, 0x4F, 0x72)
    TEAL  = (0x17, 0x8A, 0xCA)
    DARK  = (0x22, 0x22, 0x22)
    GRAY  = (0x77, 0x77, 0x77)

    # Name
    p = doc.add_paragraph()
    r = p.add_run(cv.get("nombre", "").upper())
    r.bold = True
    r.font.size = Pt(22)
    r.font.color.rgb = RGBColor(*NAVY)

    # Title
    p = doc.add_paragraph()
    r = p.add_run(cv.get("titulo_profesional", ""))
    r.font.size = Pt(12)
    r.font.color.rgb = RGBColor(*TEAL)
    r.bold = True

    # Contact bar
    parts = []
    if cv.get("email"):    parts.append(f"✉ {cv['email']}")
    if cv.get("telefono"): parts.append(f"✆ {cv['telefono']}")
    if cv.get("ubicacion"):parts.append(f"⌖ {cv['ubicacion']}")
    if cv.get("linkedin"): parts.append(f"in {cv['linkedin']}")

    if parts:
        p = doc.add_paragraph()
        r = p.add_run("   |   ".join(parts))
        r.font.size = Pt(9)
        r.font.color.rgb = RGBColor(*GRAY)

    # Thick divider
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

    def section_hdr(title):
        add_section_header(doc, title, NAVY,
                           font_size=11, border_color="17A8CA", prefix="◆  ")

    # Summary
    if cv.get("resumen_profesional"):
        section_hdr("PERFIL PROFESIONAL")
        p = doc.add_paragraph(cv["resumen_profesional"])
        p.paragraph_format.left_indent = Inches(0.15)
        p.runs[0].font.size = Pt(10)

    # Experience
    if cv.get("experiencia"):
        section_hdr("EXPERIENCIA")
        for exp in cv["experiencia"]:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(7)
            p.paragraph_format.left_indent = Inches(0.15)
            r1 = p.add_run(exp.get("cargo", ""))
            r1.bold = True
            r1.font.size = Pt(10)
            r1.font.color.rgb = RGBColor(*NAVY)
            p.add_run("  —  ").font.size = Pt(10)
            r2 = p.add_run(exp.get("empresa", ""))
            r2.font.size = Pt(10)

            p2 = doc.add_paragraph()
            p2.paragraph_format.left_indent = Inches(0.15)
            r3 = p2.add_run(exp.get("periodo", ""))
            r3.italic = True
            r3.font.size = Pt(9)
            r3.font.color.rgb = RGBColor(*TEAL)

            for logro in exp.get("logros", []):
                pb = doc.add_paragraph()
                pb.paragraph_format.left_indent = Inches(0.35)
                pb.paragraph_format.space_after = Pt(2)
                pb.add_run(f"▸  {logro}").font.size = Pt(9)

    # Education
    if cv.get("educacion"):
        section_hdr("EDUCACIÓN")
        for edu in cv["educacion"]:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            p.paragraph_format.space_before = Pt(5)
            r1 = p.add_run(edu.get("titulo", ""))
            r1.bold = True
            r1.font.size = Pt(10)
            r1.font.color.rgb = RGBColor(*NAVY)
            p.add_run(f"   |   {edu.get('institucion','')}   |   {edu.get('periodo','')}").font.size = Pt(9)
            if edu.get("detalle"):
                p2 = doc.add_paragraph(edu["detalle"])
                p2.paragraph_format.left_indent = Inches(0.15)
                p2.runs[0].font.size = Pt(9)

    # Skills
    if cv.get("habilidades_tecnicas") or cv.get("habilidades_blandas"):
        section_hdr("HABILIDADES")
        if cv.get("habilidades_tecnicas"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            lbl = p.add_run("Técnicas: ")
            lbl.bold = True
            lbl.font.size = Pt(9)
            p.add_run("  •  ".join(cv["habilidades_tecnicas"])).font.size = Pt(9)
        if cv.get("habilidades_blandas"):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            lbl = p.add_run("Competencias: ")
            lbl.bold = True
            lbl.font.size = Pt(9)
            p.add_run("  •  ".join(cv["habilidades_blandas"])).font.size = Pt(9)

    # Languages
    if cv.get("idiomas"):
        section_hdr("IDIOMAS")
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.15)
        p.add_run("  |  ".join(cv["idiomas"])).font.size = Pt(9)

    # Certifications
    certs = [c for c in cv.get("certificaciones", []) if c]
    if certs:
        section_hdr("CERTIFICACIONES")
        for cert in certs:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.15)
            p.add_run(f"▸  {cert}").font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

# ─── Main action ──────────────────────────────────────────────────────────────
if st.button("🚀 Optimizar mi CV", use_container_width=True):
    if not api_key:
        st.error("⚠️ Ingresa tu API Key de Anthropic en el panel izquierdo.")
        st.stop()
    if not job_description.strip():
        st.error("⚠️ Por favor pega la oferta de trabajo.")
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
    with st.spinner("🤖 Claude está analizando tu CV y la oferta..."):
        try:
            cv_data = optimize_cv(api_key, cv_text, job_description)
        except json.JSONDecodeError:
            st.error("Error procesando la respuesta de Claude. Intenta nuevamente.")
            st.stop()
        except anthropic.AuthenticationError:
            st.error("API Key inválida. Revisa tu clave de Anthropic.")
            st.stop()
        except Exception as e:
            st.error(f"Error inesperado: {e}")
            st.stop()

    # Results dashboard
    st.markdown("---")
    st.subheader("📊 Resultado del Análisis")

    score = cv_data.get("score_match", 0)
    color = "🟢" if score >= 75 else "🟡" if score >= 55 else "🔴"
    st.metric(f"{color} Compatibilidad ATS con la oferta", f"{score}%")

    r1, r2 = st.columns(2)
    with r1:
        kw_ok = cv_data.get("keywords_integradas", [])
        if kw_ok:
            st.success(f"✅ **Keywords integradas ({len(kw_ok)}):**\n" +
                       ", ".join(kw_ok))
    with r2:
        kw_miss = cv_data.get("keywords_faltantes", [])
        if kw_miss:
            st.warning(f"⚠️ **Keywords no cubiertas ({len(kw_miss)}):**\n" +
                       ", ".join(kw_miss))

    sugs = cv_data.get("sugerencias", [])
    if sugs:
        with st.expander("💡 Sugerencias para fortalecer tu perfil"):
            for s in sugs:
                st.markdown(f"• {s}")

    # Generate DOCX
    with st.spinner(f"Generando CV en template {template}..."):
        try:
            buf = build_classic(cv_data) if template == "Clásico" else build_modern(cv_data)
        except Exception as e:
            st.error(f"Error generando el documento: {e}")
            st.stop()

    nombre = cv_data.get("nombre", "cv").replace(" ", "_")
    st.success("✅ ¡Tu CV optimizado está listo!")
    st.download_button(
        label=f"⬇️  Descargar CV Optimizado — Template {template}  (.docx)",
        data=buf,
        file_name=f"CV_ATS_{nombre}_{template}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

st.markdown("---")
st.caption("CV Optimizer ATS · Powered by Claude AI")
