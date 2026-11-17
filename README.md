# SmallBiz Finance Agent

**Open-source AI bookkeeping for shops, cafés, freelancers and agencies — runs free on your own machine.**

[![CI](https://github.com/Nishviprp/smallbiz-finance-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Nishviprp/smallbiz-finance-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

> 🚧 **Status: under active development (Phase 2 of 5 complete).** See [Roadmap](#roadmap).

## The problem

Small-business owners lose hours every month copying bank lines into spreadsheets, guessing
categories, chasing unpaid invoices and scrambling at tax time. Accounting SaaS costs money every
month and sends your financial data to someone else's cloud.

**SmallBiz Finance Agent** imports your bank statements, categorizes every transaction (offline
rules first, then a local LLM), and learns from your corrections — your data stays on your machine.

<!-- Demo GIF goes here -->
<p align="center"><i>Demo GIF coming soon</i></p>

## Features

| | Feature | Status |
|---|---|---|
| 📥 | Import bank statements from **any bank's CSV** (debit/credit or signed amounts, UK/US/EU formats) | ✅ |
| 🔁 | Safe re-imports — duplicate lines are detected and skipped | ✅ |
| 🤖 | AI categorization: your rules → built-in merchant keywords → LLM (Ollama / OpenAI / Claude) | ✅ |
| ✏️ | Editable categories; fix one transaction and it **learns a rule** for the rest | ✅ |
| 📄 | **PDF bank statements** (tables or text, sign fixed from running balance; AI fallback) | ✅ |
| 🧾 | **Receipts** from photos or PDFs (vision AI → OCR → patterns), auto-linked to the bank line | ✅ |
| 📨 | **Invoices** from PDF/photo or manual entry; auto-marked **paid** when the money lands | ✅ |
| ⏰ | Unpaid invoice tracker: overdue / due-soon alerts, aging buckets (1-30, 31-60, 61-90, 90+) | ✅ |
| 📊 | Dashboard: P&L, cash flow, top expenses, monthly trends, KPIs | 🔜 Phase 3 |
| 🧾 | Tax-ready export (CSV / PDF) | 🔜 Phase 4 |
| 💬 | Chat with your books in plain English | 🔜 Phase 4 |
| 🐳 | One-command Docker Compose run | 🔜 Phase 5 |

## Quickstart (local, Python 3.10+)

```bash
git clone https://github.com/Nishviprp/smallbiz-finance-agent.git
cd smallbiz-finance-agent
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
uvicorn finagent.main:app --reload
```

Open **http://localhost:8000/docs** and try the demo café files in `sample_data/`:

1. `POST /uploads/statement` → `bank_statement_cafe.csv` (6 months) or `.pdf` (January)
2. `POST /uploads/receipt` → `receipts/receipt_screwfix.png` — linked to its bank line automatically
3. `POST /uploads/invoice` → `invoices/INV-2026-014.pdf` — instantly **paid** (payment is in the statement)
4. `POST /uploads/invoice` → `invoices/INV-2026-021.pdf` — then `GET /invoices/alerts` shows it **overdue**

### OCR for receipt photos (optional)

Install [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html):
Windows — [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) ·
macOS — `brew install tesseract` · Linux — `sudo apt install tesseract-ocr`.
Or skip it and set `OLLAMA_VISION_MODEL=llama3.2-vision` (or use OpenAI/Claude) to read photos with AI.
PDFs with a text layer need neither.

### Free local AI (optional)

Install [Ollama](https://ollama.com), then:

```bash
ollama pull llama3.1:8b
```

No Ollama? Set `LLM_PROVIDER=none` — built-in keyword rules still categorize most lines — or use
`LLM_PROVIDER=openai` / `anthropic` with your own API key.

## How categorization works

1. **Your rules** — created automatically when you correct a transaction with `remember: true`.
2. **Built-in keywords** — ~240 common UK/US merchants (SumUp, Bookers, HMRC, AWS, Uber…), instant and offline.
3. **LLM** — remaining lines are sent in batches; answers are validated against your category list
   and money-in/money-out direction before being saved.
4. Anything still unknown stays **uncategorized** for you to review — never silently guessed.

Transactions you edit by hand are never overwritten.

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/uploads/statement` | Import a bank statement (CSV or PDF) |
| `POST` | `/uploads/receipt` | Read a receipt photo/PDF and link it to its transaction |
| `POST` | `/uploads/invoice` | Read a sales invoice and add it to the unpaid tracker |
| `GET` | `/transactions` | List / filter (date, category, direction, search, uncategorized) |
| `PATCH` | `/transactions/{id}` | Change category / notes, optionally learn a rule |
| `POST` | `/transactions/recategorize` | Re-run categorization |
| `GET/POST/PATCH/DELETE` | `/categories` | Manage your chart of accounts |
| `GET/POST/DELETE` | `/rules` | Manage categorization rules |
| `GET/POST/PATCH/DELETE` | `/invoices` | Track invoices (`?status=unpaid\|overdue\|paid`) |
| `POST` | `/invoices/{id}/mark-paid` | Mark paid manually (optionally link a transaction) |
| `GET` | `/invoices/alerts` | Overdue + due-soon invoices, totals and aging |
| `GET/PATCH/DELETE` | `/receipts` | Review and correct receipts |

## Development

```bash
pip install -r requirements-dev.txt
pytest
ruff check . && ruff format --check .
```

Regenerate the demo data: `python scripts/generate_sample_data.py`

## Roadmap

- [x] **Phase 1** – Core: CSV import, dedupe, AI categorization, learning rules, API, tests, CI
- [x] **Phase 2** – PDF statements, receipt OCR, invoices + unpaid tracker & alerts
- [ ] **Phase 3** – Streamlit dashboard: P&L, cash flow, top expenses, trends, KPIs
- [ ] **Phase 4** – Tax-ready export (CSV/PDF), chat with your books
- [ ] **Phase 5** – Docker Compose one-command run, Postgres option, v0.1.0 release

## License

[MIT](LICENSE) — free for personal and commercial use.

> ⚠️ This tool helps you organise your books; it is not tax or accounting advice. Check with a
> qualified accountant before filing.
