from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Transaction
from ..schemas import (
    RecategorizeIn,
    RuleOut,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
    TransactionUpdateResult,
)
from ..services.categorizer import merchant_key
from ..services.importer import recategorize
from .rules import apply_rule, upsert_rule

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=TransactionPage)
def list_transactions(
    start: dt.date | None = None,
    end: dt.date | None = None,
    category_id: int | None = None,
    uncategorized: bool = False,
    direction: str | None = Query(default=None, pattern="^(in|out)$"),
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    filters = []
    if start:
        filters.append(Transaction.date >= start)
    if end:
        filters.append(Transaction.date <= end)
    if uncategorized:
        filters.append(Transaction.category_id.is_(None))
    elif category_id is not None:
        filters.append(Transaction.category_id == category_id)
    if direction == "in":
        filters.append(Transaction.amount > 0)
    elif direction == "out":
        filters.append(Transaction.amount < 0)
    if search:
        like = f"%{search.strip()}%"
        filters.append(or_(Transaction.description.ilike(like), Transaction.notes.ilike(like)))

    total = db.scalar(select(func.count(Transaction.id)).where(*filters)) or 0
    rows = db.scalars(
        select(Transaction)
        .where(*filters)
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return TransactionPage(
        items=[TransactionOut.from_model(t) for t in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{txn_id}", response_model=TransactionOut)
def get_transaction(txn_id: int, db: Session = Depends(get_db)):
    t = db.get(Transaction, txn_id)
    if t is None:
        raise HTTPException(404, "Transaction not found")
    return TransactionOut.from_model(t)


@router.patch("/{txn_id}", response_model=TransactionUpdateResult)
def update_transaction(txn_id: int, body: TransactionUpdate, db: Session = Depends(get_db)):
    t = db.get(Transaction, txn_id)
    if t is None:
        raise HTTPException(404, "Transaction not found")
    data = body.model_dump(exclude_unset=True)

    rule = None
    also_updated = 0
    if "category_id" in data:
        cid = data["category_id"]
        if cid is not None and db.get(Category, cid) is None:
            raise HTTPException(404, "Category not found")
        t.category_id = cid
        t.category_source = "user" if cid is not None else "none"
        t.confidence = 1.0 if cid is not None else None
        if body.remember and cid is not None:
            key = merchant_key(t.description)
            if len(key) >= 3:
                rule = upsert_rule(db, key, cid)
                also_updated = apply_rule(db, rule, exclude_id=t.id)
    if "notes" in data:
        t.notes = data["notes"]

    db.commit()
    db.refresh(t)
    return TransactionUpdateResult(
        transaction=TransactionOut.from_model(t),
        rule_created=RuleOut.model_validate(rule) if rule else None,
        also_updated=also_updated,
    )


@router.post("/recategorize")
def run_recategorize(body: RecategorizeIn, db: Session = Depends(get_db)):
    return {"updated": recategorize(db, **body.model_dump())}
