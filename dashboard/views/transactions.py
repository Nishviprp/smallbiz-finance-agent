import pandas as pd
import streamlit as st

from dashboard import api, ui

st.title("Transactions")
period = ui.period_filter()
if period is None:
    ui.empty_state()
    st.stop()
start, end = period

categories = ui.call(api.get, "/categories")
by_name = {c["name"]: c["id"] for c in categories}
UNCAT = "— Uncategorized —"
options = [UNCAT, *sorted(by_name)]

f1, f2, f3, f4 = st.columns([1.4, 1, 1.6, 1])
cat_filter = f1.selectbox("Category", ["All", UNCAT, *sorted(by_name)])
direction = f2.selectbox("Direction", ["All", "Money in", "Money out"])
search = f3.text_input("Search", placeholder="e.g. sysco, rent, uber")
limit = f4.selectbox("Show", [200, 500, 1000], index=1)

params = dict(
    start=start,
    end=end,
    limit=limit,
    search=search or None,
    direction={"Money in": "in", "Money out": "out"}.get(direction),
)
if cat_filter == UNCAT:
    params["uncategorized"] = True
elif cat_filter != "All":
    params["category_id"] = by_name[cat_filter]

page = ui.call(api.get, "/transactions", **params)
items = page["items"]
st.caption(f"Showing {len(items)} of {page['total']} transactions")

a1, a2, _ = st.columns([1.3, 1.6, 3])
remember = a1.toggle(
    "Learn from my edits",
    value=True,
    help="Saving a category also creates a rule and applies it to similar transactions.",
)
if a2.button("Auto-categorize uncategorized", icon=":material/auto_awesome:"):
    with st.spinner("Categorizing… (AI can take a minute)"):
        res = ui.call(api.post, "/transactions/recategorize", {"only_uncategorized": True})
    n = sum(res["updated"].values())
    st.toast(f"Categorized {n} transactions" if n else "Nothing new could be categorized")
    st.rerun()

if not items:
    st.info("No transactions match these filters.")
    st.stop()

SOURCE = {"user": "You", "rule": "Rule", "keyword": "Keyword", "llm": "AI", "none": "—"}
df = pd.DataFrame(
    {
        "id": [t["id"] for t in items],
        "Date": pd.to_datetime([t["date"] for t in items]),
        "Description": [t["description"] for t in items],
        "Amount": [t["amount"] for t in items],
        "Category": [t["category_name"] or UNCAT for t in items],
        "By": [SOURCE.get(t["category_source"], t["category_source"]) for t in items],
        "Confidence": [t["confidence"] for t in items],
        "Notes": [t["notes"] or "" for t in items],
    }
).set_index("id")

edited = st.data_editor(
    df,
    key="txn_editor",
    hide_index=True,
    height=560,
    disabled=["Date", "Description", "Amount", "By", "Confidence"],
    column_config={
        "Date": st.column_config.DateColumn(format=ui.date_column_format(), width="small"),
        "Description": st.column_config.TextColumn(width="large"),
        "Amount": st.column_config.NumberColumn(format="%.2f", width="small"),
        "Category": st.column_config.SelectboxColumn(options=options, required=True),
        "By": st.column_config.TextColumn(
            width="small", help="Who set the category: You, Rule, Keyword or AI"
        ),
        "Confidence": st.column_config.ProgressColumn(
            min_value=0, max_value=1, format="percent", width="small"
        ),
    },
)

changes = []
for tid in df.index:
    before, after = df.loc[tid], edited.loc[tid]
    body = {}
    if after["Category"] != before["Category"]:
        body["category_id"] = None if after["Category"] == UNCAT else by_name[after["Category"]]
        body["remember"] = remember and after["Category"] != UNCAT
    if after["Notes"] != before["Notes"]:
        body["notes"] = after["Notes"] or None
    if body:
        changes.append((int(tid), body))

if changes and st.button(f"Save {len(changes)} change(s)", type="primary", icon=":material/save:"):
    also = rules = 0
    for tid, body in changes:
        res = ui.call(api.patch, f"/transactions/{tid}", body)
        also += res["also_updated"]
        rules += 1 if res["rule_created"] else 0
    msg = f"Saved {len(changes)} change(s)"
    if rules:
        msg += f" · learned {rules} rule(s) · updated {also} similar transaction(s)"
    st.session_state.pop("txn_editor", None)
    st.toast(msg, icon=":material/check:")
    st.rerun()
