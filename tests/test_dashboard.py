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
]


@pytest.fixture
def seeded(client):
    for path, endpoint, mime in [
        (SAMPLE_DIR / "bank_statement_cafe.csv", "/uploads/statement", "text/csv"),
        (SAMPLE_DIR / "invoices" / "INV-2026-021.pdf", "/uploads/invoice", "application/pdf"),
        (SAMPLE_DIR / "receipts" / "receipt_makro.pdf", "/uploads/receipt", "application/pdf"),
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
    assert at.metric[0].value == "£118,701"


def test_pages_render_empty(client):
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
