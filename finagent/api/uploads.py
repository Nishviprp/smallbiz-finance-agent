from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..ingest.bank_csv import parse_bank_csv
from ..ingest.pdf_statement import parse_pdf_statement
from ..ingest.text import IMAGE_TYPES
from ..models import Invoice, Receipt, Upload
from ..schemas import ImportOut, InvoiceOut, ReceiptOut
from ..services.documents import extract_document
from ..services.importer import import_transactions
from ..services.invoices import match_payments
from ..services.llm import get_llm
from ..services.receipts import find_transaction, match_unlinked_receipts
from .invoices import ensure_unique_number
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


def _store(db: Session, data: bytes, filename: str, kind: str) -> Upload:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(filename or "upload").name.replace(" ", "_")[:120]
    path = settings.upload_dir / f"{uuid.uuid4().hex[:12]}_{safe}"
    path.write_bytes(data)
    upload = Upload(filename=filename or path.name, stored_path=str(path), kind=kind)
    db.add(upload)
    db.flush()
    return upload


@router.post("/statement", response_model=ImportOut)
def upload_statement(
    file: UploadFile = File(...),
    account: str | None = Form(default=None),
    use_llm: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    suffix = _check_type(file, STATEMENT_TYPES)
    data = _read_limited(file, settings.max_upload_mb)
    try:
        if suffix == ".pdf":
            parsed = parse_pdf_statement(
                data, settings.date_dayfirst, llm=get_llm() if use_llm else None
            )
        else:
            parsed = parse_bank_csv(data, default_dayfirst=settings.date_dayfirst)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    upload = _store(db, data, file.filename or f"statement{suffix}", "statement")
    result = import_transactions(
        db, parsed.rows, account=account or None, upload_id=upload.id, use_llm=use_llm
    )
    upload.rows_imported = result.imported
    upload.rows_duplicate = result.duplicates
    upload.rows_skipped = parsed.skipped
    db.commit()

    invoices_paid = match_payments(db) if result.imported else 0
    receipts_linked = (
        match_unlinked_receipts(db, settings.receipt_match_days) if result.imported else 0
    )

    return ImportOut(
        upload_id=upload.id,
        filename=upload.filename,
        imported=result.imported,
        duplicates=result.duplicates,
        skipped=parsed.skipped,
        categorized=result.categorized,
        uncategorized=result.uncategorized,
        warnings=parsed.warnings,
        invoices_paid=invoices_paid,
        receipts_linked=receipts_linked,
    )


@router.post("/receipt", response_model=ReceiptOut)
def upload_receipt(
    file: UploadFile = File(...),
    use_llm: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    _check_type(file, DOCUMENT_TYPES)
    data = _read_limited(file, settings.max_upload_mb)
    try:
        f = extract_document(
            data,
            file.filename or "receipt",
            "receipt",
            llm=get_llm() if use_llm else None,
            dayfirst=settings.date_dayfirst,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    upload = _store(db, data, file.filename or "receipt", "receipt")
    receipt = Receipt(
        upload_id=upload.id,
        vendor=f.vendor,
        date=f.date,
        total=f.total,
        tax=f.tax,
        currency=f.currency or settings.currency,
        extraction_method=f.method,
        raw_text=f.raw_text or None,
    )
    db.add(receipt)
    db.flush()
    txn = find_transaction(db, receipt, settings.receipt_match_days)
    if txn:
        receipt.transaction_id = txn.id
    db.commit()
    out = ReceiptOut.model_validate(receipt)
    out.warnings = f.warnings
    return out


@router.post("/invoice", response_model=InvoiceOut)
def upload_invoice(
    file: UploadFile = File(...),
    use_llm: bool = Form(default=True),
    payment_terms_days: int = Form(default=30, ge=0, le=365),
    db: Session = Depends(get_db),
):
    """Upload a sales invoice you issued; it is added to the unpaid tracker."""
    settings = get_settings()
    _check_type(file, DOCUMENT_TYPES)
    data = _read_limited(file, settings.max_upload_mb)
    try:
        f = extract_document(
            data,
            file.filename or "invoice",
            "invoice",
            llm=get_llm() if use_llm else None,
            dayfirst=settings.date_dayfirst,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if f.total is None:
        raise HTTPException(
            422, "Could not read the invoice total. Add it manually with POST /invoices."
        )

    ensure_unique_number(db, f.number)
    issue = f.date or dt.date.today()
    due = f.due_date if f.due_date and f.due_date >= issue else None
    warnings = list(f.warnings)
    if due is None:
        due = issue + dt.timedelta(days=payment_terms_days)
        warnings.append(f"No due date found; assumed {payment_terms_days}-day terms.")
    if not f.client:
        warnings.append("Client name not found — please edit the invoice.")

    upload = _store(db, data, file.filename or "invoice", "invoice")
    inv = Invoice(
        number=f.number,
        client=f.client or "Unknown client",
        client_email=f.client_email,
        issue_date=issue,
        due_date=due,
        amount=f.total,
        tax=f.tax,
        currency=f.currency or settings.currency,
        status="unpaid",
        upload_id=upload.id,
    )
    db.add(inv)
    db.commit()
    match_payments(db)
    db.refresh(inv)
    return invoice_out(inv, extraction_method=f.method, warnings=warnings)
