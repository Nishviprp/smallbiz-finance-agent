# Changelog

## v0.1.0 — 2026-11-17

First public release.

### Added
- **Import**: bank statement CSV (any bank layout, UK/US/EU formats, duplicate-safe) and PDF
  statements (tables, text with running-balance sign detection, LLM fallback).
- **Categorization**: user rules → ~240 built-in merchant keywords → LLM (Ollama, OpenAI or
  Anthropic Claude), validated against your categories; learns rules from your corrections.
- **Receipts**: photos and PDFs read by vision LLM, Tesseract OCR or pattern matching, and linked
  to the matching bank transaction.
- **Invoices**: upload or add sales invoices; automatic paid-matching from bank payments;
  overdue / due-soon alerts and aging buckets.
- **Reports**: KPI summary vs previous period, monthly cash flow, profit & loss by category, top
  expenses and suppliers, category trends.
- **Dashboard** (Streamlit): Overview, Transactions, Invoices, Receipts, Ask your books, Tax
  export, Upload, Categories & rules.
- **Chat with your books**: read-only tool routing, numbers computed in code, offline rule engine.
- **Tax export**: tax-year aware PDF tax pack, transaction ledger CSV, category summary CSV, ZIP.
- **Deployment**: Docker Compose (optional Ollama and Postgres profiles); SQLite or Postgres.
- **Quality**: 110+ tests, CI on Python 3.10–3.12, Postgres 16 and a Docker end-to-end smoke test.
