import pandas as pd
import streamlit as st

from dashboard import api, ui

st.title("Categories & rules")
cats = ui.call(api.get, "/categories")
by_id = {c["id"]: c for c in cats}

tab_cats, tab_rules = st.tabs(["Categories", "Rules"])

with tab_cats:
    st.caption(
        "Your chart of accounts. **Kind** decides where it lands: income/expense count towards "
        "profit, transfers (savings, drawings, loans) only move cash. **Tax deductible** feeds "
        "the tax export."
    )
    df = pd.DataFrame(cats).set_index("id")[["name", "kind", "tax_deductible"]]
    edited = st.data_editor(
        df,
        key="cat_editor",
        hide_index=True,
        column_config={
            "name": st.column_config.TextColumn("Name", required=True, max_chars=80),
            "kind": st.column_config.SelectboxColumn(
                "Kind", options=["income", "expense", "transfer"], required=True
            ),
            "tax_deductible": st.column_config.CheckboxColumn("Tax deductible"),
        },
    )
    diffs = [
        (cid, {k: (bool(v) if k == "tax_deductible" else v) for k, v in edited.loc[cid].items()})
        for cid in df.index
        if not edited.loc[cid].equals(df.loc[cid])
    ]
    if diffs and st.button(f"Save {len(diffs)} change(s)", type="primary"):
        for cid, body in diffs:
            ui.call(api.patch, f"/categories/{int(cid)}", body)
        st.session_state.pop("cat_editor", None)
        st.toast("Categories saved", icon=":material/check:")
        st.rerun()

    a, b = st.columns(2)
    with a, st.form("new_cat", clear_on_submit=True):
        st.markdown("**Add a category**")
        name = st.text_input("Name")
        kind = st.selectbox("Kind", ["expense", "income", "transfer"])
        deductible = st.checkbox("Tax deductible", value=kind == "expense")
        if st.form_submit_button("Add", type="primary") and name.strip():
            ui.call(
                api.post,
                "/categories",
                {"name": name.strip(), "kind": kind, "tax_deductible": deductible},
            )
            st.rerun()
    with b, st.form("del_cat"):
        st.markdown("**Delete a category**")
        victim = st.selectbox("Category", cats, format_func=lambda c: c["name"])
        st.caption("Its transactions become uncategorized and its rules are removed.")
        if st.form_submit_button("Delete"):
            ui.call(api.delete, f"/categories/{victim['id']}")
            st.rerun()

with tab_rules:
    st.caption(
        "If a description contains the pattern, the category is applied. Rules beat built-in "
        "keywords and AI. They are created automatically when you fix a transaction with "
        "*Learn from my edits* on."
    )
    rules = ui.call(api.get, "/rules")
    if rules:
        st.dataframe(
            pd.DataFrame(
                {
                    "Pattern": [r["pattern"] for r in rules],
                    "Category": [by_id.get(r["category_id"], {}).get("name") for r in rules],
                    "Priority": [r["priority"] for r in rules],
                }
            ),
            hide_index=True,
        )
    else:
        st.caption("No rules yet.")

    a, b = st.columns(2)
    with a, st.form("new_rule", clear_on_submit=True):
        st.markdown("**Add a rule**")
        pattern = st.text_input("Description contains", placeholder="e.g. window cleaning")
        cat = st.selectbox("Category", cats, format_func=lambda c: c["name"])
        apply = st.checkbox("Apply to existing transactions", value=True)
        if st.form_submit_button("Add rule", type="primary") and len(pattern.strip()) >= 2:
            ui.call(
                api.post,
                "/rules",
                {"pattern": pattern, "category_id": cat["id"], "apply_to_existing": apply},
            )
            st.rerun()
    if rules:
        with b, st.form("del_rule"):
            st.markdown("**Delete a rule**")
            rule = st.selectbox("Rule", rules, format_func=lambda r: r["pattern"])
            if st.form_submit_button("Delete"):
                ui.call(api.delete, f"/rules/{rule['id']}")
                st.rerun()
