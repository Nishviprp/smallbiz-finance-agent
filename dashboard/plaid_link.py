"""Plaid Link as a tiny Streamlit component (static HTML, no build step)."""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_component = components.declare_component(
    "plaid_link", path=str(Path(__file__).parent / "components" / "plaid_link")
)


def plaid_link(link_token: str, *, label: str = "Connect your bank", key: str) -> dict | None:
    """Shows the button; returns {"public_token", "institution"} or {"error"} once done."""
    return _component(link_token=link_token, label=label, key=key, default=None)
