"""Chat with your books.

Safety and accuracy by design:
  * The LLM never writes SQL or touches the database. It only picks one of a few read-only
    tools (+ arguments); our code computes every number.
  * The LLM then phrases the answer from that data only. A template answer built from the
    same data is used whenever no LLM is configured or the LLM fails.
  * Without any LLM, a rule-based router answers the common questions, so chat works offline.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from ..models import Category, Invoice, Transaction
from . import analytics
from .dates import fmt_date, use_dayfirst
from .llm import LLMClient, LLMError, extract_json
from .periods import MONTHS, parse_period

log = logging.getLogger(__name__)
ZERO = Decimal("0")

TOOLS: dict[str, str] = {
    "summary": "Income, expenses, net profit, margin and cash flow for a period.",
    "category_total": "Total, count and monthly breakdown for ONE category. Args: category.",
    "search": "Transactions whose description contains text (a supplier, client, keyword). "
    "Args: text, direction ('in'|'out'|null).",
    "top_expenses": "Biggest expense categories and suppliers in a period.",
    "monthly": "Month-by-month income, expenses and net profit.",
    "invoices": "Unpaid / overdue / paid sales invoices. Args: status ('open'|'overdue'|'paid').",
    "uncategorized": "Transactions that still need a category.",
}

# Plain-English words → default category names
SYNONYMS: dict[str, tuple[str, ...]] = {
    "Payroll": ("wages", "wage", "salary", "salaries", "staff", "payroll", "paye"),
    "Cost of Goods Sold": ("stock", "ingredients", "supplies", "inventory", "cogs", "suppliers"),
    "Software & Subscriptions": ("software", "subscriptions", "subscription", "saas", "apps"),
    "Marketing & Advertising": ("marketing", "advertising", "ads", "adverts", "promotion"),
    "Utilities": ("utilities", "electricity", "energy", "gas", "water", "power"),
    "Telephone & Internet": ("phone", "internet", "broadband", "mobile"),
    "Bank Fees": ("bank fees", "bank charges", "fees"),
    "Taxes & Licenses": ("tax", "taxes", "vat", "hmrc", "irs", "licence", "license", "rates"),
    "Vehicle & Fuel": ("fuel", "petrol", "diesel", "parking", "car", "van"),
    "Shipping & Postage": ("postage", "shipping", "delivery", "courier"),
    "Repairs & Maintenance": ("repairs", "repair", "maintenance", "cleaning"),
    "Sales": ("takings", "card sales", "sales"),
    "Meals & Entertainment": ("meals", "entertainment", "lunch", "dinner"),
}


@dataclass
class ChatTurn:
    role: str  # user | assistant
    content: str
    tool: str | None = None  # assistant turns: which tool answered (for follow-ups)
    args: dict | None = None


@dataclass
class ChatResult:
    answer: str
    tool: str
    args: dict = field(default_factory=dict)
    data: Any = None
    method: str = "rules"  # ai | rules
    start: dt.date | None = None
    end: dt.date | None = None


# ---- helpers --------------------------------------------------------------------


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


_SYM = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹", "CAD": "$", "AUD": "$"}


class Fmt:
    def __init__(self, currency: str):
        self.sym = _SYM.get(currency, "")
        self.code = currency

    def m(self, v: Decimal | float) -> str:
        v = Decimal(str(v))
        body = f"{abs(v):,.0f}" if abs(v) >= 1000 else f"{abs(v):,.2f}"
        s = f"{self.sym}{body}" if self.sym else f"{body} {self.code}"
        return f"-{s}" if v < 0 else s


def _d(d: dt.date) -> str:
    return fmt_date(d)


def _span(start: dt.date, end: dt.date) -> str:
    return f"{_d(start)} – {_d(end)}"


# ---- tools ----------------------------------------------------------------------


class Books:
    """Read-only query tools over the ledger."""

    def __init__(self, db: Session, currency: str, today: dt.date | None = None):
        self.db = db
        self.f = Fmt(currency)
        self.today = today or dt.date.today()
        rng = analytics.data_range(db)
        self.first, self.last = rng if rng else (self.today, self.today)
        self.has_data = rng is not None
        self.categories = list(db.scalars(select(Category)))

    def find_category(self, text: str) -> Category | None:
        t = f" {text.lower()} "
        by_name = {c.name.lower(): c for c in self.categories}
        # 1. full category name in text (longest first: "bank fees" before "fees")
        for name in sorted(by_name, key=len, reverse=True):
            if re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", t):
                return by_name[name]
        # 2. synonyms
        hits = []
        for cname, words in SYNONYMS.items():
            for w in words:
                if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", t) and cname.lower() in by_name:
                    hits.append((len(w), by_name[cname.lower()]))
        if hits:
            return max(hits, key=lambda h: h[0])[1]
        return None

    def resolve_category(self, name: str) -> Category | None:
        """For LLM output: exact, then fuzzy."""
        by_name = {c.name.lower(): c for c in self.categories}
        key = (name or "").strip().lower()
        if key in by_name:
            return by_name[key]
        close = difflib.get_close_matches(key, list(by_name), n=1, cutoff=0.6)
        return by_name[close[0]] if close else self.find_category(key)

    # Each tool returns (data, template_answer)

    def summary(self, start: dt.date, end: dt.date) -> tuple[dict, str]:
        s = analytics.summary(self.db, start, end, today=self.today)
        f = self.f
        margin = s["profit_margin_pct"]
        text = (
            f"From {_span(start, end)} you brought in {f.m(s['income'])} and spent "
            f"{f.m(s['expenses'])}, so net profit was **{f.m(s['net_profit'])}**"
            + (f" ({margin:.0f}% margin)." if margin is not None else ".")
            + f" Cash flow after transfers was {f.m(s['net_cash'])}."
        )
        if s["uncategorized_count"]:
            text += f" ({s['uncategorized_count']} transactions are still uncategorized.)"
        return s, text

    def category_total(self, category: Category, start: dt.date, end: dt.date) -> tuple[dict, str]:
        q = select(Transaction).where(
            Transaction.category_id == category.id,
            Transaction.date >= start,
            Transaction.date <= end,
        )
        txns = list(self.db.scalars(q))
        sign = 1 if category.kind == "income" else -1
        total = sum((sign * Decimal(t.amount) for t in txns), ZERO)
        by_month: Counter[str] = Counter()
        for t in txns:
            by_month[analytics.month_key(t.date)] += float(sign * Decimal(t.amount))
        data = {
            "category": category.name,
            "kind": category.kind,
            "total": total,
            "count": len(txns),
            "by_month": dict(sorted(by_month.items())),
        }
        f = self.f
        if not txns:
            return data, f"Nothing in **{category.name}** between {_span(start, end)}."
        verb = "brought in" if category.kind == "income" else "went on"
        text = (
            f"**{f.m(total)}** {verb} {category.name} between {_span(start, end)}, "
            f"across {len(txns)} transaction{'s' if len(txns) != 1 else ''} "
            f"(average {f.m(total / len(txns))})."
        )
        if len(by_month) > 1:
            top_m, top_v = max(by_month.items(), key=lambda kv: kv[1])
            text += f" Highest month: {analytics_month(top_m)} ({f.m(top_v)})."
        return data, text

    def search(
        self, text: str, start: dt.date, end: dt.date, direction: str | None = None
    ) -> tuple[dict, str]:
        words = [_stem(w) for w in re.findall(r"[a-z0-9&]+", text.lower()) if len(w) > 1]
        conds = [Transaction.description.ilike(f"%{w}%") for w in words] or [false()]
        q = select(Transaction).where(Transaction.date >= start, Transaction.date <= end, *conds)
        if direction == "in":
            q = q.where(Transaction.amount > 0)
        elif direction == "out":
            q = q.where(Transaction.amount < 0)
        txns = list(self.db.scalars(q.order_by(Transaction.date.desc())))
        out = sum((-Decimal(t.amount) for t in txns if t.amount < 0), ZERO)
        inn = sum((Decimal(t.amount) for t in txns if t.amount > 0), ZERO)
        data = {
            "query": text,
            "count": len(txns),
            "money_out": out,
            "money_in": inn,
            "transactions": [
                {
                    "date": t.date,
                    "description": t.description,
                    "amount": Decimal(t.amount),
                    "category": t.category.name if t.category else None,
                }
                for t in txns[:25]
            ],
        }
        f = self.f
        if not txns:
            return (
                data,
                f"I couldn't find any transactions matching “{text}” between {_span(start, end)}.",
            )
        parts = []
        if out:
            parts.append(f"**{f.m(out)} paid out**")
        if inn:
            parts.append(f"**{f.m(inn)} received**")
        biggest = max(txns, key=lambda t: abs(t.amount))
        return data, (
            f"{len(txns)} transaction{'s' if len(txns) != 1 else ''} match “{text}” between "
            f"{_span(start, end)}: {' and '.join(parts)}. Largest: {f.m(abs(biggest.amount))} on "
            f"{_d(biggest.date)} ({biggest.description})."
        )

    def top_expenses(self, start: dt.date, end: dt.date, limit: int = 5) -> tuple[dict, str]:
        top = analytics.top_expenses(self.db, start, end, limit=limit)
        f = self.f
        if not top["categories"]:
            return top, f"No expenses recorded between {_span(start, end)}."
        items = "; ".join(
            f"{i}. {c['category']} {f.m(c['total'])} ({c['share_pct']:.0f}%)"
            for i, c in enumerate(top["categories"], 1)
        )
        sup = top["merchants"][0]
        return top, (
            f"Your biggest costs between {_span(start, end)} (total {f.m(top['total_expenses'])}): "
            f"{items}. Largest single supplier: {sup['merchant']} ({f.m(sup['total'])})."
        )

    def monthly(self, start: dt.date, end: dt.date) -> tuple[list, str]:
        rows = analytics.monthly(self.db, start, end)
        f = self.f
        if not rows:
            return rows, "No data for that period."
        parts = ", ".join(f"{analytics_month(r['month'])} {f.m(r['net_profit'])}" for r in rows)
        best = max(rows, key=lambda r: r["net_profit"])
        worst = min(rows, key=lambda r: r["net_profit"])
        text = f"Net profit by month: {parts}."
        if len(rows) > 1:
            text += (
                f" Best: {analytics_month(best['month'])}; weakest: "
                f"{analytics_month(worst['month'])}."
            )
        return rows, text

    def invoices(self, status: str = "open") -> tuple[dict, str]:
        q = select(Invoice).order_by(Invoice.due_date)
        if status in ("open", "overdue"):
            q = q.where(Invoice.status == "unpaid")
        elif status == "paid":
            q = q.where(Invoice.status == "paid")
        invs = list(self.db.scalars(q))
        if status == "overdue":
            invs = [i for i in invs if i.due_date < self.today]
        f = self.f
        data = {
            "status": status,
            "count": len(invs),
            "total": sum((i.amount for i in invs), ZERO),
            "invoices": [
                {
                    "number": i.number,
                    "client": i.client,
                    "amount": i.amount,
                    "due_date": i.due_date,
                    "days_overdue": max(0, (self.today - i.due_date).days)
                    if i.status == "unpaid"
                    else 0,
                    "status": i.status,
                }
                for i in invs
            ],
        }
        if not invs:
            return data, {
                "overdue": "Nothing is overdue. 🎉",
                "paid": "No paid invoices recorded yet.",
            }.get(status, "You have no unpaid invoices.")
        if status == "paid":
            return data, f"{len(invs)} paid invoice(s), totalling {f.m(data['total'])}."
        overdue = [i for i in invs if i.due_date < self.today]
        text = f"You're owed **{f.m(data['total'])}** across {len(invs)} unpaid invoice(s)."
        if overdue:
            worst = max(overdue, key=lambda i: (self.today - i.due_date).days)
            text += (
                f" {len(overdue)} overdue — the oldest is {worst.number or 'an invoice'} to "
                f"{worst.client} for {f.m(worst.amount)}, {(self.today - worst.due_date).days} days late."
            )
        return data, text

    def uncategorized(self, start: dt.date, end: dt.date) -> tuple[dict, str]:
        q = select(Transaction).where(
            Transaction.category_id.is_(None), Transaction.date >= start, Transaction.date <= end
        )
        txns = list(self.db.scalars(q))
        common = Counter(t.description for t in txns).most_common(5)
        data = {
            "count": len(txns),
            "total": sum((abs(Decimal(t.amount)) for t in txns), ZERO),
            "most_common": [{"description": d, "count": n} for d, n in common],
        }
        if not txns:
            return data, "Everything is categorized. ✅"
        top = ", ".join(f"{d} ({n}×)" for d, n in common[:3])
        return data, (
            f"{len(txns)} transactions ({self.f.m(data['total'])}) still need a category. "
            f"Most common: {top}. Fix one on the Transactions page and similar ones follow."
        )

    def run(self, tool: str, args: dict, start: dt.date, end: dt.date) -> tuple[Any, str]:
        if tool == "summary":
            return self.summary(start, end)
        if tool == "category_total":
            cat = args.get("_category") or self.resolve_category(str(args.get("category", "")))
            if cat is None:
                raise ValueError("unknown category")
            return self.category_total(cat, start, end)
        if tool == "search":
            text = str(args.get("text") or "").strip()
            if len(text) < 2:
                raise ValueError("search text missing")
            direction = args.get("direction") if args.get("direction") in ("in", "out") else None
            return self.search(text, start, end, direction)
        if tool == "top_expenses":
            return self.top_expenses(start, end, int(args.get("limit") or 5))
        if tool == "monthly":
            return self.monthly(start, end)
        if tool == "invoices":
            status = (
                args.get("status") if args.get("status") in ("open", "overdue", "paid") else "open"
            )
            return self.invoices(status)
        if tool == "uncategorized":
            return self.uncategorized(start, end)
        raise ValueError(f"unknown tool {tool}")


def _stem(word: str) -> str:
    """'events' -> 'event' so plural questions match singular bank descriptions."""
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def analytics_month(key: str) -> str:
    return dt.date.fromisoformat(f"{key}-01").strftime("%b %Y")


# ---- routing --------------------------------------------------------------------

HELP = (
    "I can answer questions about your books, for example:\n"
    "- *How much profit did we make last month?*\n"
    "- *How much did we spend on wages this year?*\n"
    "- *How much have we paid Sysco since March?*\n"
    "- *What are our biggest expenses?*\n"
    "- *Which invoices are overdue?*\n"
    "- *Show profit month by month*"
)

_STOP = {
    "how", "much", "did", "do", "we", "i", "my", "our", "the", "a", "an", "spend", "spent",
    "pay", "paid", "on", "at", "to", "from", "with", "for", "in", "this", "last", "year",
    "month", "months", "what", "was", "were", "is", "are", "have", "has", "been", "total",
    "money", "since", "between", "and", "show", "me", "all", "transactions", "payments",
    "costs", "cost", "get", "got", "receive", "received", "earn", "earned", "many", "times",
    "quarter", "week", "so", "far", "ytd", "per", "each", "any", "there",
}  # fmt: skip


def _period_or_default(books: Books, text: str) -> tuple[dt.date, dt.date]:
    p = parse_period(text, books.last)
    return p if p else (books.first, books.last)


def route_rules(books: Books, question: str, history: list[ChatTurn]) -> tuple[str, dict] | None:
    q = question.lower()
    has = lambda pat: re.search(pat, q) is not None  # noqa: E731

    if has(r"\b(invoice|invoices|owe[sd]?|owed to|unpaid|overdue|outstanding|chase|debtors?)\b"):
        status = "overdue" if has(r"overdue|late|chase") else "paid" if has(r"\bpaid\b") else "open"
        return "invoices", {"status": status}
    if has(r"uncategori[sz]ed|need(s)? (a )?categor|not categori[sz]ed|unknown transactions"):
        return "uncategorized", {}
    if has(
        r"\b(top|biggest|largest|highest|main)\b.*\b(expense|expenses|cost|costs|spend|spending|bills?)\b"
    ) or has(r"where (does|did) (the|my|our) money go"):
        return "top_expenses", {}
    if has(r"month by month|each month|per month|monthly|by month|trend"):
        return "monthly", {}

    cat = books.find_category(q)
    if cat is not None:
        return "category_total", {"category": cat.name, "_category": cat}

    m = re.search(
        r"\b(?:at|to|from|with|on)\s+([a-z0-9&' .-]{2,40}?)\s*(?:\b(?:in|during|for|last|this|since|"
        r"over|between|so far|ytd)\b|[?.!]|$)",
        q,
    )
    if m:
        term = " ".join(w for w in m.group(1).split() if w not in _STOP)
        if len(term) >= 3 and books.search(term, books.first, books.last)[0]["count"]:
            direction = "in" if has(r"\b(from|received|receive|earned|paid us)\b") else None
            return "search", {"text": term, "direction": direction}

    if has(
        r"\b(profit|profits|loss|income|revenue|turnover|earn|earned|made|make|sales|expenses|"
        r"spend|spent|cash ?flow|doing|summary|overview|margin)\b"
    ):
        return "summary", {}

    # Free text: a supplier or customer name on its own ("how much have we paid Sysco?")
    words = [
        w
        for w in re.findall(r"[a-z0-9&]+", q)
        if w not in _STOP and w not in MONTHS and len(w) >= 3 and not w.isdigit()
    ]
    for size in (3, 2, 1):  # prefer the longest phrase that matches something
        for i in range(len(words) - size + 1):
            term = " ".join(words[i : i + size])
            if books.search(term, books.first, books.last)[0]["count"]:
                return "search", {"text": term}

    # Follow-up like "and in May?" → reuse the previous tool with a new period.
    if parse_period(q, books.last) and history:
        prev = next((t for t in reversed(history) if t.role == "assistant" and t.tool), None)
        if prev and prev.tool in TOOLS:
            return prev.tool, dict(prev.args or {})
    return None


def _router_prompt(books: Books, question: str, history: list[ChatTurn]) -> tuple[str, str]:
    cats = ", ".join(f"{c.name} ({c.kind})" for c in sorted(books.categories, key=lambda c: c.name))
    tools = "\n".join(f"- {k}: {v}" for k, v in TOOLS.items())
    convo = "\n".join(f"{t.role}: {t.content[:300]}" for t in history[-4:])
    system = (
        "You route a small-business owner's question about their books to ONE tool. "
        "Reply with JSON only: "
        '{"tool": "<name>", "args": {...}, "start": "YYYY-MM-DD"|null, "end": "YYYY-MM-DD"|null}. '
        "Use null dates for 'all time'. Relative dates ('last month') count back from the "
        f"latest transaction date {books.last.isoformat()}. Data covers "
        f"{books.first.isoformat()} to {books.last.isoformat()}. If the question is not about "
        'the books, use {"tool": "none"}.'
    )
    user = (
        f"Tools:\n{tools}\n\nCategories: {cats}\n\n"
        + (f"Conversation so far:\n{convo}\n\n" if convo else "")
        + f"Question: {question}"
    )
    return system, user


def _parse_date(v: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def ask(
    db: Session,
    question: str,
    currency: str,
    history: list[ChatTurn] | None = None,
    llm: LLMClient | None = None,
    today: dt.date | None = None,
    dayfirst: bool = False,
) -> ChatResult:
    use_dayfirst(dayfirst)
    history = history or []
    books = Books(db, currency, today=today)
    question = question.strip()[:500]
    if not books.has_data:
        return ChatResult(
            "There are no transactions yet — import a bank statement on the Upload page first.",
            "none",
        )

    tool, args, start, end, method = None, {}, None, None, "rules"

    if llm is not None:
        try:
            system, user = _router_prompt(books, question, history)
            plan = extract_json(llm.complete(system, user, json_mode=True))
            if isinstance(plan, dict) and plan.get("tool") in TOOLS:
                tool, args = plan["tool"], plan.get("args") or {}
                start, end = _parse_date(plan.get("start")), _parse_date(plan.get("end"))
                method = "ai"
            elif isinstance(plan, dict) and plan.get("tool") == "none":
                return ChatResult(HELP, "none", method="ai")
        except LLMError as exc:
            log.info("Chat router LLM failed, using rules: %s", exc)

    if tool is None:
        routed = route_rules(books, question, history)
        if routed is None:
            return ChatResult(HELP, "none")
        tool, args = routed
        start, end = _period_or_default(books, question)

    if start is None or end is None:
        start, end = start or books.first, end or books.last
    if end < start:
        start, end = end, start

    try:
        data, text = books.run(tool, args, start, end)
    except (ValueError, TypeError) as exc:
        if method == "ai":  # LLM picked bad args → fall back to rules
            log.info("LLM tool args invalid (%s); using rules", exc)
            return ask(db, question, currency, history, llm=None, today=today, dayfirst=dayfirst)
        return ChatResult(HELP, "none")

    data = _jsonable(data)
    clean_args = {k: v for k, v in args.items() if not k.startswith("_")}

    if llm is not None:
        try:
            text = _phrase(llm, question, data, text, currency)
            method = "ai"
        except LLMError as exc:
            log.info("Chat answer LLM failed, using template: %s", exc)

    return ChatResult(text, tool, clean_args, data, method, start, end)


def _phrase(llm: LLMClient, question: str, data: Any, draft: str, currency: str) -> str:
    system = (
        "You are a friendly bookkeeping assistant for a small business. Answer the question "
        "using ONLY the numbers in the data and the draft answer — never invent or estimate "
        f"figures. Currency: {currency}. Be concise (max 4 sentences), lead with the answer, "
        "bold the key figure with **. Not tax or legal advice."
    )
    payload = json.dumps(data, default=str)[:6000]
    user = f"Question: {question}\n\nData: {payload}\n\nDraft answer (correct figures): {draft}"
    text = llm.complete(system, user).strip()
    if not text:
        raise LLMError("empty answer")
    return text
