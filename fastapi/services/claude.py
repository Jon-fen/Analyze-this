"""
Claude optimization service — extracted from app2.py, Streamlit-free.
"""
import json
import re
import time
import unicodedata
import anthropic


def _sanitize_cv_text(text: str) -> str:
    """Normalise unicode, fix typographic quotes, strip control chars."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = (text
        .replace("\u201c", '"').replace("\u201d", '"')
        .replace("\u2018", "'").replace("\u2019", "'")
        .replace("\u00ab", '"').replace("\u00bb", '"')
        .replace("\u2032", "'").replace("\u2033", '"')
        .replace("\u2013", "-").replace("\u2014", "-")
        .replace("\x00", "")
        .replace("\r\n", "\n").replace("\r", "\n"))
    # Llaves {} → paréntesis para evitar que rompan el JSON de respuesta
    # Ej: {P}edagogical → (P)edagogical
    text = text.replace("{", "(").replace("}", ")")

    # Join URLs/data split across lines by two-column PDF layout.
    # Pattern: line ending with "-" followed by a line starting with digits
    # e.g. "linkedin.com/in/yasmina-contreras-soto-\n13709035"
    lines = text.split('\n')
    joined = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if (line.endswith('-')
                and i + 1 < len(lines)
                and lines[i + 1].strip()
                and lines[i + 1].strip()[0].isdigit()):
            joined.append(line + lines[i + 1].strip())
            i += 2
            continue
        joined.append(line)
        i += 1
    text = '\n'.join(joined)

    text = re.sub(r'\n{4,}', '\n\n\n', text)
    lines = [re.sub(r'  +', ' ', l).strip() for l in text.split('\n')]
    return '\n'.join(lines).strip()


def _fix_newlines_in_strings(json_str: str) -> str:
    """Replace bare newlines inside JSON string values with a space."""
    result = []
    in_string = False
    i = 0
    while i < len(json_str):
        ch = json_str[i]
        if ch == '\\' and i + 1 < len(json_str):
            result.append(ch)
            result.append(json_str[i + 1])
            i += 2
            continue
        if ch == '"':
            in_string = not in_string
        if in_string and ch == '\n':
            result.append(' ')
        elif in_string and ch == '\r':
            pass  # drop CR inside strings
        else:
            result.append(ch)
        i += 1
    return ''.join(result)


def _clean_claude_json(raw: str) -> str:
    """
    Sanitize the raw Claude response before json.loads.
    Handles typographic chars reproduced from CV text and bare newlines
    inside JSON string values (caused by two-column PDF layouts).
    """
    # Typographic single quotes → straight apostrophe
    raw = raw.replace("\u2018", "'").replace("\u2019", "'")
    # Typographic double quotes → straight double quote
    raw = raw.replace("\u201c", '"').replace("\u201d", '"')
    # Em/en dash → hyphen
    raw = raw.replace("\u2013", "-").replace("\u2014", "-")
    # Prime marks
    raw = raw.replace("\u2032", "'").replace("\u2033", '"')
    # Fix bare newlines inside JSON strings (the main cause for Yasmina's CV)
    raw = _fix_newlines_in_strings(raw)
    return raw


def _parse_claude_response(raw: str) -> dict:
    """Robust JSON parser with three fallback strategies."""
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    # Sanitize typographic chars and bare newlines inside JSON strings
    raw = _clean_claude_json(raw)

    import sys
    print(f"[DEBUG parse] first 300 chars: {repr(raw[:300])}", file=sys.stderr, flush=True)

    # Attempt 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[DEBUG parse] attempt 1 failed: pos={e.pos} msg={e.msg}", file=sys.stderr, flush=True)
        print(f"[DEBUG parse] context: {repr(raw[max(0,e.pos-40):e.pos+40])}", file=sys.stderr, flush=True)

    # Attempt 2: brace-balanced extraction
    try:
        start = raw.index('{')
        depth, end = 0, start
        for i, ch in enumerate(raw[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    # Attempt 3: truncate to last complete field
    try:
        truncated = raw.strip()
        truncated = re.sub(r',\s*"[^"]*$', '', truncated)
        truncated = re.sub(r',\s*$', '', truncated)
        if not truncated.endswith('}'):
            truncated += '}'
        return json.loads(truncated)
    except json.JSONDecodeError:
        pass

    raise ValueError(
        "El CV contiene caracteres especiales que dificultaron el análisis. "
        "Intenta pegar el texto directamente en el campo de texto."
    )

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
    cv_text = _sanitize_cv_text(cv_text)
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

TRANSFORMACIÓN CARGO → RESULTADO (obligatorio en cada logro):
- PROHIBIDO: "Responsable de X" / "Encargado de Y" / "A cargo de Z" / "Participé en"
- OBLIGATORIO: verbo de acción + impacto + contexto
  Correcto: "Reduje el tiempo de despacho 30% liderando equipo de 5 personas"
  Incorrecto: "Responsable del área de despacho"
- Si el CV original tiene métricas → usarlas exactas
- Si no hay métricas pero el contexto permite estimarlas → inferir rango razonable y marcarlo: "~30%", "de 3 a 8 clientes/día"
- Si no hay base para estimar → usar verbo fuerte sin métrica: "Lideré", "Implementé", "Diseñé", "Rediseñé", "Automaticé"
  NUNCA: "Fui responsable de", "Me encargué de", "Participé en"

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

IMPORTANTE — ESCAPE JSON: El texto del CV puede contener apostrofes posesivos,
comillas y símbolos especiales. Al escribir el JSON de respuesta, escápalos
correctamente: apostrofe dentro de string → \\'  , comilla dentro de string → \\".
No uses comillas sin escapar dentro de los valores JSON.

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
            try:
                return _parse_claude_response(raw)
            except (ValueError, json.JSONDecodeError):
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
