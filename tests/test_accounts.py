"""Accounts mode: sign-up/login, sessions, and strict isolation between businesses."""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from finagent.config import get_settings
from finagent.db import TenantScopeError, get_session_factory, init_db, reset_engine
from finagent.models import AuthSession, Transaction
from finagent.services.auth import hash_password, limiter, verify_password

from .conftest import SAMPLE_DIR

PASSWORD = "correct horse battery"


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "accounts")
    get_settings.cache_clear()
    limiter.reset()
    from finagent.main import create_app

    with TestClient(create_app()) as c:
        yield c
    limiter.reset()


def signup(api, email, business, country="US"):
    r = api.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "business_name": business, "country": country},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def two_businesses(api):
    a = signup(api, "alice@cafe.example", "Alice Café")
    b = signup(api, "bob@shop.example", "Bob's Shop", country="GB")
    return a, b


# ---- passwords & sessions -----------------------------------------------------


def test_password_hashing():
    h = hash_password("s3cret-pass")
    assert h.startswith("scrypt$") and "s3cret-pass" not in h
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
    assert hash_password("same") != hash_password("same")  # salted


def test_signup_login_me_logout(api):
    h = signup(api, "Alice@Cafe.example ", "Alice Café")
    me = api.get("/auth/me", headers=h).json()
    assert me["user"]["email"] == "alice@cafe.example"
    assert me["business"]["name"] == "Alice Café"
    assert me["profile"]["setup_complete"] is True
    assert me["profile"]["currency"] == "USD"

    r = api.post("/auth/login", json={"email": "alice@cafe.example", "password": PASSWORD})
    assert r.status_code == 200
    h2 = {"Authorization": f"Bearer {r.json()['token']}"}
    assert api.get("/auth/me", headers=h2).status_code == 200

    assert api.post("/auth/logout", headers=h2).status_code == 204
    assert api.get("/auth/me", headers=h2).status_code == 401
    assert api.get("/auth/me", headers=h).status_code == 200  # other session still valid


def test_signup_validation(api):
    base = {"email": "x@y.example", "password": PASSWORD, "business_name": "X"}
    assert api.post("/auth/signup", json={**base, "email": "not-an-email"}).status_code == 400
    assert api.post("/auth/signup", json={**base, "password": "short"}).status_code == 400
    assert api.post("/auth/signup", json={**base, "country": "ZZ"}).status_code == 422
    assert api.post("/auth/signup", json=base).status_code == 201
    dup = api.post("/auth/signup", json={**base, "email": "X@Y.example"})
    assert dup.status_code == 400 and "already exists" in dup.json()["detail"]


def test_signup_can_be_disabled(api, monkeypatch):
    monkeypatch.setenv("ALLOW_SIGNUP", "false")
    get_settings.cache_clear()
    body = {"email": "x@y.example", "password": PASSWORD, "business_name": "X"}
    assert api.post("/auth/signup", json=body).status_code == 400


def test_wrong_password_and_rate_limit(api):
    signup(api, "alice@cafe.example", "Alice Café")
    bad = {"email": "alice@cafe.example", "password": "nope-nope-nope"}
    for _ in range(5):
        assert api.post("/auth/login", json=bad).status_code == 401
    assert api.post("/auth/login", json=bad).status_code == 429
    good = {"email": "alice@cafe.example", "password": PASSWORD}
    assert api.post("/auth/login", json=good).status_code == 429  # still locked


def test_tokens_stored_hashed_and_expire(api):
    h = signup(api, "alice@cafe.example", "Alice Café")
    token = h["Authorization"].split()[1]
    with get_session_factory()() as db:
        db.info["global_access"] = True
        stored = db.scalars(select(AuthSession.token_hash)).all()
        assert token not in stored
        s = db.scalars(select(AuthSession)).one()
        s.expires_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(
            minutes=1
        )
        db.commit()
    assert api.get("/auth/me", headers=h).status_code == 401


def test_change_password_signs_out_everywhere(api):
    h = signup(api, "alice@cafe.example", "Alice Café")
    r = api.post(
        "/auth/password",
        headers=h,
        json={"current_password": PASSWORD, "new_password": "brand new password"},
    )
    assert r.status_code == 204
    assert api.get("/auth/me", headers=h).status_code == 401
    ok = {"email": "alice@cafe.example", "password": "brand new password"}
    assert api.post("/auth/login", json=ok).status_code == 200


def test_requires_login(api):
    for path in ["/transactions", "/categories", "/invoices", "/receipts", "/reports/summary",
                 "/settings", "/export/tax-years", "/rules", "/auth/me"]:  # fmt: skip
        assert api.get(path).status_code == 401, path
        assert api.get(path, headers={"Authorization": "Bearer forged"}).status_code == 401
    health = api.get("/health").json()
    assert health["auth_mode"] == "accounts" and "currency" not in health


# ---- isolation ----------------------------------------------------------------


def _upload(api, headers, path, endpoint, mime):
    r = api.post(
        endpoint,
        headers=headers,
        files={"file": (path.name, path.read_bytes(), mime)},
        data={"use_llm": "false"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_businesses_cannot_see_each_others_books(api, two_businesses):
    a, b = two_businesses
    assert api.post("/settings/demo", headers=a).json()["transactions"] == 337
    a_txn = api.get("/transactions", headers=a).json()["items"][0]
    a_inv = api.get("/invoices", headers=a, params={"status": "open"}).json()[0]
    a_rec = api.get("/receipts", headers=a).json()[0]
    a_cat = api.post("/categories", headers=a, json={"name": "Alice Secret"}).json()
    a_rule = api.post(
        "/rules", headers=a, json={"pattern": "counter culture", "category_id": a_cat["id"]}
    ).json()

    # B sees nothing of A's
    assert api.get("/transactions", headers=b).json()["total"] == 0
    assert api.get("/invoices", headers=b).json() == []
    assert api.get("/receipts", headers=b).json() == []
    assert api.get("/rules", headers=b).json() == []
    assert "Alice Secret" not in {c["name"] for c in api.get("/categories", headers=b).json()}
    assert api.get("/reports/summary", headers=b).json() == {"empty": True}
    assert api.get("/reports/monthly", headers=b).json() == []
    assert api.get("/export/tax-years", headers=b).json() == []
    assert api.get("/export/transactions.csv", headers=b).status_code == 404
    chat = api.post("/chat", headers=b, json={"question": "biggest expenses?", "use_llm": False})
    assert "no transactions" in chat.json()["answer"].lower()

    # B cannot read or touch A's records by id
    assert api.get(f"/transactions/{a_txn['id']}", headers=b).status_code == 404
    assert (
        api.patch(f"/transactions/{a_txn['id']}", headers=b, json={"notes": "x"}).status_code == 404
    )
    assert api.get(f"/invoices/{a_inv['id']}", headers=b).status_code == 404
    assert api.delete(f"/invoices/{a_inv['id']}", headers=b).status_code == 404
    assert api.post(f"/invoices/{a_inv['id']}/mark-paid", headers=b, json={}).status_code == 404
    assert api.patch(f"/receipts/{a_rec['id']}", headers=b, json={"notes": "x"}).status_code == 404
    assert api.delete(f"/receipts/{a_rec['id']}", headers=b).status_code == 404
    assert (
        api.patch(f"/categories/{a_cat['id']}", headers=b, json={"name": "pwned"}).status_code
        == 404
    )
    assert api.delete(f"/categories/{a_cat['id']}", headers=b).status_code == 404
    assert api.delete(f"/rules/{a_rule['id']}", headers=b).status_code == 404
    # ...nor link A's transaction to B's receipt / invoice
    b_inv = api.post(
        "/invoices", headers=b, json={"client": "Z", "issue_date": "2026-01-01", "amount": 5}
    ).json()
    r = api.post(
        f"/invoices/{b_inv['id']}/mark-paid", headers=b, json={"transaction_id": a_txn["id"]}
    )
    assert r.status_code == 404

    # B's bulk actions don't reach A
    assert api.post("/settings/reset", headers=b, json={"confirm": "DELETE"}).status_code == 200
    api.post(
        "/transactions/recategorize",
        headers=b,
        json={"only_uncategorized": False, "use_llm": False},
    )
    api.put("/settings", headers=b, json={"currency": "GBP", "relabel_existing": True})
    assert api.get("/transactions", headers=a).json()["total"] == 337
    assert api.get("/transactions", headers=a).json()["items"][0]["currency"] == "USD"
    assert api.get(f"/invoices/{a_inv['id']}", headers=a).status_code == 200
    assert api.get("/auth/me", headers=a).json()["profile"]["currency"] == "USD"
    assert {r["pattern"] for r in api.get("/rules", headers=a).json()} == {"counter culture"}


def test_same_statement_in_two_businesses(api, two_businesses):
    """Duplicate detection is per business: B can import the file A already imported."""
    a, b = two_businesses
    csv = SAMPLE_DIR / "bank_statement_cafe.csv"
    assert _upload(api, a, csv, "/uploads/statement", "text/csv")["imported"] == 337
    assert _upload(api, b, csv, "/uploads/statement", "text/csv")["imported"] == 337
    assert _upload(api, b, csv, "/uploads/statement", "text/csv")["duplicates"] == 337


def test_invoice_matching_uses_own_payments_only(api, two_businesses):
    a, b = two_businesses
    _upload(api, a, SAMPLE_DIR / "bank_statement_cafe.csv", "/uploads/statement", "text/csv")
    # B's invoice for exactly the amount A received must NOT be marked paid by A's payment.
    inv = _upload(
        api, b, SAMPLE_DIR / "invoices" / "INV-2026-014.pdf", "/uploads/invoice", "application/pdf"
    )
    assert inv["status"] == "unpaid"
    # And A can upload an invoice with the same number as B's.
    inv_a = _upload(
        api, a, SAMPLE_DIR / "invoices" / "INV-2026-014.pdf", "/uploads/invoice", "application/pdf"
    )
    assert inv_a["status"] == "paid"


def test_categories_are_per_business(api, two_businesses):
    a, b = two_businesses
    rent_a = next(c for c in api.get("/categories", headers=a).json() if c["name"] == "Rent")
    rent_b = next(c for c in api.get("/categories", headers=b).json() if c["name"] == "Rent")
    assert rent_a["id"] != rent_b["id"]
    api.patch(f"/categories/{rent_a['id']}", headers=a, json={"name": "Shop Rent"})
    assert "Rent" in {c["name"] for c in api.get("/categories", headers=b).json()}


# ---- the safety net -----------------------------------------------------------


def test_unscoped_queries_are_refused(api):
    signup(api, "alice@cafe.example", "Alice Café")
    with get_session_factory()() as db:
        with pytest.raises(TenantScopeError):
            db.scalars(select(Transaction)).all()
        with pytest.raises(TenantScopeError):
            db.execute(select(Transaction.id)).all()


def test_cannot_write_into_another_business(api, two_businesses):
    from finagent.db import scope_session
    from finagent.models import Category

    with get_session_factory()() as db:
        scope_session(db, 1)
        db.add(Category(name="sneaky", business_id=2))
        with pytest.raises(TenantScopeError):
            db.flush()


def test_old_v02_database_is_backed_up(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY, description TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    get_settings.cache_clear()
    reset_engine()
    init_db()
    assert (tmp_path / "old.v02-backup.db").exists()
    with get_session_factory()() as db:
        db.info["global_access"] = True
        assert db.scalars(select(Transaction)).all() == []


def test_cli_reset_password_and_list(api, monkeypatch, capsys):
    from finagent import cli

    signup(api, "alice@cafe.example", "Alice Café")
    answers = iter(["a fresh password", "a fresh password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(answers))
    assert cli.main(["reset-password", "alice@cafe.example"]) == 0
    ok = {"email": "alice@cafe.example", "password": "a fresh password"}
    assert api.post("/auth/login", json=ok).status_code == 200
    assert cli.main(["list-users"]) == 0
    assert "alice@cafe.example" in capsys.readouterr().out
