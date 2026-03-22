"""
OCR helpers for scanned PDFs — uses PyMuPDF to render pages and Claude vision to extract text.
"""
import base64
from io import BytesIO
import pdfplumber
import anthropic


def is_scanned_pdf(file_bytes: bytes, extracted_text: str) -> bool:
    """Return True if PDF appears to be scanned (very little extractable text)."""
    text_length = len(extracted_text.strip())
    try:
        with pdfplumber.open(BytesIO(file_bytes)) as pdf:
            num_pages = len(pdf.pages)
    except Exception:
        num_pages = 1
    return text_length < max(150, num_pages * 100)


def extract_pdf_with_ocr(file_bytes: bytes, api_key: str) -> str:
    """Render PDF pages as images and extract text via Claude vision."""
    import fitz  # PyMuPDF

    text_parts = []
    client = anthropic.Anthropic(api_key=api_key)
    doc = fitz.open(stream=file_bytes, filetype="pdf")

    for page_num in range(min(len(doc), 8)):
        page = doc[page_num]
        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=mat)
        img_b64 = base64.standard_b64encode(pix.tobytes("png")).decode("utf-8")

        try:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Extrae todo el texto de esta página de CV exactamente como aparece, "
                                "manteniendo la estructura. Solo el texto, sin comentarios adicionales."
                            ),
                        },
                    ],
                }],
            )
            page_text = msg.content[0].text.strip()
            if page_text:
                text_parts.append(f"[Página {page_num + 1}]\n{page_text}")
        except Exception:
            continue

    doc.close()

    if not text_parts:
        raise ValueError(
            "No se pudo extraer texto del PDF. Intenta pegar el texto directamente."
        )

    return "\n\n".join(text_parts)
