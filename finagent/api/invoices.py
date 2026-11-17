from __future__ import annotations

import datetime as dt
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Invoice, Transaction
from ..schemas import (
    InvoiceAlertsOut,
    InvoiceIn,
    InvoiceOut,
    InvoiceUpdate,
    MarkPaidIn,
)
from ..services.invoices import effective_status, invoice_alerts, match_payments

router = APIRouter(prefix="/invoices", tags=["invoices"])


def to_out(inv: Invoice, today: dt.date | None = None, **extra) -> InvoiceOut:
    today = today or dt.date.today()
    out = InvoiceOut.model_validate(inv)
    out.effective_status = effective_status(inv, today)
    out.days_overdue = max(0, (today - inv.due_date).days) if inv.status == "unpaid" else 0
    for k, v in extra.items():
        setattr(out, k, v)
    return out


@router.get("", response_model=list[InvoiceOut])
def list_invoices(
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(unpaid|overdue|paid|void|open)$"
    ),
    db: Session = Depends(get_db),
):
    today = dt.date.today()
    q = select(Invoice).order_by(Invoice.due_date)
    if status_filter in ("unpaid", "open", "overdue"):
        q = q.where(Invoice.status == "unpaid")
    elif status_filter:
        q = q.where(Invoice.status == status_filter)
    items = [to_out(i, today) for i in db.scalars(q)]
    if status_filter == "overdue":
        items = [i for i in items if i.effective_status == "overdue"]
    return items


@router.get("/alerts", response_model=InvoiceAlertsOut)
def alerts(
    days: int | None = Query(default=None, ge=0, le=365),
    today: dt.date | None = None,
    db: Session = Depends(get_db),
):
    window = days if days is not None else get_settings().invoice_alert_days
    result = invoice_alerts(db, today or dt.date.today(), window)
    return InvoiceAlertsOut.model_validate(asdict(result))


@router.post("/match")
def run_match(db: Session = Depends(get_db)):
    return {"matched": match_payments(db)}


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(body: InvoiceIn, db: Session = Depends(get_db)):
    ensure_unique_number(db, body.number)
    data = body.model_dump()
    data["due_date"] = data["due_date"] or body.issue_date + dt.timedelta(days=30)
    if data["due_date"] < body.issue_date:
        raise HTTPException(422, "Due date cannot be before the issue date")
    inv = Invoice(**data, currency=get_settings().currency, status="unpaid")
    db.add(inv)
    db.commit()
    match_payments(db)  # it may already be paid in an imported statement
    db.refresh(inv)
    return to_out(inv)


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    return to_out(_get(db, invoice_id))


@router.patch("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(invoice_id: int, body: InvoiceUpdate, db: Session = Depends(get_db)):
    inv = _get(db, invoice_id)
    data = body.model_dump(exclude_unset=True)
    if "number" in data:
        ensure_unique_number(db, data["number"], exclude_id=inv.id)
    for k, v in data.items():
        setattr(inv, k, v)
    if inv.due_date < inv.issue_date:
        raise HTTPException(422, "Due date cannot be before the issue date")
    if data.get("status") == "paid" and inv.paid_date is None:
        inv.paid_date = dt.date.today()
    if data.get("status") in ("unpaid", "void"):
        inv.paid_date, inv.transaction_id = None, None
    db.commit()
    return to_out(inv)


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceOut)
def mark_paid(invoice_id: int, body: MarkPaidIn, db: Session = Depends(get_db)):
    inv = _get(db, invoice_id)
    paid_date = body.paid_date
    if body.transaction_id is not None:
        txn = db.get(Transaction, body.transaction_id)
        if txn is None:
            raise HTTPException(404, "Transaction not found")
        inv.transaction_id = txn.id
        paid_date = paid_date or txn.date
    inv.status, inv.paid_date = "paid", paid_date or dt.date.today()
    db.commit()
    return to_out(inv)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, invoice_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def ensure_unique_number(db: Session, number: str | None, exclude_id: int | None = None) -> None:
    if not number:
        return
    existing = db.scalar(select(Invoice).where(func.lower(Invoice.number) == number.lower()))
    if existing and existing.id != exclude_id:
        raise HTTPException(409, f"Invoice {number} already exists (id {existing.id})")


def _get(db: Session, invoice_id: int) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    return inv
