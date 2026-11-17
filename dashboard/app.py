"""SmallBiz Finance Agent — Streamlit dashboard.

Run:  streamlit run dashboard/app.py      (API must be running: uvicorn finagent.main:app)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from dashboard import api  # noqa: E402

st.set_page_config(page_title="SmallBiz Finance Agent", page_icon="📒", layout="wide")

VIEWS = ROOT / "dashboard" / "views"
pages = {
    "Books": [
        st.Page(VIEWS / "overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page(VIEWS / "transactions.py", title="Transactions", icon=":material/receipt_long:"),
        st.Page(VIEWS / "invoices.py", title="Invoices", icon=":material/request_quote:"),
        st.Page(VIEWS / "receipts.py", title="Receipts", icon=":material/receipt:"),
        st.Page(VIEWS / "chat.py", title="Ask your books", icon=":material/chat:"),
        st.Page(VIEWS / "export.py", title="Tax export", icon=":material/download:"),
    ],
    "Manage": [
        st.Page(VIEWS / "upload.py", title="Upload", icon=":material/upload_file:"),
        st.Page(VIEWS / "categories.py", title="Categories & rules", icon=":material/category:"),
    ],
}

with st.sidebar:
    st.markdown("### 📒 SmallBiz Finance Agent")
    try:
        health = api.get("/health")
        st.session_state.currency = health.get("currency", "GBP")
        provider = health.get("llm_provider", "none")
        st.caption(f"API connected · AI: **{provider}** · {health.get('version', '')}")
    except api.APIError as exc:
        st.error(
            f"{exc}\n\nStart it with `uvicorn finagent.main:app`.", icon=":material/cloud_off:"
        )
        st.stop()

st.navigation(pages).run()
