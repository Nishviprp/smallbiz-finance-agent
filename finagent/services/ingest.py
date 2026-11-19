"""File ingestion shared by the upload API and the demo loader."""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..ingest.bank_csv import parse_bank_csv
from ..ingest.common import ParsedStatement
from ..ingest.pdf_statement import parse_pdf_statement
from ..models import Invoice, Receipt, Upload
from .business import get_profile
from .documents import DocumentFields, extract_document
from .importer import ImportResult, import_transactions
from .invoices import match_payments
from .llm import get_llm
from .receipts import find_transaction, match_unlinked_receipts


class DuplicateInvoiceError(ValueError):
    def __init__(self, number: str, existing_id: int):
        super().__init__(f"Invoice {number} already exists (id {existing_id})")
        self.existing_id = existing_id


def store_upload(db: Session, data: bytes, filename: str, kind: str) -> Upload:
    folder = get_settings().upload_dir / f"business_{db.info.get('business_id', 'x')}"
    folder.mkdir(parents=True, exist_ok=True)
    safe = Path(filename or "upload").name.replace(" ", "_")[:120]
    path = folder / f"{uuid.uuid4().hex[:12]}_{safe}"
    path.write_bytes(data)
    upload = Upload(filename=filename or path.name, stored_path=str(path), kind=kind)
    db.add(upload)
    db.flush()
    return upload


@dataclass
class StatementResult:
    upload: Upload
    parsed: ParsedStatement
    result: ImportResult
    invoices_paid: int = 0
    receipts_linked: int = 0


def ingest_statement(
    db: Session, data: bytes, filename: str, *, account: str | None = None, use_llm: bool = True
) -> StatementResult:
    """Parse + import a CSV/PDF statement. Raises ValueError if the file can't be read."""
    profile = get_profile(db)
    if filename.lower().endswith(".pdf"):
        parsed = parse_pdf_statement(
            data, profile.date_dayfirst, llm=get_llm() if use_llm else None
        )
    else:
        parsed = parse_bank_csv(data, default_dayfirst=profile.date_dayfirst)

    upload = store_upload(db, data, filename, "statement")
    result = import_transactions(
        db, parsed.rows, account=account, upload_id=upload.id, use_llm=use_llm
    )
    upload.rows_imported = result.imported
    upload.rows_duplicate = result.duplicates
    upload.rows_skipped = parsed.skipped
    db.commit()

    out = StatementResult(upload, parsed, result)
    if result.imported:
        out.invoices_paid = match_payments(db)
        out.receipts_linked = match_unlinked_receipts(db, get_settings().receipt_match_days)
    return out


def ingest_receipt(
    db: Session, data: bytes, filename: str, *, use_llm: bool = True
) -> tuple[Receipt, DocumentFields]:
    profile = get_profile(db)
    f = extract_document(
        data,
        filename or "receipt",
        "receipt",
        llm=get_llm() if use_llm else None,
        dayfirst=profile.date_dayfirst,
    )
    upload = store_upload(db, data, filename or "receipt", "receipt")
    receipt = Receipt(
        upload_id=upload.id,
        vendor=f.vendor,
        date=f.date,
        total=f.total,
        tax=f.tax,
        currency=f.currency or profile.currency,
        extraction_method=f.method,
        raw_text=f.raw_text or None,
    )
    db.add(receipt)
    db.flush()
    txn = find_transaction(db, receipt, get_settings().receipt_match_days)
    if txn:
        receipt.transaction_id = txn.id
    db.commit()
    return receipt, f


def find_invoice_number(db: Session, number: str | None) -> Invoice | None:
    if not number:
        return None
    return db.scalar(select(Invoice).where(func.lower(Invoice.number) == number.lower()))


def ingest_invoice(
    db: Session,
    data: bytes,
    filename: str,
    *,
    use_llm: bool = True,
    payment_terms_days: int = 30,
) -> tuple[Invoice, DocumentFields, list[str]]:
    """Read a sales invoice and add it to the tracker. Raises ValueError / DuplicateInvoiceError."""
    profile = get_profile(db)
    f = extract_document(
        data,
        filename or "invoice",
        "invoice",
        llm=get_llm() if use_llm else None,
        dayfirst=profile.date_dayfirst,
    )
    if f.total is None:
        raise ValueError("Could not read the invoice total. Add it manually instead.")
    existing = find_invoice_number(db, f.number)
    if existing:
        raise DuplicateInvoiceError(f.number or "", existing.id)

    issue = f.date or dt.date.today()
    due = f.due_date if f.due_date and f.due_date >= issue else None
    warnings = list(f.warnings)
    if due is None:
        due = issue + dt.timedelta(days=payment_terms_days)
        warnings.append(f"No due date found; assumed {payment_terms_days}-day terms.")
    if not f.client:
        warnings.append("Client name not found — please edit the invoice.")

    upload = store_upload(db, data, filename or "invoice", "invoice")
    inv = Invoice(
        number=f.number,
        client=f.client or "Unknown client",
        client_email=f.client_email,
        issue_date=issue,
        due_date=due,
        amount=f.total,
        tax=f.tax,
        currency=f.currency or profile.currency,
        status="unpaid",
        upload_id=upload.id,
    )
    db.add(inv)
    db.commit()
    match_payments(db)
    db.refresh(inv)
    return inv, f, warnings


@dataclass
class DemoResult:
    transactions: int = 0
    invoices: int = 0
    receipts: int = 0
    skipped: list[str] = field(default_factory=list)


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


def load_demo(db: Session, sample_dir: Path = SAMPLE_DIR) -> DemoResult:
    """Import the demo café (statement, invoices, receipts). Safe to run twice."""
    if not (sample_dir / "bank_statement_cafe.csv").exists():
        raise FileNotFoundError("Demo data not found (sample_data/ is missing).")
    out = DemoResult()
    st = ingest_statement(
        db, (sample_dir / "bank_statement_cafe.csv").read_bytes(), "bank_statement_cafe.csv",
        use_llm=False,
    )  # fmt: skip
    out.transactions = st.result.imported
    for path in sorted((sample_dir / "invoices").glob("*.pdf")):
        try:
            ingest_invoice(db, path.read_bytes(), path.name, use_llm=False)
            out.invoices += 1
        except DuplicateInvoiceError:
            out.skipped.append(path.name)
    for path in sorted((sample_dir / "receipts").glob("*")):
        if path.suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg"):
            continue
        receipt, _ = ingest_receipt(db, path.read_bytes(), path.name, use_llm=False)
        out.receipts += 1
    return out


def reset_books(db: Session) -> dict[str, int]:
    """Delete all transactions, invoices, receipts, rules and uploaded files.
    Categories and the business profile are kept."""
    from ..models import CategoryRule, Transaction

    counts = {}
    paths = [u.stored_path for u in db.scalars(select(Upload))]
    for name, model in (
        ("receipts", Receipt),
        ("invoices", Invoice),
        ("transactions", Transaction),
        ("uploads", Upload),
        ("rules", CategoryRule),
    ):
        counts[name] = db.query(model).delete(synchronize_session=False)
    db.commit()
    for p in paths:
        with contextlib.suppress(OSError):
            Path(p).unlink(missing_ok=True)
    return counts
