import datetime as dt

import streamlit as st

from dashboard import api, ui
from dashboard.plaid_link import plaid_link

st.title("Bank accounts")
st.caption(
    "Connect your business bank once — new transactions then arrive and get categorized "
    "automatically. Read-only access through Plaid; we never see your bank password."
)

status = ui.call(api.get, "/bank/status")
if not status["configured"]:
    st.info(
        "Bank feeds aren't switched on for this server yet. The person who runs it needs free "
        "Plaid keys: create an account at **dashboard.plaid.com**, copy the *client_id* and the "
        "*Sandbox secret*, then add `PLAID_CLIENT_ID` and `PLAID_SECRET` to the `.env` file and "
        "restart. Until then, upload CSV/PDF statements on **Upload**.",
        icon=":material/account_balance:",
    )
    st.stop()


def show_sync(results: list[dict]) -> None:
    for r in results:
        if r["status"] != "ok":
            st.error(f"**{r['institution']}**: {r['error']}", icon=":material/error:")
            continue
        extra = []
        if r["skipped_duplicates"]:
            extra.append(f"{r['skipped_duplicates']} already imported from statements")
        if r["pending"]:
            extra.append(f"{r['pending']} pending (added once they post)")
        if r["invoices_paid"]:
            extra.append(f"{r['invoices_paid']} invoice(s) marked paid")
        st.success(
            f"**{r['institution']}** — {r['added']} new, {r['updated']} updated, "
            f"{r['removed']} removed" + (f" · {' · '.join(extra)}" if extra else ""),
            icon=":material/sync:",
        )


def first_time(value: dict | None) -> dict | None:
    """Component values persist across reruns; handle each Plaid result exactly once."""
    if not value:
        return None
    marker = value.get("public_token") or value.get("error")
    done = st.session_state.setdefault("plaid_handled", set())
    if marker in done:
        return None
    done.add(marker)
    return value


def when(ts: str | None) -> str:
    if not ts:
        return "never"
    t = dt.datetime.fromisoformat(ts)
    return f"{ui.fmt_date(t.date())} {t:%H:%M} UTC"


# ---- Connected banks ---------------------------------------------------------------
conns = status["connections"]
if conns:
    c1, _ = st.columns([1, 4])
    if c1.button("Sync all now", type="primary", icon=":material/sync:"):
        with st.spinner("Fetching new transactions…"):
            st.session_state.bank_result = ui.call(api.post, "/bank/sync", {})["results"]
        st.rerun()
    if "bank_result" in st.session_state:
        show_sync(st.session_state.pop("bank_result"))

    for c in conns:
        with st.container(border=True):
            badge = {
                "ok": ":green[● Connected]",
                "needs_reauth": ":orange[● Needs you to sign in again]",
                "error": ":red[● Error]",
            }.get(c["status"], c["status"])
            st.markdown(
                f"#### {c['institution']}  \n{badge} · last synced {when(c['last_synced_at'])}"
            )
            for a in c["accounts"]:
                st.caption(
                    f"{a['name']} ••{a['mask'] or '----'} · {a['subtype'] or a['type'] or ''}"
                )
            if c["error"]:
                st.warning(c["error"])
            b1, b2, b3, _ = st.columns([1, 1.2, 1, 3])
            if b1.button("Sync now", key=f"sync{c['id']}", icon=":material/sync:"):
                with st.spinner("Syncing…"):
                    st.session_state.bank_result = ui.call(
                        api.post, "/bank/sync", {"connection_id": c["id"]}
                    )["results"]
                st.rerun()
            if c["status"] == "needs_reauth":
                tok_key = f"relink_token_{c['id']}"
                if tok_key not in st.session_state:
                    st.session_state[tok_key] = ui.call(
                        api.post, f"/bank/link-token?connection_id={c['id']}"
                    )["link_token"]
                with b2:
                    done = first_time(
                        plaid_link(
                            st.session_state[tok_key], label="Sign in again", key=f"relink{c['id']}"
                        )
                    )
                if done and done.get("public_token"):
                    st.session_state.pop(tok_key, None)
                    st.session_state.bank_result = ui.call(
                        api.post, "/bank/sync", {"connection_id": c["id"]}
                    )["results"]
                    st.rerun()
            with b3.popover("Disconnect", icon=":material/link_off:"):
                st.caption("Stops new transactions. Ones already imported stay in your books.")
                if st.button("Yes, disconnect", key=f"rm{c['id']}", type="primary"):
                    ui.call(api.delete, f"/bank/connections/{c['id']}")
                    st.rerun()

# ---- Connect -----------------------------------------------------------------------
st.subheader("Connect a bank" if not conns else "Connect another bank")
if status["env"] == "sandbox":
    st.caption(
        "Sandbox mode: in the Plaid window pick any bank and sign in with **user_good / pass_good**, "
        "or skip the window entirely:"
    )
    if st.button("Connect Plaid's test bank", icon=":material/science:"):
        with st.spinner("Connecting the test bank…"):
            r = ui.call(api.post, "/bank/sandbox-connect")
        st.session_state.bank_result = [r["sync"]]
        st.rerun()

if "link_token" not in st.session_state:
    try:
        with st.spinner("Contacting Plaid…"):
            st.session_state.link_token = api.post("/bank/link-token")["link_token"]
    except api.APIError as exc:
        st.warning(f"Couldn't open the Plaid window: {exc}", icon=":material/warning:")
if st.session_state.get("link_token"):
    result = first_time(
        plaid_link(
            st.session_state.link_token, key=f"plaid_new_{st.session_state.link_token[-12:]}"
        )
    )
    if result:
        if result.get("public_token"):
            with st.spinner("Connecting and importing your transactions…"):
                r = ui.call(
                    api.post,
                    "/bank/connect",
                    {
                        "public_token": result["public_token"],
                        "institution_name": result.get("institution"),
                    },
                )
            st.session_state.pop("link_token", None)
            st.session_state.bank_result = [r["sync"]]
            st.rerun()
        elif result.get("error"):
            st.warning(result["error"])

hours = status["auto_sync_hours"]
st.caption(
    f"New transactions are fetched automatically every {hours:g} hours while the app is running."
    if hours
    else "Automatic syncing is off — use *Sync now*."
)
