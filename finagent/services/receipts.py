"""Link receipts to the bank transactions they explain."""

from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Receipt, Transaction


def _words(text: str | None) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", (text or "").lower()))


def find_transaction(db: Session, receipt: Receipt, window_days: int) -> Transaction | None:
    """Same amount (money out), within ±window days, not already linked; vendor name breaks ties."""
    if receipt.total is None:
        return None
    q = select(Transaction).where(Transaction.amount == -receipt.total)
    if receipt.date:
        q = q.where(
            Transaction.date >= receipt.date - dt.timedelta(days=1),  # card may post next day
            Transaction.date <= receipt.date + dt.timedelta(days=window_days),
        )
    linked = set(
        db.scalars(select(Receipt.transaction_id).where(Receipt.transaction_id.is_not(None)))
    )
    candidates = [t for t in db.scalars(q) if t.id not in linked]
    if not candidates:
        return None
    vendor = _words(receipt.vendor)

    def rank(t: Transaction) -> tuple[int, int]:
        overlap = len(vendor & _words(t.description))
        gap = abs((t.date - receipt.date).days) if receipt.date else 0
        return (-overlap, gap)

    candidates.sort(key=rank)
    if not receipt.date and len(candidates) > 1 and rank(candidates[0]) == rank(candidates[1]):
        return None  # too ambiguous without a date
    return candidates[0]


def match_unlinked_receipts(db: Session, window_days: int) -> int:
    n = 0
    for r in db.scalars(select(Receipt).where(Receipt.transaction_id.is_(None))):
        t = find_transaction(db, r, window_days)
        if t:
            r.transaction_id = t.id
            db.flush()
            n += 1
    if n:
        db.commit()
    return n
