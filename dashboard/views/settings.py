import streamlit as st

from dashboard import api, ui

st.title("Settings")

current = ui.call(api.get, "/settings")
st.subheader("Business profile")
body = ui.profile_form(current, submit_label="Save changes", key="settings")
if body:
    ui.call(api.put, "/settings", body)
    st.session_state.pop("currency", None)
    st.toast("Settings saved", icon=":material/check:")
    st.rerun()

st.subheader("Data")
st.caption("Your books are stored on this computer (or in your own database) — nowhere else.")
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("**Demo data**")
    st.caption("Six months of a fictional café in Jersey City, NJ — great for a walkthrough.")
    ui.load_demo_button("settings_demo")
with c2, st.container(border=True):
    st.markdown("**Start fresh**")
    st.caption(
        "Deletes all transactions, invoices, receipts, rules and uploaded files. "
        "Your categories and business profile are kept."
    )
    confirm = st.text_input("Type DELETE to confirm", key="reset_confirm")
    if st.button("Delete all data", type="primary", disabled=confirm != "DELETE"):
        r = ui.call(api.post, "/settings/reset", {"confirm": "DELETE"})
        st.toast(f"Deleted {r['deleted']['transactions']} transactions", icon=":material/delete:")
        st.session_state.pop("reset_confirm", None)
        st.rerun()

if st.session_state.get("health", {}).get("auth_mode") == "accounts":
    st.subheader("Account")
    with st.form("password", clear_on_submit=True):
        current_pw = st.text_input("Current password", type="password")
        new_pw = st.text_input("New password (8+ characters)", type="password")
        if st.form_submit_button("Change password"):
            try:
                api.post(
                    "/auth/password",
                    {"current_password": current_pw, "new_password": new_pw},
                )
            except api.APIError as exc:
                st.error(str(exc))
            else:
                ui.sign_out(local_only=True)
                st.success("Password changed. Please log in again.")
                st.rerun()
