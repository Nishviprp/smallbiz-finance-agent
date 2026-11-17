"""Date periods: tax years and plain-English periods ("last month", "Q1 2026", "in March")."""

from __future__ import annotations

import calendar
import datetime as dt
import re

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9

Period = tuple[dt.date, dt.date]


def month_end(y: int, m: int) -> dt.date:
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def shift_month(y: int, m: int, delta: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


# ---- Tax years --------------------------------------------------------------


def parse_month_day(value: str) -> tuple[int, int]:
    """'04-06' -> (4, 6). Default UK tax year starts 6 April; US/most others 1 January."""
    m = re.fullmatch(r"\s*(\d{1,2})-(\d{1,2})\s*", value or "")
    if not m:
        raise ValueError(f"Invalid TAX_YEAR_START '{value}', expected MM-DD")
    month, day = int(m.group(1)), int(m.group(2))
    dt.date(2001, month, day)  # validates
    return month, day


def tax_year_for(d: dt.date, start_md: str) -> Period:
    month, day = parse_month_day(start_md)
    start = dt.date(d.year, month, day)
    if d < start:
        start = dt.date(d.year - 1, month, day)
    end = dt.date(start.year + 1, month, day) - dt.timedelta(days=1)
    return start, end


def tax_year_label(period: Period) -> str:
    s, e = period
    return str(s.year) if s.year == e.year else f"{s.year}/{str(e.year)[-2:]}"


def tax_years_covering(first: dt.date, last: dt.date, start_md: str) -> list[Period]:
    out: list[Period] = []
    cur = tax_year_for(first, start_md)
    while cur[0] <= last:
        out.append(cur)
        cur = tax_year_for(cur[1] + dt.timedelta(days=1), start_md)
    return out


# ---- Natural language -------------------------------------------------------


def parse_period(text: str, anchor: dt.date) -> Period | None:
    """Find a period in free text. Relative periods count back from `anchor`
    (the latest transaction date), matching the dashboard presets."""
    t = text.lower()

    m = re.search(r"\b(?:last|past|previous)\s+(\d{1,2})\s+months?\b", t)
    if m:
        n = max(1, int(m.group(1)))
        y, mo = shift_month(anchor.year, anchor.month, -(n - 1))
        return dt.date(y, mo, 1), anchor
    if re.search(r"\b(?:this|current)\s+month\b|\bmonth to date\b|\bmtd\b", t):
        return dt.date(anchor.year, anchor.month, 1), anchor
    if re.search(r"\b(?:last|previous|past)\s+month\b", t):
        y, mo = shift_month(anchor.year, anchor.month, -1)
        return dt.date(y, mo, 1), month_end(y, mo)
    if re.search(r"\b(?:this|current)\s+year\b|\byear to date\b|\bytd\b", t):
        return dt.date(anchor.year, 1, 1), anchor
    if re.search(r"\b(?:last|previous)\s+year\b", t):
        return dt.date(anchor.year - 1, 1, 1), dt.date(anchor.year - 1, 12, 31)
    if re.search(r"\b(?:this|current)\s+quarter\b", t):
        q0 = (anchor.month - 1) // 3 * 3 + 1
        return dt.date(anchor.year, q0, 1), anchor
    if re.search(r"\b(?:last|previous)\s+quarter\b", t):
        y, q0 = shift_month(anchor.year, (anchor.month - 1) // 3 * 3 + 1, -3)
        return dt.date(y, q0, 1), month_end(*shift_month(y, q0, 2))

    m = re.search(r"\bq([1-4])(?:\s*(\d{4}))?\b", t)
    if m:
        q, year = int(m.group(1)), int(m.group(2) or anchor.year)
        start_m = (q - 1) * 3 + 1
        return dt.date(year, start_m, 1), month_end(year, start_m + 2)

    month_pat = "|".join(sorted(MONTHS, key=len, reverse=True))
    m = re.search(rf"\b(?:since|from)\s+({month_pat})\b\.?(?:\s+(\d{{4}}))?", t)
    if m:
        mo = MONTHS[m.group(1)]
        year = (
            int(m.group(2))
            if m.group(2)
            else (anchor.year if mo <= anchor.month else anchor.year - 1)
        )
        return dt.date(year, mo, 1), anchor
    m = re.search(r"\bsince\s+(20\d{2})\b", t)
    if m:
        return dt.date(int(m.group(1)), 1, 1), anchor
    m = re.search(rf"\b({month_pat})\b\.?(?:\s+(\d{{4}}))?", t)
    if m and (m.group(1) != "may" or _may_is_month(t)):
        mo = MONTHS[m.group(1)]
        year = (
            int(m.group(2))
            if m.group(2)
            else (anchor.year if mo <= anchor.month else anchor.year - 1)
        )
        return dt.date(year, mo, 1), month_end(year, mo)

    m = re.search(r"\b(?:in|for|during)?\s*(20\d{2})\b", t)
    if m:
        y = int(m.group(1))
        return dt.date(y, 1, 1), dt.date(y, 12, 31)
    return None


def _may_is_month(t: str) -> bool:
    """'May' is also a verb ('may I…'); treat it as the month only in date-like contexts."""
    return bool(re.search(r"\b(?:in|during|for|of|since|last|this)\s+may\b|\bmay\s+20\d{2}\b", t))
