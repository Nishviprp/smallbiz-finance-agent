# SmallBiz Finance Agent

**Open-source AI bookkeeping for shops, cafés, freelancers and agencies — free, private, and it runs on your own computer.**

[![CI](https://github.com/Nishviprp/smallbiz-finance-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Nishviprp/smallbiz-finance-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Docker](https://img.shields.io/badge/docker-compose-2496ED)

Drop in your bank statements, receipts and invoices. The agent categorizes every transaction,
tracks who owes you money, shows where your cash goes, answers questions in plain English and
hands you a tax-ready pack at year end. Built for US small businesses (USD, IRS-style tax year) and
works anywhere — pick your country on first launch. Run it on your own computer, or
[host it as one website for many businesses](docs/HOSTING.md) with logins and automatic bank feeds.

<p align="center">
  <img src="docs/images/demo.gif" alt="SmallBiz Finance Agent demo: overview, transactions, invoices, chat and tax export" width="900">
</p>

## The problem

Small-business owners lose hours every month copying bank lines into spreadsheets, guessing
categories, chasing unpaid invoices and scrambling at tax time. Accounting software costs money
every month and sends your financial data to someone else's cloud.

SmallBiz Finance Agent does the bookkeeping grunt work for free, **locally**. Rules and a local
LLM (via Ollama) categorize transactions; OpenAI or Claude are optional. Every number is computed
by code — the AI never makes figures up.

## Features

| | |
|---|---|
| 📥 **Any bank, any format** | CSV from any bank (signed amounts, debit/credit or money-in/out columns, UK/US/EU dates and decimals) and **PDF statements**. Re-importing is safe — duplicates are skipped. |
| 🤖 **AI categorization that learns** | Your rules → ~240 built-in merchant keywords → LLM. Fix one transaction and it learns a rule for all similar ones. Hand edits are never overwritten. |
| 🧾 **Receipts** | Photo or PDF → vision AI, OCR or pattern matching → vendor, date, total, tax — auto-linked to the bank payment. |
| 📨 **Unpaid invoice tracker** | Upload sales invoices (PDF/photo) or add them by hand. Marked **paid** automatically when the money lands; overdue and due-soon alerts; aging buckets. |
| 📊 **Dashboard** | Income, expenses, net profit and cash flow vs the previous period, money in vs out, top categories and suppliers, trends, a full profit & loss statement. |
| 💬 **Chat with your books** | *"How much have we paid Sysco since March?"* — answered from your data. Works offline without AI. |
| 🧾 **Tax-ready export** | Pick a tax year → ZIP with a PDF tax pack, the full ledger with each line's tax treatment and a category summary for your accountant. |
| 🏦 **Automatic bank feeds** | Connect a bank once with **Plaid** — new transactions sync and categorize themselves every few hours. Works alongside statement uploads (no double counting). |
| 👥 **Accounts & many businesses** | Optional login mode for hosting: each business gets its own private books; owners stay logged in and their data is kept. |
| 🔒 **Private by default** | On your computer: a SQLite file on your disk, no login, no telemetry. Hosted: Postgres, hashed passwords, encrypted bank tokens. |

<table>
  <tr>
    <td><img src="docs/images/overview-charts.png" alt="Dashboard charts"></td>
    <td><img src="docs/images/transactions.png" alt="Transactions review table"></td>
  </tr>
  <tr>
    <td><img src="docs/images/invoices.png" alt="Unpaid invoice alerts"></td>
    <td><img src="docs/images/tax-export.png" alt="Tax export"></td>
  </tr>
</table>

## Quickstart

### Option A — One click (Windows / Mac, no technical skills needed)

1. Install **Python 3.10+** from [python.org](https://www.python.org/downloads/) — on Windows tick
   **"Add python.exe to PATH"** on the first screen.
2. [Download this project as a ZIP](https://github.com/Nishviprp/smallbiz-finance-agent/archive/refs/heads/main.zip)
   and unzip it anywhere (e.g. your Documents folder).
3. Double-click **`start.bat`** (Windows) or **`start.command`** (Mac).

The first launch installs everything (a few minutes) and adds a **SmallBiz Finance** shortcut to
your Windows desktop. After that it opens in your browser in seconds. A short welcome screen asks
for your business name and country; then click **Load the demo café** to explore, or upload your
own bank statement. Close the black window to stop the app.

<p align="center"><img src="docs/images/welcome.png" alt="First-run welcome screen" width="720"></p>

### Option B — Docker (one command)

```bash
git clone https://github.com/Nishviprp/smallbiz-finance-agent.git
cd smallbiz-finance-agent
docker compose up -d
```

Open **http://localhost:8501** → **Upload** → import `sample_data/bank_statement_cafe.csv`.

Add free local AI (downloads the model once, ~5 GB):

```bash
docker compose --profile ai up -d
docker compose exec ollama ollama pull llama3.1:8b
```

Use Postgres instead of SQLite: put
`DATABASE_URL=postgresql+psycopg://finagent:finagent@db:5432/finagent` in `.env`, then
`docker compose --profile postgres up -d`.

### Option C — Python, manually (3.10+)

```bash
git clone https://github.com/Nishviprp/smallbiz-finance-agent.git
cd smallbiz-finance-agent
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt -r dashboard/requirements.txt
cp .env.example .env                   # Windows: copy .env.example .env
```

Then run the API and the dashboard in **two terminals**:

```bash
python -m uvicorn finagent.main:app --reload       # terminal 1 → http://localhost:8000/docs
python -m streamlit run dashboard/app.py           # terminal 2 → http://localhost:8501
```

### Try the demo café

One click: **Load the demo café** (on the empty Overview, or in **Settings**) imports six months of
*Bean & Bloom Café LLC* in Jersey City, NJ. To try uploads by hand, use the files in `sample_data/`:

1. **Upload → Bank statement** → `bank_statement_cafe.csv` (or the January `.pdf`)
2. **Upload → Receipt** → `receipts/receipt_home_depot.png` — linked to its bank payment
3. **Upload → Sales invoice** → `invoices/INV-2026-014.pdf` — instantly **paid** (the payment is in the statement)
4. **Upload → Sales invoice** → `invoices/INV-2026-021.pdf` — flagged **overdue**
5. **Ask your books** → *"What are our biggest expenses?"*

Done exploring? **Settings → Start fresh** clears the demo (your settings and categories stay).

### Option D — Host it online for many businesses

One website, many businesses, HTTPS and Postgres — about $5–10/month on a small server.
Follow **[docs/HOSTING.md](docs/HOSTING.md)** (`deploy/` has the production Compose file, Caddy
config and a backup script).

### Optional extras

- **Free local AI** — install [Ollama](https://ollama.com) and run `ollama pull llama3.1:8b`.
  Without it, set `LLM_PROVIDER=none`: built-in keywords still categorize ~88% of the demo lines,
  and chat still works.
- **Paid AI** — `LLM_PROVIDER=openai` + `OPENAI_API_KEY`, or `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`.
- **Bank feeds** — get free sandbox keys at [dashboard.plaid.com](https://dashboard.plaid.com),
  set `PLAID_CLIENT_ID` / `PLAID_SECRET`, then **Bank accounts → Connect a bank**
  (test login `user_good` / `pass_good`). Real banks need Plaid production approval.
- **Receipt photos** — install [Tesseract OCR](https://tesseract-ocr.github.io/tessdoc/Installation.html)
  (Windows: [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki)), or set
  `OLLAMA_VISION_MODEL=llama3.2-vision`. PDFs with a text layer need neither. Docker includes Tesseract.

## Configuration

**Business profile** (name, country, currency, date format, tax year) is set in the app — on the
welcome screen and later in **Settings**. Country presets: United States (USD, MM/DD, Jan 1 tax
year), Canada, United Kingdom (GBP, DD/MM, Apr 6), Ireland/Eurozone, Australia (Jul 1), New Zealand
and India — every value stays editable. Amounts are never converted; the currency is a label.

Technical settings live in `.env` (copy `.env.example`):

| Variable | Default | What it does |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` · `openai` · `anthropic` · `none` |
| `DATABASE_URL` | SQLite in `./data` | Any SQLAlchemy URL, e.g. Postgres |
| `INVOICE_ALERT_DAYS` | `7` | "Due soon" window |
| `AUTH_MODE` | `local` | `local` = no login, one business · `accounts` = login, many businesses |
| `ALLOW_SIGNUP` | `true` | Let new businesses create accounts (accounts mode) |
| `SESSION_DAYS` | `30` | How long "stay logged in" lasts |
| `PLAID_CLIENT_ID` / `PLAID_SECRET` | — | Turn on bank feeds |
| `PLAID_ENV` | `sandbox` | `sandbox` (test banks) · `production` |
| `BANK_SYNC_HOURS` | `6` | Auto-sync interval (`0` = manual only) |
| `ENCRYPTION_KEY` | auto | Encrypts bank tokens; auto-created in `data/secret.key` — back it up |

## How it works

```
CSV / PDF statement ─┐                      ┌─► Dashboard (Streamlit)
Receipt photo / PDF ─┼─► FastAPI ─► SQLite ─┼─► Chat with your books
Sales invoice PDF  ──┘   │  ▲       / Postgres └─► Tax pack (PDF + CSV + ZIP)
                         ▼  │
              rules → keywords → LLM (Ollama / OpenAI / Claude)
```

**Categorization.** 1) Your rules, created automatically when you correct a transaction.
2) Built-in keywords for ~260 common US and UK merchants (Square, Sysco, Gusto, IRS, PSE&G,
Verizon, Home Depot, AWS, Uber…), instant and
offline. 3) The LLM, in batches; every answer is checked against your category list and the
money-in/money-out direction before it is saved. Anything still unknown stays **uncategorized**
for you to review — it is never silently guessed.

**The numbers.** Cash basis, the way most micro-businesses report. Income and expenses come from
income/expense categories (a refund in an expense category reduces it). Transfers, owner drawings
and loans move cash but never count as profit or loss.

**Chat.** The AI never writes SQL or touches your data. It only picks one of a few read-only
question types (summary, category total, supplier search, top expenses, monthly, invoices,
uncategorized); code computes every number and the AI words the answer from those numbers.
Without AI, a rule engine answers the same questions. Follow-ups like *"…and in March?"* work.

**Tax pack.** Categories marked *not tax deductible* (e.g. client entertainment) are listed but
not claimed; uncategorized spending is **not** claimed until you review it; unpaid invoices at
year end are listed separately for accruals-basis filers.

## API

Interactive docs at **http://localhost:8000/docs**.

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/uploads/statement` · `/uploads/receipt` · `/uploads/invoice` | Import files |
| `GET` `PATCH` | `/transactions` · `/transactions/{id}` | List / filter; fix a category (optionally learn a rule) |
| `POST` | `/transactions/recategorize` | Re-run categorization |
| `GET` `POST` `PATCH` `DELETE` | `/categories` · `/rules` | Chart of accounts and rules |
| `GET` `POST` `PATCH` `DELETE` | `/invoices` · `/receipts` | Invoices (incl. `/invoices/alerts`, `/mark-paid`) and receipts |
| `GET` | `/reports/summary` · `/monthly` · `/pnl` · `/top-expenses` · `/category-trends` | Reports |
| `POST` | `/chat` | Ask a question about your books |
| `POST` `GET` | `/auth/signup` · `/auth/login` · `/auth/logout` · `/auth/me` · `/auth/password` | Accounts (send `Authorization: Bearer <token>` in accounts mode) |
| `GET` `POST` `DELETE` | `/bank/status` · `/bank/link-token` · `/bank/connect` · `/bank/sync` · `/bank/connections/{id}` | Plaid bank feeds |
| `GET` | `/export/tax-pack.zip` · `.pdf` · `/export/transactions.csv` | Tax-ready exports |

## Development

```bash
python -m pip install -r requirements-dev.txt
pytest                                   # 160+ tests: SQLite by default
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/db pytest   # or against Postgres
ruff check . && ruff format --check .
python scripts/generate_sample_data.py   # rebuild the demo data
```

CI runs the suite on Python 3.10–3.12, against Postgres 16, and boots the full Docker Compose
stack for an end-to-end smoke test. See [CONTRIBUTING.md](CONTRIBUTING.md).

```
finagent/           FastAPI backend
  api/              routes: auth, bank, uploads, transactions, categories, rules, invoices, receipts, reports, chat, export
  ingest/           bank CSV, PDF statements, OCR / text extraction
  services/         auth, plaid + banking, crypto, categorizer, LLM clients, importer, analytics, invoices, chat, export
dashboard/          Streamlit UI (views/ = one file per page)
docker/             Dockerfiles · docker-compose.yml at the root
deploy/             production hosting: Compose + Caddy (HTTPS) + Postgres, backup script
launch.py           one-click launcher (used by start.bat / start.command / start.sh)
sample_data/        demo café: statement (CSV + PDF), receipts, invoices
tests/              pytest suite (API, parsers, categorizer, reports, chat, export, dashboard pages)
```

## Roadmap

- [x] **v0.1.0** — CSV/PDF import, AI categorization with learning rules, receipts & OCR,
  invoice tracker with auto-matching, dashboard, chat with your books, tax export, Docker
- [x] **v0.2.0** — one-click launcher, first-run setup wizard, US defaults, one-click demo,
  start-fresh reset
- [x] **v0.3.0** — accounts & many businesses on one website, Plaid bank feeds with auto-sync,
  production hosting setup (Caddy HTTPS + Postgres + backups)
- [ ] Email reminders for overdue invoices (SMTP)
- [ ] Partial invoice payments and credit notes
- [ ] VAT / sales-tax returns (UK MTD, US sales tax summaries)
- [ ] Multi-currency accounts
- [ ] UK/EU bank feeds (GoCardless open banking)
- [ ] Invite teammates / accountants to a business
- [ ] Password reset by email
- [ ] Database migrations (Alembic)

Ideas and pull requests are welcome — open an issue.

## License

[MIT](LICENSE) — free for personal and commercial use.

> ⚠️ This tool organises your records; it is not tax, legal or accounting advice. Have a qualified
> accountant review your figures before filing.
