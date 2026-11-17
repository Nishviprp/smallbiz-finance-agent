from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Receipt, Transaction
from ..schemas import ReceiptOut, ReceiptUpdate

router = APIRouter(prefix="/receipts", tags=["receipts"])


@router.get("", response_model=list[ReceiptOut])
def list_receipts(
    unlinked: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = select(Receipt).order_by(Receipt.date.desc().nulls_last(), Receipt.id.desc())
    if unlinked:
        q = q.where(Receipt.transaction_id.is_(None))
    return db.scalars(q.limit(limit)).all()


@router.get("/{receipt_id}", response_model=ReceiptOut)
def get_receipt(receipt_id: int, db: Session = Depends(get_db)):
    return _get(db, receipt_id)


@router.patch("/{receipt_id}", response_model=ReceiptOut)
def update_receipt(receipt_id: int, body: ReceiptUpdate, db: Session = Depends(get_db)):
    r = _get(db, receipt_id)
    data = body.model_dump(exclude_unset=True)
    if (
        data.get("transaction_id") is not None
        and db.get(Transaction, data["transaction_id"]) is None
    ):
        raise HTTPException(404, "Transaction not found")
    for k, v in data.items():
        setattr(r, k, v)
    db.commit()
    return r


@router.delete("/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(receipt_id: int, db: Session = Depends(get_db)):
    db.delete(_get(db, receipt_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _get(db: Session, receipt_id: int) -> Receipt:
    r = db.get(Receipt, receipt_id)
    if r is None:
        raise HTTPException(404, "Receipt not found")
    return r
