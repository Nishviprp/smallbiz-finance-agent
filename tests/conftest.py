from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finagent.config import get_settings
from finagent.db import get_session_factory, init_db, reset_engine

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets a fresh SQLite DB, upload dir and no LLM."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("CURRENCY", "GBP")
    get_settings.cache_clear()
    reset_engine()
    yield
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def db():
    init_db()
    with get_session_factory()() as session:
        yield session


@pytest.fixture
def client():
    from finagent.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def sample_csv() -> bytes:
    return (SAMPLE_DIR / "bank_statement_cafe.csv").read_bytes()
