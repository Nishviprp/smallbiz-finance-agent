"""Get text out of PDFs and images (OCR)."""

from __future__ import annotations

import io
import logging
import shutil

log = logging.getLogger(__name__)

IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _open_pdf(data: bytes):
    import pdfplumber

    try:
        return pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer raises many different types on corrupt files
        raise ValueError(f"Could not read this PDF ({type(exc).__name__}).") from exc


def pdf_text(data: bytes, max_pages: int = 50) -> str:
    parts: list[str] = []
    with _open_pdf(data) as pdf:
        try:
            for page in pdf.pages[:max_pages]:
                parts.append(page.extract_text() or "")
        except Exception as exc:
            raise ValueError(f"Could not read this PDF ({type(exc).__name__}).") from exc
    return "\n".join(parts).strip()


def pdf_tables(data: bytes, max_pages: int = 50) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    with _open_pdf(data) as pdf:
        try:
            for page in pdf.pages[:max_pages]:
                for table in page.extract_tables() or []:
                    tables.append([[(c or "").strip() for c in row] for row in table])
        except Exception as exc:
            raise ValueError(f"Could not read this PDF ({type(exc).__name__}).") from exc
    return tables


def pdf_first_page_png(data: bytes, resolution: int = 200) -> bytes | None:
    """Render page 1 to PNG (for scanned PDFs → OCR / vision)."""
    try:
        with _open_pdf(data) as pdf:
            img = pdf.pages[0].to_image(resolution=resolution).original
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as exc:  # rendering needs optional deps (pypdfium2)
        log.info("Could not render PDF page: %s", exc)
        return None


def ocr_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_image(data: bytes) -> str:
    """OCR an image with Tesseract. Returns '' if OCR is not installed."""
    if not ocr_available():
        log.info("Tesseract not installed; skipping OCR")
        return ""
    import pytesseract
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")  # fix phone rotation, greyscale
    if img.width < 1000:  # small photos OCR better upscaled
        scale = 1000 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    return pytesseract.image_to_string(img).strip()
