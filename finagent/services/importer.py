"""Persist parsed transactions: dedupe, categorize, save."""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..ingest.common import ParsedTxn
from ..models import Category, CategoryRule, Transaction
from .business import get_profile
from .categorizer import Categorizer, TxnInput
from .llm import get_llm

log = logging.getLogger(__name__)


@dataclass
class ImportResult:
    imported: int = 0
    duplicates: int = 0
    skipped: int = 0
    categorized: dict[str, int] = field(default_factory=dict)
    uncategorized: int = 0
    warnings: list[str] = field(default_factory=list)


def fingerprint(txn: ParsedTxn, account: str | None, occurrence: int) -> str:
    """Stable id for a statement line. `occurrence` keeps genuine same-day repeats
    (two identical coffees) while making a re-import of the same file a no-op."""
    raw = "|".join(
        [
            txn.date.isoformat(),
            " ".join(txn.description.lower().split()),
            f"{txn.amount:.2f}",
            (account or "").lower(),
            str(occurrence),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def build_categorizer(db: Session, use_llm: bool = True) -> Categorizer:
    settings = get_settings()
    categories = list(db.scalars(select(Category)))
    rules = list(db.scalars(select(CategoryRule)))
    llm = get_llm(settings) if use_llm else None
    return Categorizer(categories, rules, llm, settings.llm_batch_size)


def import_transactions(
    db: Session,
    rows: Sequence[ParsedTxn],
    *,
    account: str | None = None,
    upload_id: int | None = None,
    use_llm: bool = True,
    categorizer: Categorizer | None = None,
) -> ImportResult:
    currency = get_profile(db).currency
    result = ImportResult()

    seen: Counter[tuple] = Counter()
    candidates: list[tuple[str, ParsedTxn]] = []
    for row in rows:
        k = (row.date, " ".join(row.description.lower().split()), row.amount)
        fp = fingerprint(row, account, seen[k])
        seen[k] += 1
        candidates.append((fp, row))

    existing: set[str] = set()
    fps = [fp for fp, _ in candidates]
    for i in range(0, len(fps), 500):
        existing.update(
            db.scalars(
                select(Transaction.fingerprint).where(Transaction.fingerprint.in_(fps[i : i + 500]))
            )
        )

    new = [(fp, r) for fp, r in candidates if fp not in existing]
    result.duplicates = len(candidates) - len(new)
    if not new:
        return result

    cat = categorizer or build_categorizer(db, use_llm=use_llm)
    suggestions = cat.categorize(
        (TxnInput(fp, r.description, r.amount) for fp, r in new), use_llm=use_llm
    )

    counts: Counter[str] = Counter()
    for fp, r in new:
        s = suggestions.get(fp)
        db.add(
            Transaction(
                date=r.date,
                description=r.description[:500],
                amount=r.amount,
                currency=currency,
                account=account,
                upload_id=upload_id,
                fingerprint=fp,
                category_id=s.category_id if s else None,
                category_source=s.source if s else "none",
                confidence=s.confidence if s else None,
            )
        )
        counts[s.source if s else "none"] += 1

    db.commit()
    result.imported = len(new)
    result.uncategorized = counts.pop("none", 0)
    result.categorized = dict(counts)
    log.info("Imported %d transactions (%d duplicates)", result.imported, result.duplicates)
    return result


def recategorize(
    db: Session, *, only_uncategorized: bool = True, use_llm: bool = True
) -> dict[str, int]:
    """Re-run categorization. Never touches transactions a user categorized by hand."""
    q = select(Transaction).where(Transaction.category_source != "user")
    if only_uncategorized:
        q = q.where(Transaction.category_id.is_(None))
    txns = list(db.scalars(q))
    if not txns:
        return {}
    cat = build_categorizer(db, use_llm=use_llm)
    suggestions = cat.categorize(
        (TxnInput(t.id, t.description, t.amount) for t in txns), use_llm=use_llm
    )
    counts: Counter[str] = Counter()
    for t in txns:
        s = suggestions.get(t.id)
        if s:
            t.category_id, t.category_source, t.confidence = s.category_id, s.source, s.confidence
            counts[s.source] += 1
    db.commit()
    return dict(counts)
