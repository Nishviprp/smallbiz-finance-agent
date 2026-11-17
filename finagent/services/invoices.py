"""Unpaid invoice tracking: payment matching, due-date alerts, aging."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Invoice, Transaction

AGING_BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")


def effective_status(inv: Invoice, today: dt.date) -> str:
    """'overdue' is derived, never stored, so it is always correct for today."""
    if inv.status == "unpaid" and inv.due_date < today:
        return "overdue"
    return inv.status


def aging_bucket(inv: Invoice, today: dt.date) -> str:
    days = (today - inv.due_date).days
    if days <= 0:
        return "current"
    if days <= 30:
        return "1-30"
    if days <= 60:
        return "31-60"
    if days <= 90:
        return "61-90"
    return "90+"


def _tokens(text: str | None) -> set[str]:
    stop = {"ltd", "limited", "inc", "llc", "plc", "the", "and", "co", "company", "group"}
    return {t for t in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if t not in stop}


def _score(inv: Invoice, txn: Transaction) -> int:
    desc = txn.description.lower()
    score = 0
    if inv.number and inv.number.lower() in desc:
        score += 3
    if _tokens(inv.client) & _tokens(txn.description):
        score += 2
    return score


def match_payments(db: Session) -> int:
    """Mark unpaid invoices as paid when an incoming bank transaction matches.

    A match needs the exact gross amount, a date on/after (issue date - 3 days), and the
    transaction must not already pay another invoice. If several transactions qualify, the
    invoice number / client name in the description decides; otherwise we leave it for review.
    """
    unpaid = list(db.scalars(select(Invoice).where(Invoice.status == "unpaid")))
    if not unpaid:
        return 0
    used = set(
        db.scalars(select(Invoice.transaction_id).where(Invoice.transaction_id.is_not(None)))
    )
    matched = 0
    for inv in sorted(unpaid, key=lambda i: i.issue_date):
        candidates = [
            t
            for t in db.scalars(
                select(Transaction).where(
                    Transaction.amount == inv.amount,
                    Transaction.date >= inv.issue_date - dt.timedelta(days=3),
                )
            )
            if t.id not in used
        ]
        if not candidates:
            continue
        scored = sorted(
            candidates, key=lambda t: (-_score(inv, t), abs((t.date - inv.due_date).days))
        )
        best = scored[0]
        top = _score(inv, best)
        ambiguous = len(scored) > 1 and _score(inv, scored[1]) == top
        if top == 0 and len(scored) > 1:
            continue  # several same-amount payments, nothing tells them apart
        if ambiguous and top > 0:
            continue
        inv.status, inv.paid_date, inv.transaction_id = "paid", best.date, best.id
        used.add(best.id)
        matched += 1
    if matched:
        db.commit()
    return matched


@dataclass
class AlertItem:
    invoice_id: int
    number: str | None
    client: str
    amount: Decimal
    due_date: dt.date
    days: int  # overdue: days late; due_soon: days left


@dataclass
class InvoiceAlerts:
    today: dt.date
    overdue: list[AlertItem] = field(default_factory=list)
    due_soon: list[AlertItem] = field(default_factory=list)
    total_outstanding: Decimal = Decimal("0")
    total_overdue: Decimal = Decimal("0")
    aging: dict[str, Decimal] = field(default_factory=dict)


def invoice_alerts(db: Session, today: dt.date, within_days: int) -> InvoiceAlerts:
    out = InvoiceAlerts(today=today, aging={b: Decimal("0") for b in AGING_BUCKETS})
    for inv in db.scalars(select(Invoice).where(Invoice.status == "unpaid")):
        out.total_outstanding += inv.amount
        out.aging[aging_bucket(inv, today)] += inv.amount
        days_left = (inv.due_date - today).days
        item = AlertItem(inv.id, inv.number, inv.client, inv.amount, inv.due_date, abs(days_left))
        if days_left < 0:
            out.overdue.append(item)
            out.total_overdue += inv.amount
        elif days_left <= within_days:
            out.due_soon.append(item)
    out.overdue.sort(key=lambda a: -a.days)
    out.due_soon.sort(key=lambda a: a.days)
    return out
