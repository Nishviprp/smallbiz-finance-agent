"""Display dates the way the business is used to: 'Jan 5, 2026' (US) or '5 Jan 2026'."""

from __future__ import annotations

import datetime as dt
from contextvars import ContextVar

_DAYFIRST: ContextVar[bool] = ContextVar("dayfirst", default=False)


def use_dayfirst(value: bool) -> None:
    """Set the style for the current request/thread."""
    _DAYFIRST.set(value)


def fmt_date(d: dt.date, dayfirst: bool | None = None) -> str:
    first = _DAYFIRST.get() if dayfirst is None else dayfirst
    return f"{d.day} {d:%b %Y}" if first else f"{d:%b} {d.day}, {d.year}"


def fmt_short(d: dt.date, dayfirst: bool | None = None) -> str:
    first = _DAYFIRST.get() if dayfirst is None else dayfirst
    return f"{d:%d/%m/%Y}" if first else f"{d:%m/%d/%Y}"
