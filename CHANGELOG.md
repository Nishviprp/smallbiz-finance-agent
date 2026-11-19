# Changelog

## v0.2.0 — 2026-11-18

Ready for non-technical small-business owners, with US defaults.

### Added
- **One-click launcher**: double-click `start.bat` (Windows) or `start.command` (macOS). First run
  creates a private Python environment, installs everything and adds a desktop shortcut on Windows;
  later runs start in seconds and open the browser. Closing the window stops the app.
- **First-run setup wizard**: business name and country set currency, date format and tax year
  (US, Canada, UK, Ireland/Eurozone, Australia, New Zealand, India). Stored in the database.
- **Settings page**: edit the business profile, relabel existing records to a new currency,
  load the demo café in one click, and "start fresh" (delete all books, keep settings).
- Dates are shown in the business's style (`Jan 5, 2026` in the US) in the dashboard, chat and
  tax pack.
- More US merchant keywords (PSE&G, Suez/Veolia water, Home Depot, Lowe's, IRS EFTPS, state
  divisions of taxation, bank maintenance fees and more).

### Changed
- **Defaults are now US**: USD, MM/DD dates, January tax year. The demo is now a café in
  Jersey City, NJ (Square, Sysco, Gusto, NJ sales tax).
- Dashboard binds to this computer only (`127.0.0.1`) when started with the launcher.
- Upload logic moved to a shared service (`finagent/services/ingest.py`).

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
