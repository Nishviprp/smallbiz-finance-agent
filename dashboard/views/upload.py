import streamlit as st

from dashboard import api, ui

st.title("Upload")
st.caption("Everything is processed by your own API — files never leave your machine.")

tab_stmt, tab_rcpt, tab_inv = st.tabs(["Bank statement", "Receipt", "Sales invoice"])

MIME = {
    "csv": "text/csv",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def mime(name: str) -> str:
    return MIME.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")


with tab_stmt:
    with st.form("statement", clear_on_submit=True):
        files = st.file_uploader(
            "CSV or PDF statements", type=["csv", "pdf"], accept_multiple_files=True
        )
        account = st.text_input("Account name (optional)", placeholder="e.g. Business current")
        use_llm = st.toggle("Use AI for anything rules can't categorize", value=True)
        submitted = st.form_submit_button("Import", type="primary", icon=":material/upload:")
    if submitted and files:
        for f in files:
            with st.spinner(f"Importing {f.name}…"):
                try:
                    r = api.upload(
                        "/uploads/statement",
                        f.name,
                        f.getvalue(),
                        mime(f.name),
                        account=account or None,
                        use_llm=use_llm,
                    )
                except api.APIError as exc:
                    st.error(f"**{f.name}**: {exc}", icon=":material/error:")
                    continue
            by = ", ".join(f"{v} by {k}" for k, v in r["categorized"].items()) or "none"
            st.success(
                f"**{f.name}** — imported **{r['imported']}**, skipped {r['duplicates']} "
                f"duplicates. Categorized: {by}; {r['uncategorized']} left for review.",
                icon=":material/check_circle:",
            )
            extras = []
            if r["invoices_paid"]:
                extras.append(f"{r['invoices_paid']} invoice(s) marked paid")
            if r["receipts_linked"]:
                extras.append(f"{r['receipts_linked']} receipt(s) linked")
            if extras:
                st.info(" · ".join(extras), icon=":material/link:")
            for w in r["warnings"][:5]:
                st.warning(w)

with tab_rcpt:
    with st.form("receipt", clear_on_submit=True):
        files = st.file_uploader(
            "Receipt photos or PDFs",
            type=["png", "jpg", "jpeg", "webp", "pdf"],
            accept_multiple_files=True,
        )
        use_llm = st.toggle("Use AI to read receipts", value=True, key="rcpt_ai")
        submitted = st.form_submit_button("Read receipts", type="primary", icon=":material/upload:")
    if submitted and files:
        cur = ui.currency()
        for f in files:
            with st.spinner(f"Reading {f.name}…"):
                try:
                    r = api.upload(
                        "/uploads/receipt", f.name, f.getvalue(), mime(f.name), use_llm=use_llm
                    )
                except api.APIError as exc:
                    st.error(f"**{f.name}**: {exc}", icon=":material/error:")
                    continue
            total = (
                f"{r['currency']} {r['total']:.2f}" if r["total"] is not None else "total not found"
            )
            linked = "linked to its bank transaction" if r["transaction_id"] else "not linked yet"
            st.success(
                f"**{f.name}** — {r['vendor'] or 'Unknown vendor'}, {r['date'] or 'no date'}, "
                f"{total} · {linked} · read via {r['extraction_method']}",
                icon=":material/receipt:",
            )
            for w in r["warnings"]:
                st.warning(w)

with tab_inv:
    with st.form("invoice", clear_on_submit=True):
        files = st.file_uploader(
            "Invoices you issued (PDF or photo)",
            type=["pdf", "png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
        )
        terms = st.number_input("Default payment terms (days)", 0, 365, 30)
        use_llm = st.toggle("Use AI to read invoices", value=True, key="inv_ai")
        submitted = st.form_submit_button(
            "Add to tracker", type="primary", icon=":material/upload:"
        )
    if submitted and files:
        for f in files:
            with st.spinner(f"Reading {f.name}…"):
                try:
                    r = api.upload(
                        "/uploads/invoice",
                        f.name,
                        f.getvalue(),
                        mime(f.name),
                        use_llm=use_llm,
                        payment_terms_days=terms,
                    )
                except api.APIError as exc:
                    st.error(f"**{f.name}**: {exc}", icon=":material/error:")
                    continue
            status = r["effective_status"].upper()
            st.success(
                f"**{r['number'] or f.name}** — {r['client']}, {r['currency']} {r['amount']:.2f}, "
                f"due {r['due_date']} · **{status}**",
                icon=":material/request_quote:",
            )
            for w in r["warnings"]:
                st.warning(w)
