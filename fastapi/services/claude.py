"""
Claude optimization service — extracted from app2.py, Streamlit-free.
"""
import json
import time
import anthropic

MAX_CV_CHARS = 25_000
MAX_CV_CHARS_CAREER = 80_000


def optimize_cv(
    cv_text: str,
    job_text: str,
    max_pages: int,
    font_size: float,
    api_key: str,
    career_change: bool = False,
    cv_only: bool = False,
    output_lang: str = "es",
) -> dict:
    limit = MAX_CV_CHARS_CAREER if career_change else MAX_CV_CHARS
    was_truncated = len(cv_text) > limit
    cv_text = cv_text[:limit]

    words_per_page = {9: 700, 10: 600, 10.5: 560, 11: 520, 12: 460}
    max_words = words_per_page.get(float(font_size), 580) * max_pages

    lang_map = {"es": "español", "en": "English", "pt": "português"}
    lang_instruction = (
        f"\nIDIOMA DE SALIDA: Redacta TODO el CV optimizado (resumen, logros, habilidades, secciones) "
        f"en {lang_map.get(output_lang, 'español')}. El coaching y análisis también en ese idioma. "
        f"El CV original y la oferta pueden estar en idiomas distintos — eso no es problema, "
        f"compara su contenido y genera el output en el idioma solicitado.\n"
    )

    mode_instruction = (
        "MODO CAMBIO DE CARRERA — incluye experiencia de TODOS los períodos y reenmarca habilidades transferibles hacia el nuevo rol."
        if career_change
        else (
            "MODO ANÁLISIS GENERAL — no hay oferta específica. Analiza el CV: claridad ATS, modernidad, "
            "redacción de logros, estructura. Da recomendaciones concretas de mejora."
            if cv_only
            else "Selecciona la experiencia MÁS RECIENTE y relevante para esta oferta específica."
        )
    )

    prompt = f"""Eres un experto coach de carrera y especialista en optimización de CVs para sistemas ATS.
{lang_instruction}
{mode_instruction}

REGLA ABSOLUTA — CERO INVENCIÓN:
- Cada skill, herramienta, cargo, certificación y logro DEBE existir en el CV original
- Si el CV no menciona SAP → NO pongas SAP
- Si el CV no dice "Ingeniero de Materiales" → NO pongas ese título
- Si no hay experiencia en abastecimiento → NO pongas "especialista en abastecimiento"
- El título profesional debe ser el cargo real del CV más reciente, adaptado a la oferta — nunca inventado
- Ante la duda entre incluir algo o no → NO lo incluyas
Inventar datos es el error más grave posible. Es preferible un CV más corto que uno con datos falsos.

INSTRUCCIONES:
1. Solo reorganiza y reescribe lo que ya existe — NUNCA agregues información nueva
2. Integra las palabras clave de la oferta SOLO si tienen respaldo en el CV original
3. Reescribe logros con verbos de acción — pero con hechos reales del CV
4. Respeta el límite de {max_pages} página(s) ≈ {max_words} palabras
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
    {{"categoria": "Brecha crítica ⚠️", "tip": "Skill que falta y cómo cerrarla con curso/cert específica."}},
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
                max_tokens=3500,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
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

    # Paso 1: Haiku analiza (costo ~$0.01-0.02)
    result = call_model("claude-haiku-4-5-20251001")
    result["_was_truncated"] = was_truncated
    result["_model_used"] = "haiku"

    # Paso 2: Si score < 45, Opus reanaliza (~$0.15-0.20)
    if result.get("score_match", 100) < 45:
        result = call_model("claude-opus-4-5-20251101")
        result["_was_truncated"] = was_truncated
        result["_model_used"] = "opus"

    return result
