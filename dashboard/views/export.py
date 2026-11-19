import datetime as dt

import pandas as pd
import streamlit as st

from dashboard import api, theme, ui

st.title("Tax export")
st.caption(
    "A tax-ready pack for you or your accountant: PDF summary + CSV ledger. Cash basis. "
    "This organises your records — it is not tax advice."
)

years = ui.call(api.get, "/export/tax-years")
if not years:
    ui.empty_state()
    st.stop()

options = [f"Tax year {y['label']}" for y in years] + ["Custom dates"]
c1, c2, _ = st.columns([1.3, 2, 2.5])
choice = c1.selectbox("Period", options, help="Set TAX_YEAR_START in .env (e.g. 04-06 for the UK)")
if choice == "Custom dates":
    rng = ui.call(api.get, "/reports/range")
    first, last = dt.date.fromisoformat(rng["start"]), dt.date.fromisoformat(rng["end"])
    picked = c2.date_input("Dates", (first, last))
    if not (isinstance(picked, tuple) and len(picked) == 2):
        st.stop()
    start, end = picked
else:
    y = years[options.index(choice)]
    start, end = dt.date.fromisoformat(y["start"]), dt.date.fromisoformat(y["end"])
    c2.caption(f"{ui.fmt_date(start)} – {ui.fmt_date(end)}")

s = ui.call(api.get, "/export/summary", start=start, end=end)
cur = s["currency"]


def m(v):
    return theme.money(v, cur, 2)


k1, k2, k3, k4 = st.columns(4, border=True)
k1.metric("Total income", m(s["income"]))
k2.metric("Allowable expenses", m(s["allowable_expenses"]))
k3.metric("Estimated taxable profit", m(s["taxable_profit_estimate"]))
cov = s["receipt_coverage_pct"]
k4.metric("Receipts attached", f"{cov:.0f}%" if cov is not None else "—")

for w in s["warnings"]:
    st.warning(w, icon=":material/warning:")

st.subheader("By category")
cats = pd.DataFrame(s["categories"])
if not cats.empty:
    st.dataframe(
        cats[["category", "treatment", "count", "with_receipts", "total"]],
        hide_index=True,
        column_config={
            "category": "Category",
            "treatment": "Tax treatment",
            "count": "Transactions",
            "with_receipts": "With receipt",
            "total": st.column_config.NumberColumn("Total", format="%.2f"),
        },
    )
st.caption(
    f"Not claimed: disallowable {m(s['disallowable_expenses'])} · uncategorized "
    f"{m(s['uncategorized_out'])}. Transfers/drawings/loans (net) {m(s['transfers_net'])} are not "
    "profit or loss. Mark categories as tax deductible on *Categories & rules*."
)

st.subheader("Download")
tag = f"{start}_{end}"


@st.cache_data(ttl=60, show_spinner=False)
def fetch(path: str, start: dt.date, end: dt.date) -> bytes:
    r = api.client().get(path, params={"start": start.isoformat(), "end": end.isoformat()})
    if r.status_code >= 400:
        raise api.APIError(r.text, r.status_code)
    return r.content


d1, d2, d3, d4 = st.columns(4)
try:
    d1.download_button(
        "Everything (ZIP)",
        fetch("/export/tax-pack.zip", start, end),
        f"tax_pack_{tag}.zip",
        "application/zip",
        type="primary",
        icon=":material/folder_zip:",
    )
    d2.download_button(
        "Tax pack (PDF)",
        fetch("/export/tax-pack.pdf", start, end),
        f"tax_pack_{tag}.pdf",
        "application/pdf",
        icon=":material/picture_as_pdf:",
    )
    d3.download_button(
        "Transactions (CSV)",
        fetch("/export/transactions.csv", start, end),
        f"transactions_{tag}.csv",
        "text/csv",
        icon=":material/table:",
    )
    d4.download_button(
        "Category summary (CSV)",
        fetch("/export/category-summary.csv", start, end),
        f"category_summary_{tag}.csv",
        "text/csv",
        icon=":material/summarize:",
    )
except api.APIError as exc:
    st.error(str(exc))
