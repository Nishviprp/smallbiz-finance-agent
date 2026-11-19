"""Smoke tests: every dashboard page renders against a real (in-process) API."""

from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

from dashboard import api as dash_api  # noqa: E402
from dashboard.ui import preset_range  # noqa: E402

from .conftest import SAMPLE_DIR  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")
PAGES = [
    "views/overview.py",
    "views/transactions.py",
    "views/invoices.py",
    "views/receipts.py",
    "views/upload.py",
    "views/categories.py",
    "views/chat.py",
    "views/export.py",
    "views/settings.py",
    "views/bank.py",
]


def _complete_setup(client):
    r = client.put("/settings", json={"business_name": "Bean & Bloom Café LLC", "country": "US"})
    assert r.status_code == 200, r.text


@pytest.fixture
def seeded(client):
    _complete_setup(client)
    for path, endpoint, mime in [
        (SAMPLE_DIR / "bank_statement_cafe.csv", "/uploads/statement", "text/csv"),
        (SAMPLE_DIR / "invoices" / "INV-2026-021.pdf", "/uploads/invoice", "application/pdf"),
        (SAMPLE_DIR / "receipts" / "receipt_costco.pdf", "/uploads/receipt", "application/pdf"),
    ]:
        r = client.post(
            endpoint,
            files={"file": (path.name, path.read_bytes(), mime)},
            data={"use_llm": "false"},
        )
        assert r.status_code == 200, r.text
    dash_api.set_client(client)
    yield client
    dash_api.set_client(None)


def _run(page: str | None = None):
    at = st_testing.AppTest.from_file(APP, default_timeout=60)
    at.run()
    if page:
        at.switch_page(page)
        at.run()
    return at


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_with_data(seeded, page):
    at = _run(page)
    assert not at.exception, [e.value for e in at.exception]
    assert at.title


def test_overview_kpis(seeded):
    at = _run("views/overview.py")
    labels = [m.label for m in at.metric]
    assert labels[:3] == ["Income", "Expenses", "Net profit"]
    assert at.metric[0].value == "$116,463"


def test_pages_render_empty(client):
    _complete_setup(client)
    dash_api.set_client(client)
    try:
        for page in PAGES:
            at = _run(page)
            assert not at.exception, (page, [e.value for e in at.exception])
    finally:
        dash_api.set_client(None)


def test_api_down_shows_error(monkeypatch):
    import httpx

    dash_api.set_client(httpx.Client(base_url="http://127.0.0.1:9", timeout=0.5))
    try:
        at = _run()
        assert at.error and "Cannot reach the API" in at.error[0].value
    finally:
        dash_api.set_client(None)


def test_preset_range():
    import datetime as dt

    first, last = dt.date(2025, 3, 10), dt.date(2026, 6, 30)
    assert preset_range("Latest month", first, last) == (dt.date(2026, 6, 1), last)
    assert preset_range("Last 3 months", first, last) == (dt.date(2026, 4, 1), last)
    assert preset_range("Year to date", first, last) == (dt.date(2026, 1, 1), last)
    assert preset_range("Last 12 months", first, last) == (dt.date(2025, 7, 1), last)
    assert preset_range("All time", first, last) == (first, last)


def test_first_run_shows_setup_wizard(client):
    dash_api.set_client(client)
    try:
        at = _run()
        assert not at.exception
        assert "Welcome" in at.title[0].value
        at.text_input[0].input("Joe's Coffee LLC")
        at.button[0].click()
        at.run()
        assert not at.exception
        assert client.get("/settings").json()["business_name"] == "Joe's Coffee LLC"
        assert at.title[0].value == "Overview"
    finally:
        dash_api.set_client(None)


def test_accounts_mode_login_gate(monkeypatch):
    from fastapi.testclient import TestClient

    from finagent.config import get_settings
    from finagent.main import create_app

    monkeypatch.setenv("AUTH_MODE", "accounts")
    get_settings.cache_clear()
    with TestClient(create_app()) as api_client:
        dash_api.set_client(api_client)
        try:
            at = _run()
            assert not at.exception
            assert at.title[0].value == "SmallBiz Finance Agent"  # login screen
            r = api_client.post(
                "/auth/signup",
                json={"email": "a@b.example", "password": "long enough pw", "business_name": "A"},
            )
            at.session_state["auth_token"] = r.json()["token"]
            at.run()
            assert not at.exception
            assert at.title[0].value == "Overview"
            at.session_state["auth_token"] = "revoked-or-forged"
            at.run()
            assert at.title[0].value == "SmallBiz Finance Agent"  # bounced back to login
        finally:
            dash_api.set_client(None)


def test_bank_page_with_connections(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from finagent.config import get_settings
    from finagent.main import create_app
    from finagent.services import crypto, plaid

    from .fake_plaid import FakePlaid

    fake = FakePlaid()
    monkeypatch.setenv("PLAID_CLIENT_ID", "x")
    monkeypatch.setenv("PLAID_SECRET", "y")
    monkeypatch.setenv("BANK_SYNC_HOURS", "0")
    monkeypatch.setenv("SECRET_KEY_FILE", str(tmp_path / "k"))
    get_settings.cache_clear()
    crypto.reset_cache()
    monkeypatch.setattr(plaid, "_test_transport", fake.transport())
    with TestClient(create_app()) as c:
        _complete_setup(c)
        c.post("/bank/sandbox-connect")
        dash_api.set_client(c)
        try:
            at = _run("views/bank.py")
            assert not at.exception, [e.value for e in at.exception]
            assert "First Platypus Bank (test)" in " ".join(m.value for m in at.markdown)
            at.button(key="sync1").click()
            at.run()
            assert not at.exception
        finally:
            dash_api.set_client(None)
            crypto.reset_cache()
