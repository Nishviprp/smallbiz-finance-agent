"""Bank feeds against the in-memory fake Plaid (tests/fake_plaid.py)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from finagent.config import get_settings
from finagent.db import get_session_factory
from finagent.models import BankConnection
from finagent.services import crypto, plaid

from .fake_plaid import txn


@pytest.fixture
def fake(monkeypatch, tmp_path):
    from .fake_plaid import FakePlaid

    f = FakePlaid()
    monkeypatch.setenv("PLAID_CLIENT_ID", "test-client")
    monkeypatch.setenv("PLAID_SECRET", "test-secret")
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    monkeypatch.setenv("BANK_SYNC_HOURS", "0")
    monkeypatch.setenv("SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    get_settings.cache_clear()
    crypto.reset_cache()
    monkeypatch.setattr(plaid, "_test_transport", f.transport())
    yield f
    crypto.reset_cache()


@pytest.fixture
def bank_client(fake):
    from finagent.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _connect(c):
    r = c.post("/bank/sandbox-connect")
    assert r.status_code == 200, r.text
    return r.json()


def _txns(c, **params):
    return c.get("/transactions", params={"limit": 1000, **params}).json()["items"]


def test_not_configured(client):
    s = client.get("/bank/status").json()
    assert s["configured"] is False and s["connections"] == []
    assert client.post("/bank/sandbox-connect").status_code == 503


def test_connect_imports_and_categorizes(bank_client, fake):
    r = _connect(bank_client)
    conn, sync = r["connection"], r["sync"]
    assert conn["institution"] == "First Platypus Bank (test)"
    assert [a["mask"] for a in conn["accounts"]] == ["0000", "1111"]
    assert sync["added"] == 6 and sync["pending"] == 1  # pending COSTCO skipped
    assert "/transactions/sync" in fake.calls

    items = {t["description"]: t for t in _txns(bank_client)}
    assert items["SQUARE INC DEPOSIT"]["amount"] == 850.25  # sign flipped: money in
    assert items["SYSCO NEW JERSEY"]["amount"] == -412.50
    assert items["SYSCO NEW JERSEY"]["category_source"] == "keyword"
    legal = items["ACME LEGAL PARTNERS"]
    assert (legal["category_name"], legal["category_source"]) == ("Professional Fees", "bank")
    assert items["MYSTERY VENDOR 22"]["category_name"] is None  # no hint, no LLM in tests
    assert (
        items["SYSCO NEW JERSEY"]["account"]
        == "First Platypus Bank (test) Business Checking ••0000"
    )
    # A client payment labelled TRANSFER_IN by Plaid must not be hidden as a transfer.
    assert items["RIVERSIDE BOOK CLUB PAYMENT"]["category_name"] != "Transfers"


def test_access_token_is_encrypted_at_rest(bank_client, fake):
    _connect(bank_client)
    token = next(iter(fake.items))
    with get_session_factory()() as db:
        db.info["global_access"] = True
        stored = db.scalars(select(BankConnection.access_token_enc)).one()
    assert token not in stored
    assert crypto.decrypt(stored) == token


def test_resync_is_idempotent_and_applies_changes(bank_client, fake):
    _connect(bank_client)
    again = bank_client.post("/bank/sync", json={}).json()["results"][0]
    assert again["added"] == 0 and again["status"] == "ok"

    fake.queue(
        added=[
            txn("t7", "2026-07-08", "COSTCO WHSE", 75.10),  # the pending one has posted
            txn("t8", "2026-07-09", "UBER TRIP", 23.40, pfc="TRANSPORTATION"),
        ],
        modified=[txn("t2", "2026-07-02", "SYSCO NEW JERSEY", 420.00)],
        removed=[{"transaction_id": "t3"}],
    )
    r = bank_client.post("/bank/sync", json={}).json()["results"][0]
    assert (r["added"], r["updated"], r["removed"]) == (2, 1, 1)
    items = {t["description"]: t for t in _txns(bank_client)}
    assert items["SYSCO NEW JERSEY"]["amount"] == -420.00
    assert "Starbucks" not in items
    assert items["COSTCO WHSE"]["amount"] == -75.10
    assert len(items) == 7


def test_user_category_survives_bank_edit(bank_client, fake):
    _connect(bank_client)
    t = next(t for t in _txns(bank_client) if t["description"] == "MYSTERY VENDOR 22")
    cats = {c["name"]: c["id"] for c in bank_client.get("/categories").json()}
    bank_client.patch(f"/transactions/{t['id']}", json={"category_id": cats["Office Supplies"]})
    fake.queue(modified=[txn("t6", "2026-07-07", "MYSTERY VENDOR 22", 21.00)])
    bank_client.post("/bank/sync", json={})
    after = bank_client.get(f"/transactions/{t['id']}").json()
    assert after["amount"] == -21.00 and after["category_name"] == "Office Supplies"


def test_statement_lines_are_not_duplicated(bank_client, fake):
    csv = b"Date,Description,Amount\n2026-07-02,Sysco NJ card 4421,-412.50\n"
    bank_client.post(
        "/uploads/statement", files={"file": ("s.csv", csv, "text/csv")}, data={"use_llm": "false"}
    )
    r = _connect(bank_client)
    assert r["sync"]["skipped_duplicates"] == 1
    assert sum(1 for t in _txns(bank_client) if t["amount"] == -412.50) == 1


def test_pagination_restart_on_mutation(bank_client, fake):
    fake.page_size = 2
    fake.mutate_once = True
    r = _connect(bank_client)
    assert r["sync"]["added"] == 6


def test_login_required_then_repair(bank_client, fake):
    conn = _connect(bank_client)["connection"]
    fake.fail["/transactions/sync"] = {
        "code": "ITEM_LOGIN_REQUIRED",
        "display": "Please sign in to your bank again.",
    }
    r = bank_client.post("/bank/sync", json={}).json()["results"][0]
    assert r["status"] == "needs_reauth" and "sign in" in r["error"]
    status = bank_client.get("/bank/status").json()["connections"][0]
    assert status["status"] == "needs_reauth"

    lt = bank_client.post("/bank/link-token", params={"connection_id": conn["id"]})
    assert lt.status_code == 200
    assert fake.link_requests[-1]["access_token"].startswith("access-sandbox-")  # update mode
    assert "products" not in fake.link_requests[-1]
    ok = bank_client.post("/bank/sync", json={"connection_id": conn["id"]}).json()["results"][0]
    assert ok["status"] == "ok"


def test_link_token_for_new_connection(bank_client, fake):
    r = bank_client.post("/bank/link-token")
    assert r.status_code == 200 and r.json()["link_token"].startswith("link-sandbox-")
    req = fake.link_requests[-1]
    assert req["products"] == ["transactions"] and req["country_codes"] == ["US", "CA"]


def test_connect_with_public_token_from_link(bank_client, fake):
    r = bank_client.post(
        "/bank/connect",
        json={"public_token": "public-sandbox-from-link", "institution_name": "Chase"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["connection"]["institution"] == "Chase"


def test_bank_payment_marks_invoice_paid(bank_client, fake):
    inv = bank_client.post(
        "/invoices",
        json={"number": "INV-9", "client": "Riverside Book Club", "issue_date": "2026-06-20",
              "amount": 486.00},
    ).json()  # fmt: skip
    r = _connect(bank_client)
    assert r["sync"]["invoices_paid"] == 1
    assert bank_client.get(f"/invoices/{inv['id']}").json()["status"] == "paid"


def test_disconnect_keeps_transactions(bank_client, fake):
    conn = _connect(bank_client)["connection"]
    assert bank_client.delete(f"/bank/connections/{conn['id']}").status_code == 204
    assert bank_client.get("/bank/status").json()["connections"] == []
    assert len(_txns(bank_client)) == 6
    assert fake.items == {}  # item removed at Plaid
    assert bank_client.delete(f"/bank/connections/{conn['id']}").status_code == 404


def test_wrong_encryption_key_is_reported(bank_client, fake, monkeypatch, tmp_path):
    _connect(bank_client)
    from cryptography.fernet import Fernet

    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    crypto.reset_cache()
    r = bank_client.post("/bank/sync", json={}).json()["results"][0]
    assert r["status"] == "error" and "encryption key" in r["error"]


def test_background_sync_respects_businesses(fake, monkeypatch):
    """sync_due_everywhere syncs each business's connections inside its own scope."""
    from finagent.main import create_app
    from finagent.services.auth import limiter
    from finagent.services.banking import sync_due_everywhere

    monkeypatch.setenv("AUTH_MODE", "accounts")
    get_settings.cache_clear()
    limiter.reset()
    with TestClient(create_app()) as c:
        heads = []
        for email in ("a@x.example", "b@x.example"):
            r = c.post(
                "/auth/signup",
                json={"email": email, "password": "long enough pw", "business_name": email},
            )
            heads.append({"Authorization": f"Bearer {r.json()['token']}"})
        c.post("/bank/sandbox-connect", headers=heads[0])
        c.post("/bank/sandbox-connect", headers=heads[1])
        for token in list(fake.items):
            fake.queue(token, added=[txn("n1", "2026-07-10", "NEW SALE", -10.0)])
        assert sync_due_everywhere(max_age_hours=0) == 2
        for h in heads:
            descs = [t["description"] for t in c.get("/transactions", headers=h).json()["items"]]
            assert descs.count("NEW SALE") == 1
            assert len(c.get("/bank/status", headers=h).json()["connections"]) == 1
        # B cannot see or remove A's connection
        a_conn = c.get("/bank/status", headers=heads[0]).json()["connections"][0]["id"]
        assert c.delete(f"/bank/connections/{a_conn}", headers=heads[1]).status_code == 404
        r = c.post("/bank/sync", headers=heads[1], json={"connection_id": a_conn})
        assert r.status_code == 404
        r = c.post("/bank/link-token", headers=heads[1], params={"connection_id": a_conn})
        assert r.status_code == 404
