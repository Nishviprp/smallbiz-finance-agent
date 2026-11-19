"""Tax-ready exports: transaction ledger CSV, category summary CSV, invoices CSV,
a one-page-per-section PDF tax pack, and a ZIP bundle for your accountant.

The numbers are an estimate on a cash basis. Uncategorized money out is NOT treated as
allowable until you review it (the conservative choice); uncategorized money in IS counted
as income. Always have an accountant check before filing.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, Invoice, Receipt, Transaction
from .business import BusinessProfile
from .dates import fmt_date, fmt_short

ZERO = Decimal("0")

SOURCE_LABELS = {
    "user": "manual", "rule": "rule", "keyword": "keyword", "bank": "bank", "llm": "AI", "none": "",
}  # fmt: skip


def _treatment(cat: Category | None) -> str:
    if cat is None:
        return "Needs review"
    if cat.kind == "transfer":
        return "Not profit/loss"
    if cat.kind == "income":
        return "Income"
    return "Allowable expense" if cat.tax_deductible else "Disallowable expense"


@dataclass
class LedgerLine:
    id: int
    date: dt.date
    description: str
    amount: Decimal
    currency: str
    category: str
    kind: str
    treatment: str
    source: str
    account: str
    receipt: bool
    notes: str


def ledger(db: Session, start: dt.date, end: dt.date) -> list[LedgerLine]:
    cats = {c.id: c for c in db.scalars(select(Category))}
    with_receipt = set(
        db.scalars(select(Receipt.transaction_id).where(Receipt.transaction_id.is_not(None)))
    )
    q = (
        select(Transaction)
        .where(Transaction.date >= start, Transaction.date <= end)
        .order_by(Transaction.date, Transaction.id)
    )
    out = []
    for t in db.scalars(q):
        cat = cats.get(t.category_id) if t.category_id else None
        out.append(
            LedgerLine(
                id=t.id,
                date=t.date,
                description=t.description,
                amount=Decimal(t.amount),
                currency=t.currency,
                category=cat.name if cat else "Uncategorized",
                kind=cat.kind if cat else ("income" if t.amount > 0 else "expense"),
                treatment=_treatment(cat),
                source=SOURCE_LABELS.get(t.category_source, t.category_source),
                account=t.account or "",
                receipt=t.id in with_receipt,
                notes=t.notes or "",
            )
        )
    return out


@dataclass
class CategoryLine:
    category: str
    kind: str
    treatment: str
    count: int = 0
    total: Decimal = ZERO  # income: money in; expense: spend (refunds reduce it); transfer: net
    with_receipts: int = 0


@dataclass
class TaxPack:
    business: str
    currency: str
    start: dt.date
    end: dt.date
    dayfirst: bool = False
    income: Decimal = ZERO
    allowable_expenses: Decimal = ZERO
    disallowable_expenses: Decimal = ZERO
    uncategorized_in: Decimal = ZERO
    uncategorized_out: Decimal = ZERO
    uncategorized_count: int = 0
    transfers_net: Decimal = ZERO
    sales_tax_on_invoices: Decimal = ZERO
    tax_on_receipts: Decimal = ZERO
    expense_count: int = 0
    expense_with_receipt: int = 0
    unpaid_at_end: list[Invoice] = field(default_factory=list)
    categories: list[CategoryLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def taxable_profit_estimate(self) -> Decimal:
        return self.income - self.allowable_expenses

    @property
    def receipt_coverage_pct(self) -> float | None:
        if not self.expense_count:
            return None
        return self.expense_with_receipt / self.expense_count * 100


def build_tax_pack(db: Session, start: dt.date, end: dt.date, profile: BusinessProfile) -> TaxPack:
    pack = TaxPack(profile.business_name, profile.currency, start, end, profile.date_dayfirst)
    lines = ledger(db, start, end)
    by_cat: dict[str, CategoryLine] = {}
    for ln in lines:
        name = ln.category
        if ln.treatment == "Needs review":  # split by direction so both are visible
            name = "Uncategorized money in" if ln.amount > 0 else "Uncategorized money out"
        cl = by_cat.setdefault(name, CategoryLine(name, ln.kind, ln.treatment))
        cl.count += 1
        cl.with_receipts += 1 if ln.receipt else 0
        signed = ln.amount if ln.kind in ("income", "transfer") else -ln.amount
        cl.total += signed

        if ln.treatment == "Income":
            pack.income += ln.amount
        elif ln.treatment == "Allowable expense":
            pack.allowable_expenses += -ln.amount
        elif ln.treatment == "Disallowable expense":
            pack.disallowable_expenses += -ln.amount
        elif ln.treatment == "Not profit/loss":
            pack.transfers_net += ln.amount
        else:
            pack.uncategorized_count += 1
            if ln.amount > 0:
                pack.uncategorized_in += ln.amount
                pack.income += ln.amount  # conservative: unknown money in is income
            else:
                pack.uncategorized_out += -ln.amount
        if ln.amount < 0 and ln.kind == "expense":
            pack.expense_count += 1
            pack.expense_with_receipt += 1 if ln.receipt else 0

    order = {"Income": 0, "Allowable expense": 1, "Disallowable expense": 2, "Needs review": 3}
    pack.categories = sorted(by_cat.values(), key=lambda c: (order.get(c.treatment, 4), -c.total))

    pack.sales_tax_on_invoices = sum(
        (
            i.tax or ZERO
            for i in db.scalars(
                select(Invoice).where(
                    Invoice.issue_date >= start, Invoice.issue_date <= end, Invoice.status != "void"
                )
            )
        ),
        ZERO,
    )
    pack.tax_on_receipts = sum(
        (
            r.tax or ZERO
            for r in db.scalars(select(Receipt).where(Receipt.date >= start, Receipt.date <= end))
        ),
        ZERO,
    )
    pack.unpaid_at_end = [
        i
        for i in db.scalars(
            select(Invoice).where(Invoice.issue_date <= end, Invoice.status != "void")
        )
        if i.status == "unpaid" or (i.paid_date and i.paid_date > end)
    ]

    if not lines:
        pack.warnings.append("No transactions in this period.")
    if pack.uncategorized_count:
        pack.warnings.append(
            f"{pack.uncategorized_count} transactions are uncategorized. Money in is counted as "
            f"income; {_money(pack.uncategorized_out, pack.currency)} of money out is NOT claimed "
            "until you categorize it."
        )
    cov = pack.receipt_coverage_pct
    if cov is not None and cov < 50:
        pack.warnings.append(
            f"Only {cov:.0f}% of expense payments have a receipt attached. "
            "Keep records for everything you claim."
        )
    return pack


# ---- CSV ----------------------------------------------------------------------


def _csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens £/€ correctly


def ledger_csv(lines: list[LedgerLine]) -> bytes:
    header = [
        "Date", "Description", "Money in", "Money out", "Amount", "Currency", "Category",
        "Type", "Tax treatment", "Categorized by", "Receipt", "Account", "Notes", "ID",
    ]  # fmt: skip
    rows = [
        [
            ln.date.isoformat(),
            ln.description,
            f"{ln.amount:.2f}" if ln.amount > 0 else "",
            f"{-ln.amount:.2f}" if ln.amount < 0 else "",
            f"{ln.amount:.2f}",
            ln.currency,
            ln.category,
            ln.kind,
            ln.treatment,
            ln.source,
            "yes" if ln.receipt else "",
            ln.account,
            ln.notes,
            ln.id,
        ]
        for ln in lines
    ]
    return _csv(header, rows)


def summary_csv(pack: TaxPack) -> bytes:
    rows = [
        [c.category, c.kind, c.treatment, c.count, f"{c.total:.2f}", c.with_receipts]
        for c in pack.categories
    ]
    rows += [
        [],
        ["Total income", "", "", "", f"{pack.income:.2f}", ""],
        ["Allowable expenses", "", "", "", f"{pack.allowable_expenses:.2f}", ""],
        ["Disallowable expenses", "", "", "", f"{pack.disallowable_expenses:.2f}", ""],
        ["Uncategorized money out (not claimed)", "", "", "", f"{pack.uncategorized_out:.2f}", ""],
        ["Estimated taxable profit", "", "", "", f"{pack.taxable_profit_estimate:.2f}", ""],
    ]
    return _csv(
        ["Category", "Type", "Tax treatment", "Transactions", "Total", "With receipt"], rows
    )


def invoices_csv(db: Session) -> bytes:
    rows = [
        [
            i.number or "",
            i.client,
            i.client_email or "",
            i.issue_date.isoformat(),
            i.due_date.isoformat(),
            f"{i.amount:.2f}",
            f"{i.tax:.2f}" if i.tax is not None else "",
            i.currency,
            i.status,
            i.paid_date.isoformat() if i.paid_date else "",
        ]
        for i in db.scalars(select(Invoice).order_by(Invoice.issue_date))
    ]
    header = ["Number", "Client", "Email", "Issued", "Due", "Amount", "Tax", "Currency",
              "Status", "Paid on"]  # fmt: skip
    return _csv(header, rows)


# ---- PDF ----------------------------------------------------------------------

_SYM = {"GBP": "£", "EUR": "€", "USD": "$", "CAD": "$", "AUD": "$"}


def _money(v: Decimal | float, currency: str) -> str:
    sym = _SYM.get(currency, "")
    s = f"{abs(Decimal(v)):,.2f}"
    s = f"{sym}{s}" if sym else f"{s} {currency}"
    return f"-{s}" if v < 0 else s


def tax_pack_pdf(pack: TaxPack) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], alignment=0, fontSize=20, spaceAfter=4)
    h2 = ParagraphStyle(
        "h2", parent=ss["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=6, keepWithNext=1
    )
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#52514e"))
    m = lambda v: _money(v, pack.currency)  # noqa: E731
    fd = lambda d: fmt_date(d, pack.dayfirst)  # noqa: E731
    fs = lambda d: fmt_short(d, pack.dayfirst)  # noqa: E731

    def table(rows, widths, bold_last=False, header=True, text_cols=1):
        t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
        style = [
            ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
            ("ALIGN", (text_cols, 0), (-1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e1e0d9")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if header:
            style += [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0efec")),
            ]
        if bold_last:
            style.append(("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9))
        t.setStyle(TableStyle(style))
        return t

    story = [
        Paragraph("Tax pack", h1),
        Paragraph(
            f"<b>{_esc(pack.business)}</b> · {fd(pack.start)} – {fd(pack.end)} · "
            f"{pack.currency} · cash basis · generated {fd(dt.date.today())}",
            body,
        ),
        Spacer(1, 8),
        Paragraph("Summary", h2),
        table(
            [
                ["", "Amount"],
                ["Total income", m(pack.income)],
                ["Allowable expenses", m(pack.allowable_expenses)],
                ["Estimated taxable profit", m(pack.taxable_profit_estimate)],
                ["Disallowable expenses (not claimed)", m(pack.disallowable_expenses)],
                ["Uncategorized money out (not claimed)", m(pack.uncategorized_out)],
                ["Transfers, drawings & loans (net, not P&L)", m(pack.transfers_net)],
                ["Sales tax / VAT on invoices issued", m(pack.sales_tax_on_invoices)],
                ["Tax / VAT shown on receipts", m(pack.tax_on_receipts)],
            ],
            [120 * mm, 45 * mm],
        ),
    ]
    cov = pack.receipt_coverage_pct
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            f"Receipts attached to {pack.expense_with_receipt} of {pack.expense_count} expense "
            f"payments ({cov:.0f}%)."
            if cov is not None
            else "No expense payments.",
            small,
        )
    )

    if pack.warnings:
        story.append(Paragraph("Check before filing", h2))
        for w in pack.warnings:
            story.append(Paragraph(f"• {_esc(w)}", body))

    for title, treatments in [
        ("Income", {"Income"}),
        ("Expenses", {"Allowable expense", "Disallowable expense"}),
        ("Needs review", {"Needs review"}),
        ("Not profit or loss", {"Not profit/loss"}),
    ]:
        cats = [c for c in pack.categories if c.treatment in treatments]
        if not cats:
            continue
        rows = [["Category", "Treatment", "Count", "Receipts", "Total"]]
        rows += [
            [c.category, c.treatment, str(c.count), str(c.with_receipts), m(c.total)] for c in cats
        ]
        # "Needs review" mixes money in and out, so a single total would mislead.
        total = "" if title == "Needs review" else m(sum(c.total for c in cats))
        rows.append(["Total", "", str(sum(c.count for c in cats)), "", total])
        story += [
            Paragraph(title, h2),
            table(rows, [62 * mm, 40 * mm, 18 * mm, 20 * mm, 30 * mm], bold_last=True, text_cols=2),
        ]

    if pack.unpaid_at_end:
        rows = [["Invoice", "Client", "Issued", "Due", "Amount"]]
        rows += [
            [i.number or f"#{i.id}", _clip(i.client, 34), fs(i.issue_date), fs(i.due_date),
             m(i.amount)]
            for i in pack.unpaid_at_end
        ]  # fmt: skip
        rows.append(["Total owed to you", "", "", "", m(sum(i.amount for i in pack.unpaid_at_end))])
        story += [
            Paragraph(f"Unpaid invoices at {fd(pack.end)}", h2),
            Paragraph(
                "Not included in cash-basis income above; relevant if you report on an "
                "accruals (invoice) basis.",
                small,
            ),
            Spacer(1, 4),
            table(rows, [30 * mm, 62 * mm, 25 * mm, 25 * mm, 28 * mm], bold_last=True, text_cols=2),
        ]

    story += [
        Spacer(1, 14),
        Paragraph(
            "Prepared with SmallBiz Finance Agent (open source). This is an organised summary of "
            "your records, not tax advice. Allowable expenses depend on your country's rules — "
            "ask a qualified accountant to review before filing.",
            small,
        ),
    ]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Tax pack {pack.start} to {pack.end}",
        author=pack.business,
    )
    doc.build(story)
    return buf.getvalue()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def tax_pack_zip(db: Session, pack: TaxPack) -> bytes:
    lines = ledger(db, pack.start, pack.end)
    tag = f"{pack.start:%Y%m%d}-{pack.end:%Y%m%d}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"tax_pack_{tag}.pdf", tax_pack_pdf(pack))
        z.writestr(f"transactions_{tag}.csv", ledger_csv(lines))
        z.writestr(f"category_summary_{tag}.csv", summary_csv(pack))
        z.writestr("invoices.csv", invoices_csv(db))
        z.writestr(
            "README.txt",
            f"Tax pack for {pack.business}, {pack.start} to {pack.end} ({pack.currency}).\n"
            "tax_pack.pdf          summary for you / your accountant\n"
            "transactions.csv      every bank line with category and tax treatment\n"
            "category_summary.csv  totals per category\n"
            "invoices.csv          all sales invoices and payment status\n",
        )
    return buf.getvalue()
