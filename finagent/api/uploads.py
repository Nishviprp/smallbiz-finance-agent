from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..ingest.bank_csv import parse_bank_csv
from ..models import Upload
from ..schemas import ImportOut
from ..services.importer import import_transactions

router = APIRouter(prefix="/uploads", tags=["uploads"])

STATEMENT_TYPES = {".csv"}


def _read_limited(file: UploadFile, max_mb: int) -> bytes:
    data = file.file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {max_mb} MB")
    if not data:
        raise HTTPException(400, "File is empty")
    return data


def _store(data: bytes, filename: str) -> Path:
    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    safe = Path(filename or "upload").name.replace(" ", "_")[:120]
    path = settings.upload_dir / f"{uuid.uuid4().hex[:12]}_{safe}"
    path.write_bytes(data)
    return path


@router.post("/statement", response_model=ImportOut)
def upload_statement(  # sync: runs in threadpool (DB + LLM calls block)
    file: UploadFile = File(...),
    account: str | None = Form(default=None),
    use_llm: bool = Form(default=True),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in STATEMENT_TYPES:
        raise HTTPException(415, f"Unsupported statement type '{suffix}'. Supported: CSV")

    data = _read_limited(file, settings.max_upload_mb)
    try:
        parsed = parse_bank_csv(data, default_dayfirst=settings.date_dayfirst)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    path = _store(data, file.filename or "statement.csv")
    upload = Upload(filename=file.filename or path.name, stored_path=str(path), kind="statement")
    db.add(upload)
    db.flush()

    result = import_transactions(
        db, parsed.rows, account=account or None, upload_id=upload.id, use_llm=use_llm
    )
    upload.rows_imported = result.imported
    upload.rows_duplicate = result.duplicates
    upload.rows_skipped = parsed.skipped
    db.commit()

    return ImportOut(
        upload_id=upload.id,
        filename=upload.filename,
        imported=result.imported,
        duplicates=result.duplicates,
        skipped=parsed.skipped,
        categorized=result.categorized,
        uncategorized=result.uncategorized,
        warnings=parsed.warnings,
    )
