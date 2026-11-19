import streamlit as st

from dashboard import api, ui

st.title("Welcome to SmallBiz Finance Agent 👋")
st.markdown(
    "Free AI bookkeeping that runs on your own computer — your financial data never leaves it.\n\n"
    "Tell us a little about your business. You can change this any time in **Settings**."
)

current = ui.call(api.get, "/settings")
body = ui.profile_form(current, submit_label="Save and start", key="setup")
if body:
    ui.call(api.put, "/settings", body)
    st.session_state.pop("currency", None)
    st.rerun()
