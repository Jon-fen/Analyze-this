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


def extract_pdf(file_bytes: bytes) -> str:
    import io
    from .claude import _sanitize_cv_text
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        if row:
                            cells = [str(c).strip() for c in row if c and str(c).strip()]
                            if cells:
                                text_parts.append("  |  ".join(cells))
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return _sanitize_cv_text("\n".join(text_parts))


def extract_docx(file_bytes: bytes) -> str:
    import io
    doc = DocxDocument(io.BytesIO(file_bytes))
    return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
