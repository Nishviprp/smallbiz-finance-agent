from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from finagent.config import get_settings
from finagent.db import Base, get_engine, get_session_factory, init_db, reset_engine

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets a fresh database, upload dir and no LLM.

    SQLite by default; set TEST_DATABASE_URL (e.g. a Postgres URL) to run the suite against it.
    """
    pg_url = os.getenv("TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", pg_url or f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("CURRENCY", "GBP")
    get_settings.cache_clear()
    reset_engine()
    if pg_url:
        from finagent import models  # noqa: F401

        Base.metadata.drop_all(get_engine())
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
