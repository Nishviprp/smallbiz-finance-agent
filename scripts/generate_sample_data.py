"""Generate realistic demo data for a small US café (deterministic).

Bean & Bloom Café LLC, Jersey City, NJ — January to June 2026.

Usage: python scripts/generate_sample_data.py
Writes to sample_data/:
  bank_statement_cafe.csv   6 months, US-style (MM/DD/YYYY, signed amounts, balance)
  bank_statement_cafe.pdf   January as a PDF statement (withdrawals / deposits / balance)
  receipts/                 receipt photo (PNG) + PDF that match statement lines
  invoices/                 sales invoices: one paid (in the statement), one overdue
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from decimal import Decimal
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "sample_data" / "bank_statement_cafe.csv"
START, END = dt.date(2026, 1, 1), dt.date(2026, 6, 30)
NJ_SALES_TAX = Decimal("0.06625")
BUSINESS = "Bean & Bloom Café LLC"
ADDRESS = "214 Newark Ave, Jersey City, NJ 07302"


def money(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def generate_rows() -> list[tuple[dt.date, str, Decimal]]:
    rng = random.Random(42)
    rows: list[tuple[dt.date, str, Decimal]] = []
    day = START
    while day <= END:
        wd = day.weekday()
        seasonal = 1 + (day.month - 1) * 0.04  # business growing into summer
        # Daily card takings deposit (next business day); Monday includes the weekend
        if wd < 5:
            base = 1150 if wd == 0 else 720
            amt = money(base * seasonal * rng.uniform(0.8, 1.2))
            rows.append((day, f"SQUARE INC DEPOSIT {day:%m%d}", amt))
        if wd == 1:
            amt = money(-rng.uniform(380, 560) * seasonal)
            rows.append((day, "SYSCO NEW JERSEY INV 4421", amt))
        if wd == 3:
            rows.append((day, "RESTAURANT DEPOT SECAUCUS", money(-rng.uniform(150, 260))))
            rows.append((day, "ACH COUNTER CULTURE COFFEE", money(-rng.uniform(210, 290))))
        if wd == 4 and rng.random() < 0.35:
            rows.append((day, "COSTCO WHSE #1129 BAYONNE", money(-rng.uniform(60, 180))))
        if wd == 2 and rng.random() < 0.25:
            rows.append((day, "UBER EATS PAYOUT", money(rng.uniform(120, 260))))
        if day.day == 1:
            rows.append((day, "ZELLE PAYMENT TO HUDSON PROPERTY MGMT RENT", Decimal("-2200.00")))
        if day.day == 3:
            rows.append((day, "PSE&G ELECTRIC & GAS", money(-rng.uniform(180, 320))))
            rows.append((day, "SUEZ WATER NJ", money(-rng.uniform(45, 70))))
        if day.day == 5:
            rows.append((day, "VERIZON FIOS BUSINESS", Decimal("-79.99")))
            rows.append((day, "SQUARESPACE INC", Decimal("-23.00")))
            rows.append((day, "CANVA PTY LTD", Decimal("-14.99")))
        if day.day == 8:
            rows.append((day, "THE HARTFORD INSURANCE", Decimal("-86.50")))
        if day.day == 12:
            rows.append((day, "FACEBK ADS 8XK2", money(-rng.uniform(40, 120))))
        if day.day == 15:
            rows.append((day, "GUSTO TAX PAYROLL TAXES", money(-rng.uniform(820, 980))))
        if day.day == 20:
            rows.append((day, "INTUIT *QUICKBOOKS", Decimal("-38.00")))
            rows.append((day, "NJ DIVISION OF TAXATION SALES TAX", money(-rng.uniform(1050, 1350))))
        if day.day == 25:
            amt = money(-rng.uniform(4300, 4800) * seasonal)
            rows.append((day, "GUSTO PAYROLL NET PAY", amt))
        if day.day == 28:
            rows.append((day, "MONTHLY MAINTENANCE FEE", Decimal("-15.00")))
            rows.append((day, "TRANSFER TO SAVINGS XXXX4491", Decimal("-500.00")))
        if day.day == 10 and day.month in (1, 4):
            rows.append((day, "IRS USATAXPYMT ESTIMATED TAX", money(-rng.uniform(1800, 2400))))
        # Irregular / harder-to-categorize lines (left for the LLM or the user)
        if wd == 5 and rng.random() < 0.3:
            rows.append((day, "J SMITH WINDOW CLEANING", Decimal("-25.00")))
        if rng.random() < 0.04:
            rows.append((day, "HAPPY HOUND DOG TREATS", money(-rng.uniform(15, 35))))
        if rng.random() < 0.03:
            rows.append((day, "THE HOME DEPOT #0912", money(-rng.uniform(12, 90))))
        if rng.random() < 0.03:
            rows.append((day, "USPS PO 3345 JERSEY CITY", money(-rng.uniform(3, 15))))
        if rng.random() < 0.025:
            amt = money(rng.uniform(250, 600))
            rows.append((day, "ZELLE FROM GREEN LLC CATERING EVENT DEPOSIT", amt))
        day += dt.timedelta(days=1)
    return rows


OPENING_BALANCE = Decimal("8500.00")


def write_csv(rows) -> None:
    balance = OPENING_BALANCE
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Description", "Amount", "Balance"])
        for d, desc, amt in rows:
            balance += amt
            w.writerow([d.strftime("%m/%d/%Y"), desc, f"{amt:.2f}", f"{balance:.2f}"])
    print(f"Wrote {len(rows)} transactions to {OUT}")


def write_pdf_statement(rows) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    path = OUT.parent / "bank_statement_cafe.pdf"
    styles = getSampleStyleSheet()
    data = [["Date", "Description", "Withdrawals", "Deposits", "Balance"]]
    balance = OPENING_BALANCE
    for d, desc, amt in rows:
        if d.month != 1:
            continue
        balance += amt
        out_, in_ = (f"{-amt:,.2f}", "") if amt < 0 else ("", f"{amt:,.2f}")
        data.append([d.strftime("%m/%d/%Y"), desc, out_, in_, f"{balance:,.2f}"])
    table = Table(data, colWidths=[62, 240, 66, 62, 70], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    doc = SimpleDocTemplate(str(path), pagesize=LETTER, title="Bean & Bloom Cafe statement")
    doc.build(
        [
            Paragraph("Demo Community Bank — Business Checking", styles["Title"]),
            Paragraph(f"{BUSINESS} · Account ending 4491 · January 2026", styles["Normal"]),
            Paragraph(f"Beginning balance: ${OPENING_BALANCE:,.2f}", styles["Normal"]),
            Spacer(1, 12),
            table,
        ]
    )
    print(f"Wrote {path}")


def _first(rows, needle: str):
    return next(r for r in rows if needle in r[1])


def write_receipts(rows) -> None:
    from PIL import Image, ImageDraw, ImageFont

    folder = OUT.parent / "receipts"
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("*"):
        old.unlink()

    # 1. Phone-photo style PNG receipt for a Home Depot purchase in the statement
    d, _, amt = _first(rows, "HOME DEPOT")
    total = -amt
    net = (total / (1 + NJ_SALES_TAX)).quantize(Decimal("0.01"))
    lines = [
        "THE HOME DEPOT",
        "Store 0912  Jersey City, NJ",
        "",
        f"Date: {d:%m/%d/%Y}  10:42 AM",
        "",
        f"Sealant & fixings      {net:>8.2f}",
        f"Subtotal               {net:>8.2f}",
        f"Sales Tax 6.625%       {total - net:>8.2f}",
        f"TOTAL                  {total:>8.2f}",
        "",
        "VISA ending 4491",
        "Thank you for shopping",
    ]
    font = ImageFont.load_default(size=30)
    img = Image.new("RGB", (720, 70 + 46 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 35 + i * 46), line, fill="black", font=font)
    img.save(folder / "receipt_home_depot.png")

    # 2. PDF receipt for a Costco purchase
    from reportlab.lib.pagesizes import A6
    from reportlab.pdfgen import canvas

    d, _, amt = _first(rows, "COSTCO")
    c = canvas.Canvas(str(folder / "receipt_costco.pdf"), pagesize=A6)
    y = 380
    for line in [
        "COSTCO WHOLESALE",
        "Bayonne #1129, NJ",
        f"Date: {d:%m/%d/%Y}",
        "",
        f"Catering supplies   ${-amt:.2f}",
        f"TOTAL               ${-amt:.2f}",
        "Sales Tax           $0.00",
    ]:
        c.setFont("Helvetica", 10)
        c.drawString(20, y, line)
        y -= 16
    c.save()
    print(f"Wrote receipts to {folder}")


def write_invoices(rows) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    folder = OUT.parent / "invoices"
    folder.mkdir(parents=True, exist_ok=True)
    paid_date, _, paid_amt = _first(rows, "GREEN LLC")
    invoices = [
        # (number, client, email, issue, due, gross) — first one is paid in the statement
        (
            "INV-2026-014",
            "Green LLC",
            "accounts@greenllc.example",
            paid_date - dt.timedelta(days=12),
            paid_date + dt.timedelta(days=2),
            paid_amt,
        ),
        (
            "INV-2026-021",
            "Riverside Book Club",
            "treasurer@riverside.example",
            dt.date(2026, 5, 6),
            dt.date(2026, 6, 5),
            Decimal("486.00"),
        ),
    ]
    for number, client, email, issue, due, gross in invoices:
        net = (gross / (1 + NJ_SALES_TAX)).quantize(Decimal("0.01"))
        c = canvas.Canvas(str(folder / f"{number}.pdf"), pagesize=LETTER)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, 740, BUSINESS)
        c.setFont("Helvetica", 10)
        c.drawString(50, 724, f"{ADDRESS} · hello@beanandbloom.example")
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, 685, "INVOICE")
        c.setFont("Helvetica", 10)
        y = 662
        for line in [
            f"Invoice No: {number}",
            f"Invoice Date: {issue:%m/%d/%Y}",
            f"Due Date: {due:%m/%d/%Y}",
            "",
            "Bill To:",
            client,
            email,
            "",
            "Event catering and room hire",
            f"Subtotal: ${net:,.2f}",
            f"Sales Tax (6.625%): ${gross - net:,.2f}",
            f"Amount Due: ${gross:,.2f}",
            "",
            f"Pay by Zelle or ACH to {BUSINESS}. Thank you!",
        ]:
            c.drawString(50, y, line)
            y -= 16
        c.save()
    print(f"Wrote invoices to {folder}")


def main() -> None:
    rows = generate_rows()
    write_csv(rows)
    write_pdf_statement(rows)
    write_receipts(rows)
    write_invoices(rows)


if __name__ == "__main__":
    main()
