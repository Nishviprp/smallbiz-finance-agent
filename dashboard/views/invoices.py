import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import api, theme, ui

st.title("Invoices")
cur = ui.currency()
p = theme.palette()


def m(v):
    return theme.money(v, cur, 2)


alerts = ui.call(api.get, "/invoices/alerts")

# ---- Alerts -----------------------------------------------------------------
k1, k2, k3 = st.columns(3, border=True)
k1.metric("Outstanding", m(alerts["total_outstanding"]))
k2.metric("Overdue", m(alerts["total_overdue"]))
k2.caption(f"{len(alerts['overdue'])} invoice(s)")
k3.metric("Due in the next 7 days", str(len(alerts["due_soon"])))

for a in alerts["overdue"]:
    st.error(
        f"**{a['number'] or 'Invoice'}** · {a['client']} · {m(a['amount'])} — "
        f"**{a['days']} days overdue** (due {a['due_date']})",
        icon=":material/warning:",
    )
for a in alerts["due_soon"]:
    st.warning(
        f"**{a['number'] or 'Invoice'}** · {a['client']} · {m(a['amount'])} — "
        f"due in {a['days']} day(s) ({a['due_date']})",
        icon=":material/schedule:",
    )

# ---- Aging ------------------------------------------------------------------
if alerts["total_outstanding"]:
    st.subheader("Aging of unpaid invoices")
    buckets = list(alerts["aging"].keys())
    labels = ["Not yet due" if b == "current" else f"{b} days late" for b in buckets]
    fig = go.Figure(
        go.Bar(
            x=labels,
            y=[alerts["aging"][b] for b in buckets],
            marker_color=list(p.ordinal),  # ordinal: later = darker
            hovertemplate="%{x}<br><b>%{y:,.2f}</b><extra></extra>",
        )
    )
    theme.show(theme.style(fig, legend=False, height=260), key="aging")

# ---- List -------------------------------------------------------------------
st.subheader("All invoices")
status = st.segmented_control(
    "Status", ["Open", "Overdue", "Paid", "Void", "All"], default="Open", key="inv_status"
)
param = {"Open": "open", "Overdue": "overdue", "Paid": "paid", "Void": "void"}.get(status or "All")
invoices = ui.call(api.get, "/invoices", status=param)

if invoices:
    STATUS = {
        "overdue": "🔴 Overdue",
        "unpaid": "🟡 Unpaid",
        "paid": "🟢 Paid",
        "void": "⚪ Void",
    }
    df = pd.DataFrame(
        {
            "id": [i["id"] for i in invoices],
            "Number": [i["number"] or "—" for i in invoices],
            "Client": [i["client"] for i in invoices],
            "Issued": [i["issue_date"] for i in invoices],
            "Due": [i["due_date"] for i in invoices],
            "Amount": [i["amount"] for i in invoices],
            "Status": [STATUS.get(i["effective_status"], i["effective_status"]) for i in invoices],
            "Days late": [i["days_overdue"] or None for i in invoices],
            "Paid on": [i["paid_date"] or "" for i in invoices],
        }
    )
    st.dataframe(
        df.drop(columns="id"),
        hide_index=True,
        column_config={"Amount": st.column_config.NumberColumn(format="%.2f")},
    )
else:
    st.caption("No invoices here.")

# ---- Actions ----------------------------------------------------------------
c1, c2 = st.columns(2)
with (
    c1,
    st.expander("Add an invoice manually", icon=":material/add:"),
    st.form("new_invoice", clear_on_submit=True),
):
    number = st.text_input("Invoice number")
    client = st.text_input("Client *")
    email = st.text_input("Client email")
    a, b = st.columns(2)
    issued = a.date_input("Issue date", dt.date.today())
    due = b.date_input("Due date", dt.date.today() + dt.timedelta(days=30))
    amount = st.number_input("Amount incl. tax *", min_value=0.0, step=10.0, format="%.2f")
    tax = st.number_input("Tax included", min_value=0.0, step=1.0, format="%.2f")
    if st.form_submit_button("Add invoice", type="primary"):
        if not client or amount <= 0:
            st.error("Client and a positive amount are required.")
        else:
            r = ui.call(
                api.post,
                "/invoices",
                {
                    "number": number or None,
                    "client": client,
                    "client_email": email or None,
                    "issue_date": issued.isoformat(),
                    "due_date": due.isoformat(),
                    "amount": amount,
                    "tax": tax or None,
                },
            )
            st.toast(f"Added — status: {r['effective_status']}", icon=":material/check:")
            st.rerun()

open_invoices = [i for i in ui.call(api.get, "/invoices", status="open")]
with c2, st.expander("Mark an invoice as paid", icon=":material/paid:"):
    if not open_invoices:
        st.caption("No open invoices.")
    else:
        with st.form("mark_paid"):
            choice = st.selectbox(
                "Invoice",
                open_invoices,
                format_func=lambda i: (
                    f"{i['number'] or '#' + str(i['id'])} · {i['client']} · {m(i['amount'])}"
                ),
            )
            paid_on = st.date_input("Paid on", dt.date.today())
            if st.form_submit_button("Mark paid", type="primary"):
                ui.call(
                    api.post,
                    f"/invoices/{choice['id']}/mark-paid",
                    {"paid_date": paid_on.isoformat()},
                )
                st.toast("Marked as paid", icon=":material/check:")
                st.rerun()

if st.button("Re-check bank transactions for payments", icon=":material/sync:"):
    n = ui.call(api.post, "/invoices/match")["matched"]
    st.toast(f"{n} invoice(s) matched to payments" if n else "No new payments found")
    st.rerun()
