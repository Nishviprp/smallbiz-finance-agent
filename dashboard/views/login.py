import streamlit as st

from dashboard import api, ui

_, mid, _ = st.columns([1, 1.4, 1])
with mid:
    st.title("SmallBiz Finance Agent")
    st.caption(
        "Free AI bookkeeping for small businesses — your books stay private to your account."
    )

    health = st.session_state.get("health", {})
    tabs = ["Log in", "Create account"] if health.get("allow_signup", True) else ["Log in"]
    choice = st.segmented_control("Account", tabs, default="Log in", label_visibility="collapsed")

    if choice == "Log in":
        with st.form("login"):
            email = st.text_input("Email", autocomplete="email")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")
        if submitted:
            try:
                r = api.post("/auth/login", {"email": email, "password": password})
            except api.APIError as exc:
                st.error(str(exc), icon=":material/lock:")
            else:
                ui.sign_in(r["token"])
                st.rerun()
        st.caption("Forgot your password? Ask the person who runs this server to reset it.")
    else:
        meta = ui.call(api.get, "/settings/countries")
        countries = meta["countries"]
        with st.form("signup"):
            business = st.text_input("Business name", placeholder="Joe's Coffee LLC")
            country = st.selectbox(
                "Where is your business?",
                list(countries),
                format_func=lambda c: countries[c]["name"],
            )
            name = st.text_input("Your name")
            email = st.text_input("Email", autocomplete="email")
            password = st.text_input(
                "Password (8+ characters)", type="password", autocomplete="new-password"
            )
            submitted = st.form_submit_button("Create account", type="primary", width="stretch")
        if submitted:
            try:
                r = api.post(
                    "/auth/signup",
                    {
                        "email": email,
                        "password": password,
                        "name": name,
                        "business_name": business,
                        "country": country,
                    },
                )
            except api.APIError as exc:
                st.error(str(exc), icon=":material/error:")
            else:
                ui.sign_in(r["token"])
                st.rerun()
