"""Extract key fields from receipts and invoices (PDF or photo).

Pipeline: vision LLM (if configured) → text (PDF layer or OCR) + LLM → text + regex.
Every field is optional; the user can correct anything afterwards.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from ..ingest.common import clean_text, parse_amount, parse_date
from ..ingest.text import IMAGE_TYPES, ocr_image, pdf_first_page_png, pdf_text
from .llm import LLMClient, LLMError, extract_json

log = logging.getLogger(__name__)

DocKind = Literal["receipt", "invoice"]


@dataclass
class DocumentFields:
    vendor: str | None = None  # who issued it (shop / your business)
    client: str | None = None  # invoices: who must pay
    client_email: str | None = None
    number: str | None = None
    date: dt.date | None = None
    due_date: dt.date | None = None
    total: Decimal | None = None
    tax: Decimal | None = None
    currency: str | None = None
    raw_text: str = ""
    method: str = "none"
    warnings: list[str] = field(default_factory=list)


def extract_document(
    data: bytes,
    filename: str,
    kind: DocKind,
    llm: LLMClient | None = None,
    dayfirst: bool = True,
) -> DocumentFields:
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    is_pdf = suffix == ".pdf" or data[:5] == b"%PDF-"
    image: bytes | None = None
    mime = "image/png"
    text = ""

    if is_pdf:
        text = pdf_text(data, max_pages=5)
        method_text = "pdf-text"
        if not text:  # scanned PDF: treat page 1 as a photo
            image = pdf_first_page_png(data)
            method_text = "pdf-ocr"
    elif suffix in IMAGE_TYPES:
        image, mime = data, IMAGE_TYPES[suffix]
        method_text = "ocr"
    else:
        raise ValueError(f"Unsupported file type '{suffix}'. Use PDF, JPG, PNG or WEBP.")

    warnings: list[str] = []

    # 1. Vision model reads the photo directly (best for crumpled receipts).
    if llm is not None and image is not None:
        try:
            result = _llm_fields(llm, kind, "", image, mime, dayfirst)
            if result.total is not None:
                result.method = "vision"
                return result
        except LLMError as exc:
            log.info("Vision extraction unavailable: %s", exc)

    # 2. Get text (PDF layer or OCR).
    if image is not None and not text:
        text = ocr_image(image)
    if not text:
        return DocumentFields(
            method="none",
            warnings=["No text could be read. Install Tesseract OCR or set a vision model."],
        )

    # 3. Text LLM, topped up by regex.
    if llm is not None:
        try:
            result = _llm_fields(llm, kind, text, None, mime, dayfirst)
            if result.total is not None:
                result.method, result.raw_text = f"{method_text}+llm", text
                _fill_from_regex(result, text, kind, dayfirst)
                return result
        except LLMError as exc:
            log.info("LLM extraction unavailable: %s", exc)
            warnings.append("AI extraction unavailable; fields read with pattern matching.")

    # 4. Regex only.
    fields = DocumentFields(raw_text=text, method=f"{method_text}+regex", warnings=warnings)
    _fill_from_regex(fields, text, kind, dayfirst)
    if fields.total is None:
        fields.warnings.append("Total not found — please enter it manually.")
    return fields


# ---- LLM ------------------------------------------------------------------------

_LLM_SYSTEM = (
    "You read {kind}s for a small-business bookkeeping app. Extract only what is printed; "
    "use null for anything missing. Dates as YYYY-MM-DD. Amounts as plain numbers."
)
_LLM_SCHEMA = {
    "receipt": '{"vendor": str, "date": str, "total": num, "tax": num, "currency": "GBP|USD|..."}',
    "invoice": (
        '{"vendor": "issuer", "client": "billed to", "client_email": str, "number": str, '
        '"date": "issue date", "due_date": str, "total": "amount due incl. tax", '
        '"tax": num, "currency": str}'
    ),
}


def _llm_fields(
    llm: LLMClient,
    kind: DocKind,
    text: str,
    image: bytes | None,
    mime: str,
    dayfirst: bool,
) -> DocumentFields:
    system = _LLM_SYSTEM.format(kind=kind)
    prompt = f"Return JSON exactly like: {_LLM_SCHEMA[kind]}"
    if text:
        prompt += f"\n\nDocument text (may contain OCR errors):\n{text[:8000]}"
    if image is not None:
        reply = llm.complete_vision(system, prompt, image, mime, json_mode=True)
    else:
        reply = llm.complete(system, prompt, json_mode=True)
    d = extract_json(reply)
    if not isinstance(d, dict):
        raise LLMError("Expected a JSON object")

    def s(key: str) -> str | None:
        v = d.get(key)
        return clean_text(v)[:200] or None if isinstance(v, str) else None

    total = parse_amount(d.get("total"))
    tax = parse_amount(d.get("tax"))
    currency = (s("currency") or "").upper()[:3] or None
    return DocumentFields(
        vendor=s("vendor"),
        client=s("client"),
        client_email=s("client_email"),
        number=s("number"),
        date=parse_date(s("date"), dayfirst),
        due_date=parse_date(s("due_date"), dayfirst),
        total=abs(total) if total is not None else None,
        tax=abs(tax) if tax is not None else None,
        currency=currency if currency and currency.isalpha() else None,
    )


# ---- Regex fallback -------------------------------------------------------------

_AMOUNT = r"[-(]?[£$€]?\s?\d{1,3}(?:[,\s]\d{3})*(?:[.,]\d{2})\)?"
_DATE = (
    r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}"
)
_TOTAL_STRONG = re.compile(
    rf"(?:grand\s+total|amount\s+due|balance\s+due|total\s+due|total\s+to\s+pay|"
    rf"total\s+payable|amount\s+payable)\b[^\d\n]*?({_AMOUNT})",
    re.I,
)
_TOTAL = re.compile(rf"(?<!sub)(?<!sub\s)(?<!sub-)\btotal\b[^\d\n]*?({_AMOUNT})", re.I)
_TAX = re.compile(
    rf"\b(?:vat|tax|gst|hst|sales\s+tax)\b(?:\s*\(?\d{{1,2}}(?:\.\d+)?\s*%\)?)?"
    rf"[^\d\n%]*?({_AMOUNT})",
    re.I,
)
_DUE = re.compile(rf"\b(?:due\s+date|payment\s+due|due\s+by|due\s+on|due)\b\s*:?\s*({_DATE})", re.I)
_ISSUE = re.compile(
    rf"\b(?:invoice\s+date|issue\s+date|date\s+issued|date\s+of\s+issue|tax\s+point|date)\b"
    rf"\s*:?\s*({_DATE})",
    re.I,
)
_ANY_DATE = re.compile(rf"({_DATE})")
_NUMBER = re.compile(
    r"\binvoice\s*(?:no\.?|number|num|#)\s*:?\s*#?\s*([A-Z0-9][A-Z0-9\-/_.]{1,30})", re.I
)
_BILL_TO = re.compile(r"\b(?:bill(?:ed)?\s+to|invoice\s+to|customer|client)\b\s*:?\s*(.*)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CURRENCY = {"£": "GBP", "$": "USD", "€": "EUR"}


def _fill_from_regex(f: DocumentFields, text: str, kind: DocKind, dayfirst: bool) -> None:
    """Fill only the fields that are still empty."""
    if not text:
        return
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    if f.total is None:
        m = _TOTAL_STRONG.findall(text) or _TOTAL.findall(text)
        found = [a for a in (_abs(parse_amount(x)) for x in m) if a is not None]
        if found:
            f.total = max(found)
        else:  # fall back to the largest amount on the page
            amounts = [_abs(parse_amount(a)) for a in re.findall(_AMOUNT, text)]
            amounts = [a for a in amounts if a is not None]
            f.total = max(amounts) if amounts else None
    if f.tax is None:
        m = _TAX.findall(text)
        if m:
            tax = _abs(parse_amount(m[-1]))
            f.tax = tax if tax is not None and (f.total is None or tax < f.total) else None
    if f.due_date is None and kind == "invoice":
        m = _DUE.search(text)
        f.due_date = parse_date(m.group(1), dayfirst) if m else None
    if f.date is None:
        m = _ISSUE.search(text) or _ANY_DATE.search(text)
        f.date = parse_date(m.group(1), dayfirst) if m else None
    if f.number is None and kind == "invoice":
        m = _NUMBER.search(text)
        f.number = m.group(1).strip(".") if m else None
    if f.vendor is None and lines:
        f.vendor = next((ln[:200] for ln in lines if re.search(r"[A-Za-z]{3}", ln)), None)
    if kind == "invoice" and f.client is None:
        for i, ln in enumerate(lines):
            m = _BILL_TO.match(ln)
            if m:
                same_line = m.group(1).strip()
                f.client = (same_line or (lines[i + 1] if i + 1 < len(lines) else ""))[:200] or None
                break
    if kind == "invoice" and f.client_email is None:
        emails = _EMAIL.findall(text)
        # The client's email usually comes after the issuer's.
        f.client_email = emails[-1] if emails else None
    if f.currency is None:
        f.currency = next((code for sym, code in _CURRENCY.items() if sym in text), None)


def _abs(v: Decimal | None) -> Decimal | None:
    return abs(v) if v is not None else None
