"""Shared dashboard helpers: the period filter, API error display, formatting."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

import streamlit as st

from dashboard import api

PRESETS = (
    "All time",
    "Latest month",
    "Last 3 months",
    "Last 6 months",
    "Year to date",
    "Last 12 months",
    "Custom",
)


def call(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Call the API; show a friendly error and stop the page if it fails."""
    try:
        return fn(*args, **kwargs)
    except api.APIError as exc:
        st.error(str(exc), icon=":material/error:")
        st.stop()


def currency() -> str:
    if "currency" not in st.session_state:
        st.session_state.currency = call(api.get, "/health").get("currency", "GBP")
    return st.session_state.currency


def _month_start(d: dt.date, months_back: int) -> dt.date:
    y, m = d.year, d.month - months_back
    while m <= 0:
        y, m = y - 1, m + 12
    return dt.date(y, m, 1)


def preset_range(preset: str, first: dt.date, last: dt.date) -> tuple[dt.date, dt.date]:
    """Presets are anchored to the latest transaction, since statements arrive late."""
    if preset == "Latest month":
        return _month_start(last, 0), last
    if preset == "Last 3 months":
        return max(first, _month_start(last, 2)), last
    if preset == "Last 6 months":
        return max(first, _month_start(last, 5)), last
    if preset == "Year to date":
        return max(first, dt.date(last.year, 1, 1)), last
    if preset == "Last 12 months":
        return max(first, _month_start(last, 11)), last
    return first, last


def period_filter() -> tuple[dt.date, dt.date] | None:
    """Date-range control, in one row above the content. Shared across pages."""
    rng = call(api.get, "/reports/range")
    if not rng.get("start"):
        return None
    first = dt.date.fromisoformat(rng["start"])
    last = dt.date.fromisoformat(rng["end"])

    c1, c2, _ = st.columns([1.2, 2, 3])
    preset = c1.selectbox(
        "Period", PRESETS, key="period_preset", help="Relative to your latest transaction"
    )
    if preset == "Custom":
        default = st.session_state.get("period_custom", (first, last))
        picked = c2.date_input(
            "Dates", value=default, min_value=first, max_value=last, key="period_custom"
        )
        if isinstance(picked, tuple) and len(picked) == 2:
            return picked[0], picked[1]
        return first, last
    start, end = preset_range(preset, first, last)
    c2.caption(f"{start:%d %b %Y} – {end:%d %b %Y}")
    return start, end


def empty_state() -> None:
    st.info(
        "No transactions yet. Go to **Upload** and import a bank statement — "
        "try `sample_data/bank_statement_cafe.csv`.",
        icon=":material/upload_file:",
    )


def month_label(key: str) -> str:
    return dt.date.fromisoformat(f"{key}-01").strftime("%b %Y")
