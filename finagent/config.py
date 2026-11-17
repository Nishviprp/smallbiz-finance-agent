"""Application settings, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["ollama", "openai", "anthropic", "none"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Storage
    database_url: str = "sqlite:///./data/finagent.db"
    upload_dir: Path = Path("./data/uploads")
    max_upload_mb: int = 20

    # Business defaults
    business_name: str = "My Business"
    currency: str = "GBP"
    # First day of your tax year as MM-DD: 01-01 (US & most countries), 04-06 (UK), 07-01 (AU)
    tax_year_start: str = "01-01"
    # Used only when a statement's dates are ambiguous (e.g. 03/04/2026).
    date_dayfirst: bool = True

    # LLM
    llm_provider: LLMProvider = "ollama"
    llm_timeout_seconds: float = 90.0
    llm_batch_size: int = 25
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    # Optional: reads receipt/invoice photos directly (e.g. llama3.2-vision). Empty = use OCR.
    ollama_vision_model: str = ""
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"

    # Invoices: warn about invoices due within this many days
    invoice_alert_days: int = 7
    # Receipt ↔ bank transaction matching window
    receipt_match_days: int = 5

    # API
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
