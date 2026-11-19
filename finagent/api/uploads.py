from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..ingest.text import IMAGE_TYPES
from ..schemas import ImportOut, InvoiceOut, ReceiptOut
from ..services.ingest import (
    DuplicateInvoiceError,
    ingest_invoice,
    ingest_receipt,
    ingest_statement,
)
from .invoices import to_out as invoice_out

router = APIRouter(prefix="/uploads", tags=["uploads"])

STATEMENT_TYPES = {".csv", ".pdf"}
DOCUMENT_TYPES = {".pdf", *IMAGE_TYPES}

# Endpoints are sync on purpose: FastAPI runs them in a threadpool, so blocking DB/OCR/LLM
# work does not stall the event loop.


def _read_limited(file: UploadFile, max_mb: int) -> bytes:
    data = file.file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {max_mb} MB")
    if not data:
        raise HTTPException(400, "File is empty")
    return data


def _check_type(file: UploadFile, allowed: set[str]) -> str:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        names = ", ".join(sorted(s.lstrip(".").upper() for s in allowed))
        raise HTTPException(415, f"Unsupported file type '{suffix}'. Supported: {names}")
    return suffix


@router.post("/statement", response_model=ImportOut)
def upload_statement(
    file: UploadFile = File(...),
    account: str | None = Form(default=None),
    use_llm: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    suffix = _check_type(file, STATEMENT_TYPES)
    data = _read_limited(file, get_settings().max_upload_mb)
    try:
        st = ingest_statement(
            db,
            data,
            file.filename or f"statement{suffix}",
            account=account or None,
            use_llm=use_llm,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return ImportOut(
        upload_id=st.upload.id,
        filename=st.upload.filename,
        imported=st.result.imported,
        duplicates=st.result.duplicates,
        skipped=st.parsed.skipped,
        categorized=st.result.categorized,
        uncategorized=st.result.uncategorized,
        warnings=st.parsed.warnings,
        invoices_paid=st.invoices_paid,
        receipts_linked=st.receipts_linked,
    )


@router.post("/receipt", response_model=ReceiptOut)
def upload_receipt(
    file: UploadFile = File(...),
    use_llm: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    _check_type(file, DOCUMENT_TYPES)
    data = _read_limited(file, get_settings().max_upload_mb)
    try:
        receipt, fields = ingest_receipt(db, data, file.filename or "receipt", use_llm=use_llm)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    out = ReceiptOut.model_validate(receipt)
    out.warnings = fields.warnings
    return out


@router.post("/invoice", response_model=InvoiceOut)
def upload_invoice(
    file: UploadFile = File(...),
    use_llm: bool = Form(default=True),
    payment_terms_days: int = Form(default=30, ge=0, le=365),
    db: Session = Depends(get_db),
):
    """Upload a sales invoice you issued; it is added to the unpaid tracker."""
    _check_type(file, DOCUMENT_TYPES)
    data = _read_limited(file, get_settings().max_upload_mb)
    try:
        inv, fields, warnings = ingest_invoice(
            db,
            data,
            file.filename or "invoice",
            use_llm=use_llm,
            payment_terms_days=payment_terms_days,
        )
    except DuplicateInvoiceError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return invoice_out(inv, extraction_method=fields.method, warnings=warnings)
