"""Shared types and value parsers for all importers."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from dateutil import parser as dateparser


@dataclass(frozen=True)
class ParsedTxn:
    date: dt.date
    description: str
    amount: Decimal  # signed: + in, - out


@dataclass
class ParsedStatement:
    rows: list[ParsedTxn] = field(default_factory=list)
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


_CURRENCY = re.compile(r"[£$€¥₹]|\b(?:GBP|USD|EUR|INR|CAD|AUD)\b", re.IGNORECASE)


def parse_amount(value: object) -> Decimal | None:
    """Parse messy bank amounts.

    Handles: '£1,234.50', '-12.00', '(45.00)', '12.00-', '12.00 DR', '1.234,56', '' -> None.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and value != value:  # NaN
            return None
        return Decimal(str(value)).quantize(Decimal("0.01"))

    s = _CURRENCY.sub("", str(value)).strip().replace("−", "-").replace(" ", "")
    if not s or s in {"-", "--", "nan", "None"}:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    upper = s.upper()
    if upper.endswith("DR"):
        negative, s = True, s[:-2]
    elif upper.endswith("CR"):
        s = s[:-2]
    if s.endswith("-"):
        negative, s = True, s[:-1]
    if s.startswith("+"):
        s = s[1:]
    if s.startswith("-"):
        negative, s = not negative, s[1:]

    # Decimal separator detection
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:  # 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}", s) else s.replace(",", "")

    try:
        amount = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -amount if negative else amount


_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\s*$")
_ISO_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$")


def infer_dayfirst(samples: Iterable[str], default: bool = True) -> bool:
    """Decide DD/MM vs MM/DD from the whole column, not row by row."""
    for s in samples:
        m = _NUMERIC_DATE.match(str(s))
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 >= b:
            return True
        if b > 12 >= a:
            return False
    return default


def parse_date(value: object, dayfirst: bool) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    if not s:
        return None
    iso = _ISO_DATE.match(s)
    if iso:  # dateutil mis-reads YYYY-MM-DD when dayfirst=True
        try:
            return dt.date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    try:
        return dateparser.parse(s, dayfirst=dayfirst, fuzzy=False).date()
    except (ValueError, OverflowError, TypeError):
        return None


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
