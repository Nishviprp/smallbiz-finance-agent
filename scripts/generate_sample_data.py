"""Generate a realistic 6-month bank statement for a small café (deterministic).

Usage: python scripts/generate_sample_data.py
Writes sample_data/bank_statement_cafe.csv (UK-style: DD/MM/YYYY, signed amounts, balance).
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


def main() -> None:
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

    balance = Decimal("8500.00")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Date", "Description", "Amount", "Balance"])
        for d, desc, amt in rows:
            balance += amt
            w.writerow([d.strftime("%d/%m/%Y"), desc, f"{amt:.2f}", f"{balance:.2f}"])
    print(f"Wrote {len(rows)} transactions to {OUT}")


if __name__ == "__main__":
    main()
