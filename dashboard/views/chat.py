import pandas as pd
import streamlit as st

from dashboard import api, ui

st.title("Ask your books")
st.caption(
    "Plain-English questions about your transactions and invoices. Read-only — every number "
    "is calculated from your data, the AI only chooses the question type and words the answer."
)

if "chat" not in st.session_state:
    st.session_state.chat = []

EXAMPLES = [
    "How much profit did we make last month?",
    "How much did we spend on wages this year?",
    "What are our biggest expenses?",
    "Which invoices are overdue?",
]


def render_data(turn: dict) -> None:
    data, tool = turn.get("data"), turn.get("tool")
    if not data or tool in (None, "none"):
        return
    rows = None
    if tool == "search":
        rows = data.get("transactions")
    elif tool == "invoices":
        rows = data.get("invoices")
    elif tool == "top_expenses":
        rows = data.get("categories")
    elif tool == "monthly":
        rows = data
    elif tool == "uncategorized":
        rows = data.get("most_common")
    elif tool == "category_total":
        rows = [{"month": k, "total": v} for k, v in data.get("by_month", {}).items()]
    if rows:
        with st.expander("Show the numbers"):
            st.dataframe(pd.DataFrame(rows), hide_index=True)
    period = f"{turn['start']} → {turn['end']}" if turn.get("start") else ""
    how = "AI" if turn.get("method") == "ai" else "built-in rules"
    st.caption(" · ".join(x for x in (period, f"answered with {how}") if x))


for turn in st.session_state.chat:
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        if turn["role"] == "assistant":
            render_data(turn)

if not st.session_state.chat:
    st.markdown("**Try:**")
    cols = st.columns(len(EXAMPLES))
    for col, ex in zip(cols, EXAMPLES, strict=True):
        if col.button(ex, key=f"ex_{ex}"):
            st.session_state.pending = ex
            st.rerun()

question = st.chat_input("Ask about your income, spending, suppliers or invoices…")
question = question or st.session_state.pop("pending", None)

if question:
    history = [
        {k: t.get(k) for k in ("role", "content", "tool", "args")}
        for t in st.session_state.chat[-8:]
    ]
    st.session_state.chat.append({"role": "user", "content": question})
    with st.spinner("Checking your books…"):
        res = ui.call(api.post, "/chat", {"question": question, "history": history})
    st.session_state.chat.append(
        {
            "role": "assistant",
            "content": res["answer"],
            "tool": res["tool"],
            "args": res["args"],
            "data": res["data"],
            "method": res["method"],
            "start": res["start"],
            "end": res["end"],
        }
    )
    st.rerun()

if st.session_state.chat and st.button("Clear conversation", icon=":material/delete_sweep:"):
    st.session_state.chat = []
    st.rerun()
