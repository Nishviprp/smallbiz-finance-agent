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
from .categorizer import Categorizer, Suggestion, TxnInput, sign_ok
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
    fingerprints: Sequence[str] | None = None,
    hints: dict[str, str] | None = None,
    accounts: Sequence[str | None] | None = None,
) -> ImportResult:
    """Save new rows. `fingerprints` (e.g. "plaid:<id>") override the computed ones;
    `hints` maps fingerprint -> category name suggested by the bank (used after rules and
    keywords, before the LLM); `accounts` gives a per-row account label."""
    currency = get_profile(db).currency
    result = ImportResult()

    seen: Counter[tuple] = Counter()
    candidates: list[tuple[str, ParsedTxn, str | None]] = []
    for i, row in enumerate(rows):
        acct = accounts[i] if accounts is not None else account
        if fingerprints is not None:
            fp = fingerprints[i]
        else:
            k = (row.date, " ".join(row.description.lower().split()), row.amount)
            fp = fingerprint(row, account, seen[k])
            seen[k] += 1
        candidates.append((fp, row, acct))

    existing: set[str] = set()
    fps = [fp for fp, _, _ in candidates]
    for i in range(0, len(fps), 500):
        existing.update(
            db.scalars(
                select(Transaction.fingerprint).where(Transaction.fingerprint.in_(fps[i : i + 500]))
            )
        )

    new = [(fp, r, a) for fp, r, a in candidates if fp not in existing]
    result.duplicates = len(candidates) - len(new)
    if not new:
        return result

    cat = categorizer or build_categorizer(db, use_llm=use_llm)
    items = [TxnInput(fp, r.description, r.amount) for fp, r, _ in new]
    suggestions = cat.categorize(items, use_llm=False)  # rules + keywords
    if hints:
        by_name = {c.name.lower(): c for c in cat.categories.values()}
        for t in items:
            name = hints.get(t.key)
            c = by_name.get(name.lower()) if name else None
            if t.key not in suggestions and c is not None and sign_ok(c.kind, t.amount):
                suggestions[t.key] = Suggestion(c.id, "bank", 0.8)
    if use_llm:
        suggestions.update(cat.classify_llm([t for t in items if t.key not in suggestions]))

    counts: Counter[str] = Counter()
    for fp, r, acct in new:
        s = suggestions.get(fp)
        db.add(
            Transaction(
                date=r.date,
                description=r.description[:500],
                amount=r.amount,
                currency=currency,
                account=acct,
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
