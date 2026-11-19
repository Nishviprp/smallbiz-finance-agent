"""SmallBiz Finance Agent — Streamlit dashboard.

Run:  python -m streamlit run dashboard/app.py
      (the API must be running: python -m uvicorn finagent.main:app)
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
        st.Page(VIEWS / "bank.py", title="Bank accounts", icon=":material/account_balance:"),
        st.Page(VIEWS / "upload.py", title="Upload", icon=":material/upload_file:"),
        st.Page(VIEWS / "categories.py", title="Categories & rules", icon=":material/category:"),
        st.Page(VIEWS / "settings.py", title="Settings", icon=":material/settings:"),
    ],
}

from dashboard import ui  # noqa: E402

ui.apply_pending_cookie()

# ---- 1. Is the API there? ----------------------------------------------------------
try:
    health = api.get("/health")
except api.APIError as exc:
    with st.sidebar:
        st.markdown("### 📒 SmallBiz Finance Agent")
        st.error(
            f"{exc}\n\nStart it with `python -m uvicorn finagent.main:app`, "
            "or set `API_URL` if it runs elsewhere.",
            icon=":material/cloud_off:",
        )
    st.stop()
st.session_state.health = health
accounts = health.get("auth_mode") == "accounts"

# ---- 2. Who is this? (accounts mode: login; local mode: the one business) ---------
user = None
if accounts:
    if not st.session_state.get("auth_token"):
        remembered = ui.remembered_token()
        if remembered:
            st.session_state.auth_token = remembered
    me = None
    if st.session_state.get("auth_token"):
        try:
            me = api.get("/auth/me")
        except api.APIError as exc:
            if exc.status != 401:
                st.error(str(exc))
                st.stop()
            ui.sign_out(local_only=True)  # expired or revoked
            st.rerun()
    if me is None:
        st.navigation([st.Page(VIEWS / "login.py", title="Log in", icon=":material/login:")]).run()
        st.stop()
    user, profile = me["user"], me["profile"]
else:
    profile = health

st.session_state.currency = profile.get("currency", "USD")
st.session_state.date_dayfirst = profile.get("date_dayfirst", False)

# ---- 3. Sidebar --------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 📒 SmallBiz Finance Agent")
    if profile.get("setup_complete"):
        st.caption(f"**{profile.get('business_name', '')}** · {profile.get('currency', '')}")
    if user:
        st.caption(f"Signed in as {user['email']}")
        if st.button("Log out", icon=":material/logout:", key="logout"):
            ui.sign_out()
            st.rerun()
    provider = health.get("llm_provider", "none")
    st.caption(f"AI: **{provider}** · v{health.get('version', '')}")

# ---- 4. Pages ----------------------------------------------------------------------
if not profile.get("setup_complete"):
    # First run: only the welcome wizard until the business profile is saved.
    st.navigation(
        [st.Page(VIEWS / "setup.py", title="Welcome", icon=":material/waving_hand:")]
    ).run()
else:
    st.navigation(pages).run()
