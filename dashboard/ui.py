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
        st.session_state.currency = call(api.get, "/health").get("currency", "USD")
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
    c2.caption(f"{fmt_date(start)} – {fmt_date(end)}")
    return start, end


def empty_state() -> None:
    st.info(
        "No transactions yet. Import a bank statement on **Upload**, or explore with the demo "
        "café first (you can clear it later in **Settings**).",
        icon=":material/upload_file:",
    )
    c1, c2, _ = st.columns([1, 1, 3])
    with c1:
        load_demo_button("empty_demo")
    if c2.button("Upload my statement", icon=":material/upload:"):
        st.switch_page("views/upload.py")


def fmt_date(d: dt.date) -> str:
    """'Jan 5, 2026' (US) or '5 Jan 2026', following the business profile."""
    if st.session_state.get("date_dayfirst"):
        return f"{d.day} {d:%b %Y}"
    return f"{d:%b} {d.day}, {d.year}"


def date_column_format() -> str:
    return "D MMM YYYY" if st.session_state.get("date_dayfirst") else "MMM D, YYYY"


def month_label(key: str) -> str:
    return dt.date.fromisoformat(f"{key}-01").strftime("%b %Y")


MONTHS = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip


def profile_form(current: dict, *, submit_label: str, key: str) -> dict | None:
    """Business profile form (name, country, currency, date format, tax year).
    Returns the PUT /settings body when submitted, else None."""
    meta = call(api.get, "/settings/countries")
    countries: dict = meta["countries"]
    codes = list(countries)

    country = st.selectbox(
        "Where is your business?",
        codes,
        index=codes.index(current.get("country", "US")) if current.get("country") in codes else 0,
        format_func=lambda c: countries[c]["name"],
        key=f"{key}_country",
    )
    preset = countries[country]
    # When the country changes, start from its defaults; otherwise keep saved values.
    use_saved = country == current.get("country") and current.get("setup_complete")
    base = current if use_saved else preset

    with st.form(key):
        name = st.text_input(
            "Business name",
            value=current.get("business_name") or "",
            placeholder="Joe's Coffee LLC",
        )
        c1, c2 = st.columns(2)
        currencies = list(dict.fromkeys([base["currency"], *meta["currencies"]]))
        currency = c1.selectbox("Currency", currencies, index=0)
        date_fmt = c2.radio(
            "Date format on your bank statements",
            ["MM/DD/YYYY", "DD/MM/YYYY"],
            index=1 if base["date_dayfirst"] else 0,
            horizontal=True,
            help="Only used when a file's dates are ambiguous — most files are detected automatically.",
        )
        month, day = (int(x) for x in base["tax_year_start"].split("-"))
        c3, c4 = st.columns(2)
        ty_month = c3.selectbox("Tax year starts in", MONTHS, index=month - 1)
        ty_day = c4.number_input("on day", min_value=1, max_value=31, value=day)

        relabel = False
        others = current.get("other_currency_transactions", 0)
        if others:
            relabel = st.checkbox(
                f"Also relabel my {others} existing transactions to this currency "
                "(amounts stay the same — no conversion)",
                value=True,
            )
        submitted = st.form_submit_button(submit_label, type="primary")

    if not submitted:
        return None
    if not name.strip():
        st.error("Please enter your business name.")
        return None
    return {
        "business_name": name.strip(),
        "country": country,
        "currency": currency,
        "date_dayfirst": date_fmt == "DD/MM/YYYY",
        "tax_year_start": f"{MONTHS.index(ty_month) + 1:02d}-{int(ty_day):02d}",
        "relabel_existing": relabel,
    }


def load_demo_button(key: str = "demo") -> None:
    if st.button("Load the demo café", key=key, icon=":material/coffee:"):
        with st.spinner("Loading 6 months of demo data…"):
            r = call(api.post, "/settings/demo")
        st.toast(
            f"Demo loaded: {r['transactions']} transactions, {r['invoices']} invoices, "
            f"{r['receipts']} receipts",
            icon=":material/check:",
        )
        st.rerun()
