import datetime as dt
import io
import json
from decimal import Decimal

import pytest

from finagent.ingest.pdf_statement import parse_pdf_statement
from finagent.ingest.text import ocr_available
from finagent.services.documents import extract_document
from finagent.services.llm import LLMError

from .conftest import SAMPLE_DIR

needs_ocr = pytest.mark.skipif(not ocr_available(), reason="Tesseract OCR not installed")


def _text_pdf(lines: list[str]) -> bytes:
    """A PDF with plain text lines (no table grid), like many bank exports."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return buf.getvalue()


class FakeLLM:
    name = "fake"

    def __init__(self, text_reply=None, vision_reply=None):
        self.text_reply, self.vision_reply = text_reply, vision_reply
        self.vision_calls = self.text_calls = 0

    def complete(self, system, user, *, json_mode=False):
        self.text_calls += 1
        if self.text_reply is None:
            raise LLMError("no text model")
        return self.text_reply

    def complete_vision(self, system, user, image, mime, *, json_mode=False):
        self.vision_calls += 1
        if self.vision_reply is None:
            raise LLMError("no vision model")
        return self.vision_reply


# ---- PDF statements ---------------------------------------------------------


def test_pdf_statement_tables_match_csv():
    st = parse_pdf_statement((SAMPLE_DIR / "bank_statement_cafe.pdf").read_bytes())
    assert len(st.rows) == 59
    assert sum(r.amount for r in st.rows) == Decimal("1100.37")


def test_pdf_statement_text_lines_use_balance_for_sign():
    pdf = _text_pdf(
        [
            "Business Account Statement",
            "Balance brought forward 1,000.00",
            "03/02/2026 CARD PAYMENT TO STAPLES 45.10 954.90",
            "04/02/2026 STRIPE PAYOUT 300.00 1,254.90",
            "05/02/2026 DD BRITISH GAS 120.00 1,134.90",
            "Closing balance 1,134.90",
        ]
    )
    st = parse_pdf_statement(pdf)
    assert [(r.description, r.amount) for r in st.rows] == [
        ("CARD PAYMENT TO STAPLES", Decimal("-45.10")),
        ("STRIPE PAYOUT", Decimal("300.00")),
        ("DD BRITISH GAS", Decimal("-120.00")),
    ]


def test_pdf_statement_llm_fallback():
    pdf = _text_pdf(["Statement", "Payments made this month were lovely."])
    llm = FakeLLM(
        text_reply=json.dumps(
            {"transactions": [{"date": "2026-02-03", "description": "Rent", "amount": -900}]}
        )
    )
    st = parse_pdf_statement(pdf, llm=llm)
    assert st.rows[0].amount == Decimal("-900.00")
    assert st.warnings


def test_pdf_statement_unreadable_raises():
    with pytest.raises(ValueError):
        parse_pdf_statement(_text_pdf(["nothing useful here"]))


# ---- Receipts & invoices ----------------------------------------------------


@needs_ocr
def test_receipt_photo_ocr():
    f = extract_document(
        (SAMPLE_DIR / "receipts" / "receipt_home_depot.png").read_bytes(), "r.png", "receipt"
    )
    assert f.method == "ocr+regex"
    assert f.vendor == "THE HOME DEPOT"
    assert f.total == Decimal("74.85")
    assert f.tax == Decimal("4.65")
    assert f.date == dt.date(2026, 1, 3)


def test_invoice_pdf_regex():
    f = extract_document(
        (SAMPLE_DIR / "invoices" / "INV-2026-021.pdf").read_bytes(), "i.pdf", "invoice"
    )
    assert f.number == "INV-2026-021"
    assert f.client == "Riverside Book Club"
    assert f.client_email == "treasurer@riverside.example"
    assert (f.date, f.due_date) == (dt.date(2026, 5, 6), dt.date(2026, 6, 5))
    assert (f.total, f.tax) == (Decimal("486.00"), Decimal("30.20"))
    assert f.currency == "USD"


def test_vision_model_used_for_photos():
    reply = json.dumps({"vendor": "Corner Shop", "date": "2026-03-01", "total": "9.99"})
    llm = FakeLLM(vision_reply=reply)
    f = extract_document(b"\x89PNG fake", "photo.jpg", "receipt", llm=llm)
    assert (f.method, f.vendor, f.total) == ("vision", "Corner Shop", Decimal("9.99"))


def test_text_llm_used_for_pdfs_and_regex_fills_gaps():
    reply = json.dumps({"client": "Green LLC", "total": 317.60})  # no number/dates
    llm = FakeLLM(text_reply=reply)
    f = extract_document(
        (SAMPLE_DIR / "invoices" / "INV-2026-014.pdf").read_bytes(), "i.pdf", "invoice", llm=llm
    )
    assert f.method == "pdf-text+llm"
    assert f.number == "INV-2026-014"  # from regex
    assert f.due_date is not None
    assert llm.vision_calls == 0


def test_llm_failure_falls_back_to_regex():
    llm = FakeLLM()  # both modes raise
    f = extract_document(
        (SAMPLE_DIR / "receipts" / "receipt_costco.pdf").read_bytes(), "r.pdf", "receipt", llm=llm
    )
    assert f.method == "pdf-text+regex"
    assert f.total == Decimal("172.40")


def test_unsupported_document_type():
    with pytest.raises(ValueError):
        extract_document(b"hello", "notes.txt", "receipt")
