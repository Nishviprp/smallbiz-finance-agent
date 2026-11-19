"""Bank feeds via Plaid: connect once, then transactions arrive automatically.

* Each Plaid transaction is stored with fingerprint "plaid:<transaction_id>", so re-syncs never
  duplicate, and Plaid's later edits/removals are applied to the same row.
* Pending transactions are skipped until they post.
* Lines already imported from a CSV/PDF statement (same date and amount) are not duplicated.
* Plaid's own category is used as a hint after your rules and the keyword list.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_session_factory, scope_session
from ..ingest.common import ParsedTxn, clean_text
from ..models import BankAccount, BankConnection, Transaction
from .crypto import decrypt, encrypt
from .importer import import_transactions
from .invoices import match_payments
from .plaid import PlaidClient, PlaidError, get_plaid

log = logging.getLogger(__name__)

# Plaid "personal finance category" → default category name (most specific wins).
# TRANSFER_IN/OUT are deliberately NOT mapped: client payments and owner transfers both show up
# as transfers, and guessing wrong would hide real income from profit.
PFC_HINTS: dict[str, str] = {
    "INCOME_INTEREST_EARNED": "Interest Income",
    "INCOME": "Other Income",
    "LOAN_PAYMENTS": "Loan",
    "BANK_FEES": "Bank Fees",
    "ENTERTAINMENT": "Meals & Entertainment",
    "FOOD_AND_DRINK": "Meals & Entertainment",
    "HOME_IMPROVEMENT": "Repairs & Maintenance",
    "GENERAL_SERVICES_ACCOUNTING_AND_FINANCIAL_PLANNING": "Professional Fees",
    "GENERAL_SERVICES_CONSULTING_AND_LEGAL": "Professional Fees",
    "GENERAL_SERVICES_INSURANCE": "Insurance",
    "GENERAL_SERVICES_POSTAGE_AND_SHIPPING": "Shipping & Postage",
    "GOVERNMENT_AND_NON_PROFIT_TAX_PAYMENT": "Taxes & Licenses",
    "TRANSPORTATION_GAS": "Vehicle & Fuel",
    "TRANSPORTATION_PARKING": "Vehicle & Fuel",
    "TRANSPORTATION": "Travel",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES_RENT": "Rent",
    "RENT_AND_UTILITIES_TELEPHONE": "Telephone & Internet",
    "RENT_AND_UTILITIES_INTERNET_AND_CABLE": "Telephone & Internet",
    "RENT_AND_UTILITIES_GAS_AND_ELECTRICITY": "Utilities",
    "RENT_AND_UTILITIES_WATER": "Utilities",
    "RENT_AND_UTILITIES_SEWAGE_AND_WASTE_MANAGEMENT": "Utilities",
}


def pfc_hint(txn: dict) -> str | None:
    pfc = txn.get("personal_finance_category") or {}
    for key in (pfc.get("detailed"), pfc.get("primary")):
        if key and key in PFC_HINTS:
            return PFC_HINTS[key]
    return None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


@dataclass
class SyncResult:
    connection_id: int
    institution: str
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped_duplicates: int = 0
    pending: int = 0
    invoices_paid: int = 0
    status: str = "ok"
    error: str | None = None
    categorized: dict[str, int] = field(default_factory=dict)


# ---- connect / disconnect ---------------------------------------------------------


def connect(
    db: Session,
    public_token: str,
    *,
    institution_name: str | None = None,
    plaid: PlaidClient | None = None,
    use_llm: bool = True,
) -> tuple[BankConnection, SyncResult]:
    plaid = plaid or get_plaid()
    access_token, item_id = plaid.exchange_public_token(public_token)
    existing = db.scalar(select(BankConnection).where(BankConnection.item_id == item_id))
    conn = existing or BankConnection(item_id=item_id)
    conn.access_token_enc = encrypt(access_token)
    conn.institution_name = (institution_name or plaid.institution_name(access_token) or "Bank")[
        :120
    ]
    conn.status, conn.error = "ok", None
    if existing is None:
        db.add(conn)
    db.flush()
    _refresh_accounts(db, conn, plaid, access_token)
    db.commit()
    return conn, sync_connection(db, conn, plaid=plaid, use_llm=use_llm)


def _refresh_accounts(db: Session, conn: BankConnection, plaid: PlaidClient, token: str) -> None:
    known = {a.account_id: a for a in conn.accounts}
    for acc in plaid.get_accounts(token):
        a = known.get(acc["account_id"]) or BankAccount(
            connection_id=conn.id, account_id=acc["account_id"], name="Account"
        )
        a.name = (acc.get("official_name") or acc.get("name") or "Account")[:120]
        a.mask = acc.get("mask")
        a.type, a.subtype = acc.get("type"), acc.get("subtype")
        if a.account_id not in known:
            conn.accounts.append(a)
            db.add(a)


def disconnect(db: Session, conn: BankConnection, *, plaid: PlaidClient | None = None) -> None:
    """Remove the bank link. Imported transactions stay in your books."""
    try:
        (plaid or get_plaid()).remove_item(decrypt(conn.access_token_enc))
    except PlaidError as exc:
        log.warning("Plaid item/remove failed (removing locally anyway): %s", exc)
    db.delete(conn)
    db.commit()


# ---- sync -------------------------------------------------------------------------


def _amount(txn: dict) -> Decimal:
    # Plaid: positive = money leaving the account. Ours: positive = money in.
    return -Decimal(str(txn["amount"])).quantize(Decimal("0.01"))


def _description(txn: dict) -> str:
    return clean_text(txn.get("merchant_name") or txn.get("name") or "(no description)")[:500]


def _date(txn: dict) -> dt.date:
    return dt.date.fromisoformat(txn["date"])


def sync_connection(
    db: Session,
    conn: BankConnection,
    *,
    plaid: PlaidClient | None = None,
    use_llm: bool = True,
) -> SyncResult:
    plaid = plaid or get_plaid()
    out = SyncResult(conn.id, conn.institution_name)
    try:
        token = decrypt(conn.access_token_enc)
        changes = plaid.sync_transactions(token, conn.cursor)
    except PlaidError as exc:
        conn.status = "needs_reauth" if exc.needs_reauth else "error"
        conn.error = exc.user_message
        db.commit()
        out.status, out.error = conn.status, conn.error
        return out
    except Exception as exc:  # decryption etc.
        conn.status, conn.error = "error", str(exc)
        db.commit()
        out.status, out.error = conn.status, conn.error
        return out

    labels = {a.account_id: a.label for a in conn.accounts}

    # Removed → delete
    removed_ids = [
        f"plaid:{r['transaction_id']}" for r in changes["removed"] if r.get("transaction_id")
    ]
    if removed_ids:
        out.removed = (
            db.execute(delete(Transaction).where(Transaction.fingerprint.in_(removed_ids))).rowcount
            or 0
        )

    # Modified → update in place (keep the user's category)
    for txn in changes["modified"]:
        if txn.get("pending"):
            continue
        row = db.scalar(
            select(Transaction).where(Transaction.fingerprint == f"plaid:{txn['transaction_id']}")
        )
        if row is not None:
            row.date, row.amount, row.description = _date(txn), _amount(txn), _description(txn)
            out.updated += 1

    # Added (+ modified ones we never saw) → import
    fresh = [t for t in changes["added"] + changes["modified"] if not t.get("pending")]
    out.pending = sum(1 for t in changes["added"] if t.get("pending"))
    fresh = _skip_statement_duplicates(db, fresh, out)
    if fresh:
        result = import_transactions(
            db,
            [ParsedTxn(_date(t), _description(t), _amount(t)) for t in fresh],
            fingerprints=[f"plaid:{t['transaction_id']}" for t in fresh],
            hints={f"plaid:{t['transaction_id']}": h for t in fresh if (h := pfc_hint(t))},
            accounts=[labels.get(t.get("account_id"), conn.institution_name) for t in fresh],
            use_llm=use_llm,
        )
        out.added = result.imported
        out.categorized = result.categorized

    conn.cursor = changes["cursor"]
    conn.status, conn.error = "ok", None
    conn.last_synced_at = _utcnow()
    db.commit()
    if out.added:
        out.invoices_paid = match_payments(db)
    return out


def _skip_statement_duplicates(db: Session, txns: list[dict], out: SyncResult) -> list[dict]:
    """Don't re-add lines the business already imported from a statement file."""
    if not txns:
        return txns
    dates = [_date(t) for t in txns]
    rows = db.execute(
        select(Transaction.date, Transaction.amount).where(
            Transaction.date >= min(dates),
            Transaction.date <= max(dates),
            ~Transaction.fingerprint.startswith("plaid:"),
        )
    ).all()
    available = Counter((d, Decimal(a)) for d, a in rows)
    keep = []
    for t in txns:
        key = (_date(t), _amount(t))
        already = db.scalar(
            select(Transaction.id).where(Transaction.fingerprint == f"plaid:{t['transaction_id']}")
        )
        if already is None and available[key] > 0:
            available[key] -= 1
            out.skipped_duplicates += 1
            continue
        keep.append(t)
    return keep


def sync_all(db: Session, *, use_llm: bool = True) -> list[SyncResult]:
    """Sync every connection of the business in scope."""
    return [
        sync_connection(db, c, use_llm=use_llm)
        for c in db.scalars(select(BankConnection).order_by(BankConnection.id))
    ]


def sync_due_everywhere(max_age_hours: float) -> int:
    """Background job: sync connections across ALL businesses that are older than max_age.
    Each connection is synced inside a session scoped to its own business."""
    cutoff = _utcnow() - dt.timedelta(hours=max_age_hours)
    with get_session_factory()() as db:
        db.info["global_access"] = True
        due = db.execute(
            select(BankConnection.id, BankConnection.business_id).where(
                BankConnection.status != "needs_reauth",
                (BankConnection.last_synced_at.is_(None))
                | (BankConnection.last_synced_at < cutoff),
            )
        ).all()
    synced = 0
    for conn_id, business_id in due:
        with get_session_factory()() as db:
            scope_session(db, business_id)
            conn = db.get(BankConnection, conn_id)
            if conn is not None:
                sync_connection(db, conn)
                synced += 1
    return synced
