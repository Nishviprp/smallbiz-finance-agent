# Changelog

## v0.3.1 — 2026-11-22

Tested against the real Plaid sandbox.

### Fixed
- Launcher crashed with "Permission denied" when run with a system-wide Python
  (`python launch.py` without the `.venv`): it now keeps its package checksum in `data/`.
- Bank accounts page stayed blank while waiting for Plaid, and hid everything if Plaid returned
  an error. The test-bank button now shows first and Plaid errors appear as a clear warning.

## v0.3.0 — 2026-11-18

Host it online: one website, many businesses, automatic bank feeds.

### Added
- **Accounts mode** (`AUTH_MODE=accounts`): sign up / log in page, each business gets its own
  private books, "stay logged in" for `SESSION_DAYS`, change password in Settings, CLI to list
  users and reset passwords. Passwords are scrypt-hashed, session tokens stored only as hashes,
  repeated wrong passwords are rate-limited.
- **Tenant isolation built into the database layer**: every query is automatically scoped to the
  logged-in business; unscoped or cross-business reads and writes are refused.
- **Plaid bank feeds**: connect a bank with Plaid Link (or the sandbox test bank in one click),
  incremental sync via `/transactions/sync`, auto-sync every `BANK_SYNC_HOURS`, Plaid categories
  used as hints, pending lines skipped, edits/removals from the bank applied, lines already
  imported from a statement skipped, re-login prompt when a bank needs it, disconnect keeps history.
- Bank tokens encrypted at rest (`ENCRYPTION_KEY` or auto-created `data/secret.key`).
- **Production hosting**: `deploy/docker-compose.prod.yml` (Caddy auto-HTTPS + Postgres, only
  ports 80/443 exposed), `deploy/backup.sh`, and [docs/HOSTING.md](docs/HOSTING.md).

### Changed
- `local` mode (the default) works exactly as before — no login.
- Uploaded files are stored per business (`data/uploads/business_<id>/`).

### Upgrading from v0.2
- The database layout changed. On first start a v0.2 SQLite database is moved aside to
  `*.v02-backup.db` and a fresh one is created — load the demo or re-upload your files.
  (Postgres users: drop and recreate the database.)

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
