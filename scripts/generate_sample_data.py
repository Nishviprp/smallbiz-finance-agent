"""Generate realistic demo data for a small café (deterministic).

Usage: python scripts/generate_sample_data.py
Writes to sample_data/:
  bank_statement_cafe.csv   6 months, UK-style (DD/MM/YYYY, signed amounts, balance)
  bank_statement_cafe.pdf   January as a PDF statement (paid out / paid in / balance)
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


def money(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def generate_rows() -> list[tuple[dt.date, str, Decimal]]:
    rng = random.Random(42)
    rows: list[tuple[dt.date, str, Decimal]] = []
    day = START
    while day <= END:
        wd = day.weekday()
        seasonal = 1 + (day.month - 1) * 0.04  # business growing into summer
        # Daily card takings payout (next business day), cafés are busiest at weekends
        if wd < 5:
            base = 1150 if wd == 0 else 720  # Monday payout includes weekend
            rows.append(
                (day, f"SUMUP PAYOUT {day:%d%m}", money(base * seasonal * rng.uniform(0.8, 1.2)))
            )
        if wd == 1:
            rows.append(
                (day, "BOOKERS WHOLESALE LTD CARD 4421", money(-rng.uniform(380, 560) * seasonal))
            )
        if wd == 3:
            rows.append((day, "CARD PAYMENT TO BRAKES FOOD SERVICE", money(-rng.uniform(150, 260))))
            rows.append((day, "DD MONMOUTH COFFEE ROASTERS", money(-rng.uniform(210, 290))))
        if wd == 4 and rng.random() < 0.35:
            rows.append((day, "CARD PAYMENT TO COSTCO WHOLESALE", money(-rng.uniform(60, 180))))
        if wd == 2 and rng.random() < 0.25:
            rows.append((day, "UBER EATS PAYOUT", money(rng.uniform(120, 260))))
        if day.day == 1:
            rows.append((day, "SO LANDLORD RENT HIGH ST UNIT 4", Decimal("-2200.00")))
        if day.day == 3:
            rows.append((day, "DD BRITISH GAS BUSINESS", money(-rng.uniform(180, 320))))
            rows.append((day, "DD THAMES WATER", money(-rng.uniform(45, 70))))
        if day.day == 5:
            rows.append((day, "DD BT GROUP PLC BROADBAND", Decimal("-48.00")))
            rows.append((day, "CARD PAYMENT TO SQUARESPACE INC", Decimal("-19.00")))
            rows.append((day, "CARD PAYMENT TO CANVA PTY", Decimal("-10.99")))
        if day.day == 8:
            rows.append((day, "DD HISCOX INSURANCE", Decimal("-64.50")))
        if day.day == 12:
            rows.append((day, "CARD PAYMENT TO META ADS FACEBK", money(-rng.uniform(40, 120))))
        if day.day == 15:
            rows.append((day, "HMRC PAYE", money(-rng.uniform(820, 980))))
        if day.day == 20:
            rows.append((day, "DD SIMPLY XERO UK", Decimal("-33.00")))
        if day.day == 25:
            rows.append(
                (day, "BACS PAYROLL STAFF WAGES", money(-rng.uniform(4300, 4800) * seasonal))
            )
        if day.day == 28:
            rows.append((day, "MONTHLY ACCOUNT FEE", Decimal("-12.50")))
            rows.append((day, "TRANSFER TO SAVINGS 20-44-91", Decimal("-500.00")))
        if day.day == 10 and day.month in (1, 4):
            rows.append((day, "HMRC VAT PAYMENT REF 123456789", money(-rng.uniform(1800, 2400))))
        # Irregular / harder-to-categorize lines (left for the LLM or the user)
        if wd == 5 and rng.random() < 0.3:
            rows.append((day, "J SMITH WINDOW CLEANING", Decimal("-25.00")))
        if rng.random() < 0.04:
            rows.append(
                (day, "CARD PAYMENT TO HAPPY HOUND DOG TREATS", money(-rng.uniform(15, 35)))
            )
        if rng.random() < 0.03:
            rows.append((day, "SCREWFIX DIRECT", money(-rng.uniform(12, 90))))
        if rng.random() < 0.03:
            rows.append((day, "ROYAL MAIL GROUP", money(-rng.uniform(3, 15))))
        if rng.random() < 0.025:
            rows.append(
                (day, "FPI CATERING EVENT DEPOSIT - GREEN LTD", money(rng.uniform(250, 600)))
            )
        if rng.random() < 0.02:
            rows.append((day, "CARD PAYMENT TO MAKRO", money(-rng.uniform(40, 140))))
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
            w.writerow([d.strftime("%d/%m/%Y"), desc, f"{amt:.2f}", f"{balance:.2f}"])
    print(f"Wrote {len(rows)} transactions to {OUT}")


def write_pdf_statement(rows) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    path = OUT.parent / "bank_statement_cafe.pdf"
    styles = getSampleStyleSheet()
    data = [["Date", "Description", "Paid out", "Paid in", "Balance"]]
    balance = OPENING_BALANCE
    for d, desc, amt in rows:
        if d.month != 1:
            continue
        balance += amt
        out_, in_ = (f"{-amt:,.2f}", "") if amt < 0 else ("", f"{amt:,.2f}")
        data.append([d.strftime("%d/%m/%Y"), desc, out_, in_, f"{balance:,.2f}"])
    table = Table(data, colWidths=[62, 250, 62, 62, 70], repeatRows=1)
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
    doc = SimpleDocTemplate(str(path), pagesize=A4, title="Bean & Bloom Cafe statement")
    doc.build(
        [
            Paragraph("Demo Bank plc — Business Current Account", styles["Title"]),
            Paragraph(
                "Bean &amp; Bloom Café Ltd · Sort code 20-44-91 · January 2026", styles["Normal"]
            ),
            Paragraph(f"Balance brought forward: £{OPENING_BALANCE:,.2f}", styles["Normal"]),
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

    # 1. Phone-photo style PNG receipt for a Screwfix purchase in the statement
    d, _, amt = _first(rows, "SCREWFIX")
    total = -amt
    net = (total / Decimal("1.2")).quantize(Decimal("0.01"))
    lines = [
        "SCREWFIX",
        "Unit 3 Trade Park, London",
        "VAT No. GB 232 1234 56",
        "",
        f"Date: {d:%d/%m/%Y}  10:42",
        "",
        f"Sealant & fixings      {net:>8.2f}",
        f"Subtotal               {net:>8.2f}",
        f"VAT 20%                {total - net:>8.2f}",
        f"TOTAL                  {total:>8.2f}",
        "",
        "Paid by card",
        "Thank you for shopping",
    ]
    font = ImageFont.load_default(size=30)
    img = Image.new("RGB", (720, 70 + 46 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 35 + i * 46), line, fill="black", font=font)
    img.save(folder / "receipt_screwfix.png")

    # 2. PDF receipt for a Makro purchase
    from reportlab.lib.pagesizes import A6
    from reportlab.pdfgen import canvas

    d, _, amt = _first(rows, "MAKRO")
    c = canvas.Canvas(str(folder / "receipt_makro.pdf"), pagesize=A6)
    y = 380
    for line in [
        "MAKRO Cash & Carry",
        "Charlton, London",
        f"Date: {d:%d/%m/%Y}",
        "",
        f"Catering supplies   £{-amt:.2f}",
        f"TOTAL               £{-amt:.2f}",
        "VAT                 £0.00",
    ]:
        c.setFont("Helvetica", 10)
        c.drawString(20, y, line)
        y -= 16
    c.save()
    print(f"Wrote receipts to {folder}")


def write_invoices(rows) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    folder = OUT.parent / "invoices"
    folder.mkdir(parents=True, exist_ok=True)
    paid_date, _, paid_amt = _first(rows, "GREEN LTD")
    invoices = [
        # (number, client, email, issue, due, gross) — first one is paid in the statement
        (
            "INV-2026-014",
            "Green Ltd",
            "accounts@greenltd.example",
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
        net = (gross / Decimal("1.2")).quantize(Decimal("0.01"))
        c = canvas.Canvas(str(folder / f"{number}.pdf"), pagesize=A4)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, 790, "Bean & Bloom Café Ltd")
        c.setFont("Helvetica", 10)
        c.drawString(50, 774, "12 High Street, London · hello@beanandbloom.example")
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, 735, "INVOICE")
        c.setFont("Helvetica", 10)
        y = 712
        for line in [
            f"Invoice No: {number}",
            f"Invoice Date: {issue:%d/%m/%Y}",
            f"Due Date: {due:%d/%m/%Y}",
            "",
            "Bill To:",
            client,
            email,
            "",
            "Event catering and room hire",
            f"Subtotal: £{net:,.2f}",
            f"VAT (20%): £{gross - net:,.2f}",
            f"Amount Due: £{gross:,.2f}",
            "",
            "Bank transfer to Bean & Bloom Café Ltd, sort code 20-44-91. Thank you!",
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
