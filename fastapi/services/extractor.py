"""
Extraction helpers — PDF, DOCX, and URL scraping.
Copied from app2.py and decoupled from Streamlit.
"""
import re
import requests
from bs4 import BeautifulSoup
import pdfplumber
from docx import Document as DocxDocument


def is_valid_url(url: str) -> bool:
    return bool(re.match(r"^https?://", url.strip()))


def scrape_job_url(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
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
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "iframe"]):
        tag.decompose()

    text = ""
    for sel in [
        {"class": lambda c: c and any(k in " ".join(c).lower() for k in
            ["job-description", "description", "vacancy", "posting", "details", "content"])},
        {"id": lambda i: i and any(k in i.lower() for k in ["job-description", "description", "details"])},
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


def _detect_columns(page):
    """Return the X midpoint if the page has two columns, else None."""
    words = page.extract_words()
    if not words:
        return None
    x0, y0, x1, y1 = page.bbox
    width = x1 - x0
    left_words  = [w for w in words if w['x1'] < x0 + width * 0.5]
    right_words = [w for w in words if w['x0'] > x0 + width * 0.5]
    if left_words and right_words:
        max_left  = max(w['x1'] for w in left_words)
        min_right = min(w['x0'] for w in right_words)
        if min_right - max_left > 15:
            return (max_left + min_right) / 2
    return None


def extract_pdf(file_bytes: bytes) -> str:
    import io
    from .claude import _sanitize_cv_text
    text_pages = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            x0, y0, x1, y1 = page.bbox
            split_x = _detect_columns(page)

            if split_x:
                # Two-column layout: extract each side separately
                try:
                    left  = page.crop((x0, y0, split_x, y1)).extract_text() or ''
                    right = page.crop((split_x, y0, x1, y1)).extract_text() or ''
                    page_text = left + '\n\n' + right
                except Exception:
                    page_text = page.extract_text() or ''
            else:
                # Single column: tables first, then text
                parts = []
                try:
                    for table in (page.extract_tables() or []):
                        for row in table:
                            if row:
                                cells = [str(c).strip() for c in row if c and str(c).strip()]
                                if cells:
                                    parts.append("  |  ".join(cells))
                except Exception:
                    pass
                t = page.extract_text()
                if t:
                    parts.append(t)
                page_text = '\n'.join(parts)

            if page_text.strip():
                text_pages.append(page_text)

    return _sanitize_cv_text('\n\n'.join(text_pages))


def extract_docx(file_bytes: bytes) -> str:
    import io
    doc = DocxDocument(io.BytesIO(file_bytes))
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
