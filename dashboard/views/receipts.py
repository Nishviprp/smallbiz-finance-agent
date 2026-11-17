import pandas as pd
import streamlit as st

from dashboard import api, ui

st.title("Receipts")
only_unlinked = st.toggle("Only receipts not yet matched to a bank transaction")
receipts = ui.call(api.get, "/receipts", unlinked=only_unlinked or None)

if not receipts:
    st.info("No receipts yet — add photos or PDFs on **Upload**.", icon=":material/receipt:")
    st.stop()

df = pd.DataFrame(
    {
        "id": [r["id"] for r in receipts],
        "Date": [r["date"] for r in receipts],
        "Vendor": [r["vendor"] for r in receipts],
        "Total": [r["total"] for r in receipts],
        "Tax": [r["tax"] for r in receipts],
        "Matched": ["✅ Yes" if r["transaction_id"] else "— No" for r in receipts],
        "Read via": [r["extraction_method"] for r in receipts],
    }
)
st.dataframe(
    df.drop(columns="id"),
    hide_index=True,
    column_config={
        "Total": st.column_config.NumberColumn(format="%.2f"),
        "Tax": st.column_config.NumberColumn(format="%.2f"),
    },
)

st.subheader("Fix a receipt")
r = st.selectbox(
    "Receipt",
    receipts,
    format_func=lambda r: (
        f"#{r['id']} · {r['vendor'] or 'Unknown'} · {r['date'] or 'no date'} · "
        f"{r['total'] if r['total'] is not None else '?'}"
    ),
)
with st.form("fix_receipt"):
    vendor = st.text_input("Vendor", r["vendor"] or "")
    a, b = st.columns(2)
    total = a.number_input("Total", min_value=0.0, value=float(r["total"] or 0), format="%.2f")
    tax = b.number_input("Tax", min_value=0.0, value=float(r["tax"] or 0), format="%.2f")
    txn_id = st.number_input(
        "Linked transaction ID (0 = none)", min_value=0, value=int(r["transaction_id"] or 0)
    )
    notes = st.text_area("Notes", r["notes"] or "")
    save, remove = st.columns(2)
    if save.form_submit_button("Save", type="primary"):
        ui.call(
            api.patch,
            f"/receipts/{r['id']}",
            {
                "vendor": vendor or None,
                "total": total or None,
                "tax": tax or None,
                "transaction_id": txn_id or None,
                "notes": notes or None,
            },
        )
        st.toast("Receipt updated", icon=":material/check:")
        st.rerun()
    if remove.form_submit_button("Delete receipt"):
        ui.call(api.delete, f"/receipts/{r['id']}")
        st.toast("Receipt deleted")
        st.rerun()
