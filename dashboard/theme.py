"""Chart styling: a validated colorblind-safe palette (light + dark) and Plotly defaults.

Categorical slots are assigned in a fixed order and follow the *entity*:
money in = slot 1, money out = slot 2, net = slot 3; category trends take slots 1..5
in all-time rank order, and "Other" is always neutral grey.
"""

from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go
import streamlit as st

FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'


@dataclass(frozen=True)
class Palette:
    series: tuple[str, ...]
    surface: str
    ink: str
    ink2: str
    muted: str
    grid: str
    axis: str
    other: str
    ordinal: tuple[str, ...]  # light → dark, for ordered buckets (invoice aging)
    critical: str


LIGHT = Palette(
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
    surface="#fcfcfb",
    ink="#0b0b0b",
    ink2="#52514e",
    muted="#898781",
    grid="#e1e0d9",
    axis="#c3c2b7",
    other="#898781",
    ordinal=("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"),
    critical="#d03b3b",
)
DARK = Palette(
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#0ca30c", "#9085e9", "#e66767"),
    surface="#1a1a19",
    ink="#f0efec",
    ink2="#c3c2b7",
    muted="#898781",
    grid="#2c2c2a",
    axis="#383835",
    other="#898781",
    ordinal=("#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95"),
    critical="#d03b3b",
)

IN, OUT, NET = 0, 1, 2  # slot indexes for cash-flow entities


def palette() -> Palette:
    theme = getattr(getattr(st, "context", None), "theme", None)
    return DARK if getattr(theme, "type", "light") == "dark" else LIGHT


def style(fig: go.Figure, *, height: int = 320, legend: bool = True, money: str = "y") -> go.Figure:
    p = palette()
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=16, t=36 if legend else 8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=p.ink2, size=13),
        showlegend=legend,
        legend=dict(orientation="h", x=0, y=1.02, yanchor="bottom", title=None, font_color=p.ink2),
        hoverlabel=dict(bgcolor=p.surface, bordercolor=p.grid, font=dict(color=p.ink, family=FONT)),
        barcornerradius=4,
        bargap=0.35,
        bargroupgap=0.06,
    )
    axis = dict(
        gridcolor=p.grid,
        linecolor=p.axis,
        zerolinecolor=p.axis,
        tickfont=dict(color=p.muted, size=12),
        title=None,
        automargin=True,
    )
    fig.update_xaxes(**axis, showgrid=money == "x")
    fig.update_yaxes(**axis, showgrid=money == "y")
    if money in ("x", "y"):
        getattr(fig, f"update_{money}axes")(tickformat="~s")
    return fig


def show(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, theme=None, key=key, config={"displayModeBar": False})


SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹", "CAD": "$", "AUD": "$"}


def money(value: float | int | None, currency: str = "GBP", decimals: int = 0) -> str:
    if value is None:
        return "—"
    sym = SYMBOLS.get(currency, "")
    sign = "-" if value < 0 else ""
    return f"{sign}{sym}{abs(value):,.{decimals}f}"
