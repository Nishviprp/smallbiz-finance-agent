import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard import api, theme, ui

st.title("Overview")
period = ui.period_filter()
if period is None:
    ui.empty_state()
    st.stop()
start, end = period
cur = ui.currency()
p = theme.palette()


def m(v, d=0):
    return theme.money(v, cur, d)


def delta(key: str) -> str | None:
    pct = (s.get("change_pct") or {}).get(key)
    return None if pct is None else f"{pct:+.1f}% vs previous period"


s = ui.call(api.get, "/reports/summary", start=start, end=end)

# ---- KPI row ----------------------------------------------------------------
k1, k2, k3, k4, k5 = st.columns(5, border=True)
k1.metric("Income", m(s["income"]), delta("income"))
k2.metric("Expenses", m(s["expenses"]), delta("expenses"), delta_color="inverse")
margin = s.get("profit_margin_pct")
k3.metric(
    "Net profit",
    m(s["net_profit"]),
    delta("net_profit"),
    help="Income minus expenses. Transfers, drawings and loans are excluded.",
)
k3.caption(f"Margin {margin:.1f}%" if margin is not None else "Margin —")
k4.metric(
    "Net cash flow", m(s["net_cash"]), help="Everything in minus everything out, incl. transfers."
)
k4.caption(f"Avg monthly spend {m(s['avg_monthly_expenses'])}")
k5.metric("Unpaid invoices", m(s["outstanding_invoices"]))
if s["overdue_count"]:
    k5.markdown(
        f":red[:material/warning: **{s['overdue_count']} overdue** · {m(s['overdue_invoices'])}]"
    )
else:
    k5.caption("Nothing overdue")

if s["uncategorized_count"]:
    st.info(
        f"**{s['uncategorized_count']} transactions** ({m(s['uncategorized_amount'])}) need a "
        "category. They are counted by direction until you review them on **Transactions**.",
        icon=":material/label:",
    )

# ---- Cash flow --------------------------------------------------------------
monthly = pd.DataFrame(ui.call(api.get, "/reports/monthly", start=start, end=end))
monthly["label"] = monthly["month"].map(ui.month_label)

left, right = st.columns(2)
with left:
    st.subheader("Money in vs money out")
    fig = go.Figure(
        [
            go.Bar(
                name="Money in",
                x=monthly["label"],
                y=monthly["cash_in"],
                marker_color=p.series[theme.IN],
                hovertemplate="%{y:,.0f}<extra>Money in</extra>",
            ),
            go.Bar(
                name="Money out",
                x=monthly["label"],
                y=monthly["cash_out"],
                marker_color=p.series[theme.OUT],
                hovertemplate="%{y:,.0f}<extra>Money out</extra>",
            ),
        ]
    )
    fig.update_layout(barmode="group", hovermode="x unified")
    theme.show(theme.style(fig), key="cash_bars")

with right:
    st.subheader("Net profit by month")
    fig = go.Figure(
        go.Scatter(
            name="Net profit",
            x=monthly["label"],
            y=monthly["net_profit"],
            mode="lines+markers",
            line=dict(color=p.series[theme.NET], width=2),
            marker=dict(size=8, line=dict(width=2, color=p.surface)),
            hovertemplate="%{y:,.0f}<extra>Net profit</extra>",
        )
    )
    fig.add_hline(y=0, line_color=p.axis, line_width=1)
    fig.update_layout(hovermode="x unified")
    theme.show(theme.style(fig, legend=False), key="net_line")

with st.expander("Monthly figures (table)"):
    table = monthly[
        ["label", "income", "expenses", "net_profit", "cash_in", "cash_out", "net_cash"]
    ]
    st.dataframe(
        table.rename(
            columns={
                "label": "Month",
                "income": "Income",
                "expenses": "Expenses",
                "net_profit": "Net profit",
                "cash_in": "Money in",
                "cash_out": "Money out",
                "net_cash": "Net cash",
            }
        ),
        hide_index=True,
        column_config={
            c: st.column_config.NumberColumn(format="%.2f")
            for c in ("Income", "Expenses", "Net profit", "Money in", "Money out", "Net cash")
        },
    )

# ---- Where the money goes ---------------------------------------------------
top = ui.call(api.get, "/reports/top-expenses", start=start, end=end, limit=8)
left, right = st.columns([3, 2])
with left:
    st.subheader("Top expense categories")
    cats = pd.DataFrame(top["categories"])
    if cats.empty:
        st.caption("No expenses in this period.")
    else:
        cats = cats.iloc[::-1]  # largest on top
        fig = go.Figure(
            go.Bar(
                x=cats["total"],
                y=cats["category"],
                orientation="h",
                marker_color=p.series[theme.OUT],
                text=[f"{v:.0f}%" if v >= 1 else "<1%" for v in cats["share_pct"]],
                textposition="outside",
                textfont=dict(color=p.ink2),
                cliponaxis=False,
                customdata=cats["share_pct"],
                hovertemplate="%{y}<br><b>%{x:,.2f}</b> · %{customdata:.1f}% of spend<extra></extra>",
            )
        )
        theme.show(
            theme.style(fig, legend=False, money="x", height=40 + 36 * len(cats)), key="top_cats"
        )
with right:
    st.subheader("Top suppliers")
    merchants = pd.DataFrame(top["merchants"])
    if not merchants.empty:
        st.dataframe(
            merchants[["merchant", "total", "count", "share_pct"]],
            hide_index=True,
            column_config={
                "merchant": "Supplier",
                "total": st.column_config.NumberColumn("Spent", format="%.2f"),
                "count": st.column_config.NumberColumn("Payments"),
                "share_pct": st.column_config.ProgressColumn(
                    "Share", format="%.0f%%", min_value=0, max_value=100
                ),
            },
        )

# ---- Trends -----------------------------------------------------------------
st.subheader("Expense trends by category")
trends = ui.call(api.get, "/reports/category-trends", start=start, end=end, kind="expense", top=5)
if trends["series"]:
    labels = [ui.month_label(x) for x in trends["months"]]
    fig = go.Figure()
    for i, sr in enumerate(trends["series"]):
        color = p.other if sr["category"] == "Other" else p.series[i]
        fig.add_scatter(
            name=sr["category"],
            x=labels,
            y=sr["values"],
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(size=8, line=dict(width=2, color=p.surface)),
            hovertemplate="%{y:,.0f}",
        )
    fig.update_layout(hovermode="x unified")
    theme.show(theme.style(fig, height=360), key="trends")
    with st.expander("Trend figures (table)"):
        st.dataframe(
            pd.DataFrame({sr["category"]: sr["values"] for sr in trends["series"]}, index=labels),
            column_config={
                sr["category"]: st.column_config.NumberColumn(format="%.2f")
                for sr in trends["series"]
            },
        )

# ---- Profit & loss statement ------------------------------------------------
st.subheader("Profit & loss")
pl = ui.call(api.get, "/reports/pnl", start=start, end=end)
month_cols = [ui.month_label(x) for x in pl["months"]]


def pl_rows(section: list[dict], heading: str, total: float) -> list[dict]:
    rows, month_totals = [], dict.fromkeys(month_cols, 0.0)
    for line in section:
        vals = dict(zip(month_cols, (line["by_month"][k] for k in pl["months"]), strict=True))
        for k, v in vals.items():
            month_totals[k] += v
        rows.append({"Section": heading, "Line": line["category"], **vals, "Total": line["total"]})
    rows.append(
        {"Section": heading, "Line": f"Total {heading.lower()}", **month_totals, "Total": total}
    )
    return rows


net_by_month = dict(zip(month_cols, monthly["net_profit"], strict=True))
statement = pd.DataFrame(
    pl_rows(pl["income"], "Income", pl["total_income"])
    + pl_rows(pl["expenses"], "Expenses", pl["total_expenses"])
    + [{"Section": "", "Line": "Net profit", **net_by_month, "Total": pl["net_profit"]}]
)
st.dataframe(
    statement,
    hide_index=True,
    height=35 * (len(statement) + 1) + 3,
    column_config={
        "Section": st.column_config.TextColumn(pinned=True, width="small"),
        "Line": st.column_config.TextColumn(pinned=True, width="medium"),
        **{c: st.column_config.NumberColumn(format="%.2f") for c in [*month_cols, "Total"]},
    },
)
st.caption(
    f"Transfers, drawings and loans are excluded from profit "
    f"(net {m(pl['net_transfers'], 2)} this period). Cash basis."
)
