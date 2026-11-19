"""Financial reports: KPIs, monthly P&L / cash flow, top expenses, category trends.

Definitions (cash basis, which is how most micro-businesses report):
  * Income   = money in categorized as an income category (+ uncategorized money in)
  * Expenses = money out categorized as an expense category (+ uncategorized money out);
               refunds in an expense category reduce that category.
  * Transfers / owner drawings / loans move cash but are NOT profit or loss.
  * Net profit = income - expenses.  Net cash = everything in - everything out.
Aggregation is done in Python so the same code runs on SQLite and Postgres.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Category, Invoice, Transaction
from .categorizer import merchant_key, pretty_merchant

ZERO = Decimal("0")
UNCAT_IN = "Uncategorized income"
UNCAT_OUT = "Uncategorized expenses"


@dataclass(frozen=True)
class Row:
    date: dt.date
    amount: Decimal
    category: str
    kind: str  # income | expense | transfer
    description: str


def month_key(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def months_between(start: dt.date, end: dt.date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def data_range(db: Session) -> tuple[dt.date, dt.date] | None:
    lo, hi = db.execute(select(func.min(Transaction.date), func.max(Transaction.date))).one()
    return (lo, hi) if lo else None


def resolve_period(
    db: Session, start: dt.date | None, end: dt.date | None
) -> tuple[dt.date, dt.date] | None:
    rng = data_range(db)
    if rng is None and (start is None or end is None):
        return None
    start = start or rng[0]  # type: ignore[index]
    end = end or rng[1]  # type: ignore[index]
    if end < start:
        start, end = end, start
    return start, end


def load_rows(db: Session, start: dt.date, end: dt.date) -> list[Row]:
    cats = {c.id: c for c in db.scalars(select(Category))}
    rows: list[Row] = []
    q = select(
        Transaction.date, Transaction.amount, Transaction.category_id, Transaction.description
    ).where(Transaction.date >= start, Transaction.date <= end)
    for date, amount, cid, desc in db.execute(q):
        amount = Decimal(amount)
        cat = cats.get(cid) if cid is not None else None
        if cat is None:
            name, kind = (UNCAT_IN, "income") if amount > 0 else (UNCAT_OUT, "expense")
        else:
            name, kind = cat.name, cat.kind
        rows.append(Row(date, amount, name, kind, desc))
    return rows


# ---- Summary / KPIs ---------------------------------------------------------


@dataclass
class Totals:
    income: Decimal = ZERO
    expenses: Decimal = ZERO
    cash_in: Decimal = ZERO
    cash_out: Decimal = ZERO

    @property
    def net_profit(self) -> Decimal:
        return self.income - self.expenses

    @property
    def net_cash(self) -> Decimal:
        return self.cash_in - self.cash_out

    def add(self, r: Row) -> None:
        if r.amount > 0:
            self.cash_in += r.amount
        else:
            self.cash_out += -r.amount
        if r.kind == "income":
            self.income += r.amount
        elif r.kind == "expense":
            self.expenses += -r.amount


def totals(rows: list[Row]) -> Totals:
    t = Totals()
    for r in rows:
        t.add(r)
    return t


def _pct_change(cur: Decimal, prev: Decimal) -> float | None:
    if prev == 0:
        return None
    return float((cur - prev) / abs(prev) * 100)


def summary(db: Session, start: dt.date, end: dt.date, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    rows = load_rows(db, start, end)
    t = totals(rows)

    # Same-length window immediately before, for deltas on the KPI tiles.
    length = (end - start).days + 1
    prev_end = start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=length - 1)
    p = totals(load_rows(db, prev_start, prev_end))
    has_prev = p.cash_in or p.cash_out

    n_months = max(1, len(months_between(start, end)))
    uncategorized = [r for r in rows if r.category in (UNCAT_IN, UNCAT_OUT)]
    unpaid = list(db.scalars(select(Invoice).where(Invoice.status == "unpaid")))

    return {
        "start": start,
        "end": end,
        "income": t.income,
        "expenses": t.expenses,
        "net_profit": t.net_profit,
        "profit_margin_pct": float(t.net_profit / t.income * 100) if t.income > 0 else None,
        "cash_in": t.cash_in,
        "cash_out": t.cash_out,
        "net_cash": t.net_cash,
        "avg_monthly_income": t.income / n_months,
        "avg_monthly_expenses": t.expenses / n_months,
        "transaction_count": len(rows),
        "uncategorized_count": len(uncategorized),
        "uncategorized_amount": sum((abs(r.amount) for r in uncategorized), ZERO),
        "outstanding_invoices": sum((i.amount for i in unpaid), ZERO),
        "overdue_invoices": sum((i.amount for i in unpaid if i.due_date < today), ZERO),
        "overdue_count": sum(1 for i in unpaid if i.due_date < today),
        "previous": {
            "start": prev_start,
            "end": prev_end,
            "income": p.income,
            "expenses": p.expenses,
            "net_profit": p.net_profit,
        }
        if has_prev
        else None,
        "change_pct": {
            "income": _pct_change(t.income, p.income),
            "expenses": _pct_change(t.expenses, p.expenses),
            "net_profit": _pct_change(t.net_profit, p.net_profit),
        }
        if has_prev
        else None,
    }


# ---- Monthly ----------------------------------------------------------------


def monthly(db: Session, start: dt.date, end: dt.date) -> list[dict]:
    per: dict[str, Totals] = {m: Totals() for m in months_between(start, end)}
    for r in load_rows(db, start, end):
        per[month_key(r.date)].add(r)
    out, running = [], ZERO
    for m, t in per.items():
        running += t.net_cash
        out.append(
            {
                "month": m,
                "income": t.income,
                "expenses": t.expenses,
                "net_profit": t.net_profit,
                "cash_in": t.cash_in,
                "cash_out": t.cash_out,
                "net_cash": t.net_cash,
                "cumulative_net_cash": running,
            }
        )
    return out


# ---- P&L --------------------------------------------------------------------


def pnl(db: Session, start: dt.date, end: dt.date) -> dict:
    months = months_between(start, end)
    grid: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: {m: ZERO for m in months})
    transfers = ZERO
    for r in load_rows(db, start, end):
        if r.kind == "transfer":
            transfers += r.amount
            continue
        sign = 1 if r.kind == "income" else -1
        grid[(r.kind, r.category)][month_key(r.date)] += sign * r.amount

    def section(kind: str) -> list[dict]:
        lines = [
            {"category": name, "total": sum(vals.values(), ZERO), "by_month": vals}
            for (k, name), vals in grid.items()
            if k == kind
        ]
        return sorted(lines, key=lambda x: -x["total"])

    inc, exp = section("income"), section("expense")
    ti = sum((x["total"] for x in inc), ZERO)
    te = sum((x["total"] for x in exp), ZERO)
    return {
        "start": start,
        "end": end,
        "months": months,
        "income": inc,
        "expenses": exp,
        "total_income": ti,
        "total_expenses": te,
        "net_profit": ti - te,
        "net_transfers": transfers,
    }


# ---- Top expenses & trends --------------------------------------------------


def top_expenses(db: Session, start: dt.date, end: dt.date, limit: int = 10) -> dict:
    by_cat: dict[str, Decimal] = defaultdict(lambda: ZERO)
    by_merchant: dict[str, Decimal] = defaultdict(lambda: ZERO)
    count: dict[str, int] = defaultdict(int)
    total = ZERO
    for r in load_rows(db, start, end):
        if r.kind != "expense":
            continue
        spend = -r.amount
        total += spend
        by_cat[r.category] += spend
        key = pretty_merchant(merchant_key(r.description) or r.description[:30].lower())
        by_merchant[key] += spend
        count[key] += 1

    def ranked(d: dict[str, Decimal], label: str) -> list[dict]:
        items = sorted(d.items(), key=lambda kv: -kv[1])[:limit]
        return [
            {
                label: k,
                "total": v,
                "share_pct": float(v / total * 100) if total else 0.0,
                **({"count": count[k]} if label == "merchant" else {}),
            }
            for k, v in items
            if v > 0
        ]

    return {
        "total_expenses": total,
        "categories": ranked(by_cat, "category"),
        "merchants": ranked(by_merchant, "merchant"),
    }


def category_trends(
    db: Session, start: dt.date, end: dt.date, kind: str = "expense", top: int = 5
) -> dict:
    """Monthly totals for the top-N categories + 'Other'. Series order is by total over the
    whole data range (not the filter), so a category keeps its color when the filter changes."""
    months = months_between(start, end)
    full = data_range(db)
    ranking_rows = load_rows(db, *full) if full else []
    rank: dict[str, Decimal] = defaultdict(lambda: ZERO)
    sign = 1 if kind == "income" else -1
    for r in ranking_rows:
        if r.kind == kind:
            rank[r.category] += sign * r.amount
    leaders = [c for c, _ in sorted(rank.items(), key=lambda kv: -kv[1])[:top]]

    series: dict[str, dict[str, Decimal]] = {c: {m: ZERO for m in months} for c in leaders}
    other = {m: ZERO for m in months}
    for r in load_rows(db, start, end):
        if r.kind != kind:
            continue
        target = series.get(r.category, other)
        target[month_key(r.date)] += sign * r.amount
    out = [{"category": c, "values": [series[c][m] for m in months]} for c in leaders]
    if any(other.values()):
        out.append({"category": "Other", "values": [other[m] for m in months]})
    return {"months": months, "kind": kind, "series": out}
