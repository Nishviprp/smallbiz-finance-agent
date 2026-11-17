import csv
import datetime as dt
import io
import json
import zipfile

import pdfplumber
import pytest

from finagent.services.chat import ChatTurn, ask
from finagent.services.llm import LLMError
from finagent.services.periods import parse_period, tax_year_for, tax_year_label

from .conftest import SAMPLE_DIR

TODAY = dt.date(2026, 11, 17)
ANCHOR = dt.date(2026, 6, 30)


@pytest.fixture
def books(client, db):
    for path, endpoint, mime in [
        (SAMPLE_DIR / "bank_statement_cafe.csv", "/uploads/statement", "text/csv"),
        (SAMPLE_DIR / "invoices" / "INV-2026-021.pdf", "/uploads/invoice", "application/pdf"),
    ]:
        r = client.post(
            endpoint,
            files={"file": (path.name, path.read_bytes(), mime)},
            data={"use_llm": "false"},
        )
        assert r.status_code == 200, r.text
    return db


# ---- periods ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("profit last month", (dt.date(2026, 5, 1), dt.date(2026, 5, 31))),
        ("spend this year", (dt.date(2026, 1, 1), ANCHOR)),
        ("sales in March", (dt.date(2026, 3, 1), dt.date(2026, 3, 31))),
        ("Q2 2026", (dt.date(2026, 4, 1), dt.date(2026, 6, 30))),
        ("last 3 months", (dt.date(2026, 4, 1), ANCHOR)),
        ("paid bookers since march", (dt.date(2026, 3, 1), ANCHOR)),
        ("rent in may", (dt.date(2026, 5, 1), dt.date(2026, 5, 31))),
        ("may I see my rent", None),
        ("what about 2025", (dt.date(2025, 1, 1), dt.date(2025, 12, 31))),
        ("how are we doing", None),
    ],
)
def test_parse_period(text, expected):
    assert parse_period(text, ANCHOR) == expected


def test_tax_years():
    uk = tax_year_for(dt.date(2026, 3, 1), "04-06")
    assert uk == (dt.date(2025, 4, 6), dt.date(2026, 4, 5))
    assert tax_year_label(uk) == "2025/26"
    assert tax_year_for(dt.date(2026, 3, 1), "01-01") == (
        dt.date(2026, 1, 1),
        dt.date(2026, 12, 31),
    )
    with pytest.raises(ValueError):
        tax_year_for(dt.date(2026, 1, 1), "13-40")


# ---- chat (rules, no LLM) ---------------------------------------------------


@pytest.mark.parametrize(
    "question,tool,needle",
    [
        ("How much profit did we make last month?", "summary", "£8,408"),
        ("How much did we spend on wages this year?", "category_total", "£35,399"),
        ("How much have we paid Bookers since March?", "search", "£9,748"),
        ("What are our biggest expenses?", "top_expenses", "Payroll"),
        ("Which invoices are overdue?", "invoices", "Riverside Book Club"),
        ("show profit month by month", "monthly", "Best: May 2026"),
        ("what did we earn from catering events", "search", "received"),
        ("what still needs categorizing?", "uncategorized", "42 transactions"),
        ("tell me a joke", "none", "I can answer"),
    ],
)
def test_chat_rules(books, question, tool, needle):
    r = ask(books, question, "GBP", today=TODAY)
    assert r.tool == tool
    assert r.method == "rules"
    assert needle in r.answer


def test_chat_follow_up_reuses_previous_question(books):
    first = ask(books, "How much did we spend on rent?", "GBP", today=TODAY)
    history = [
        ChatTurn("user", "How much did we spend on rent?"),
        ChatTurn("assistant", first.answer, first.tool, first.args),
    ]
    r = ask(books, "and in March?", "GBP", history=history, today=TODAY)
    assert r.tool == "category_total"
    assert (r.start, r.end) == (dt.date(2026, 3, 1), dt.date(2026, 3, 31))
    assert "£2,200" in r.answer


def test_chat_empty_books(db):
    r = ask(db, "How much profit?", "GBP")
    assert "no transactions" in r.answer.lower()


# ---- chat with an LLM -------------------------------------------------------


class ScriptedLLM:
    name = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user, *, json_mode=False):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def test_chat_llm_routes_and_phrases(books):
    plan = {
        "tool": "category_total",
        "args": {"category": "utilites"},
        "start": "2026-01-01",
        "end": "2026-03-31",
    }  # fmt: skip  (typo on purpose → fuzzy match)
    llm = ScriptedLLM(json.dumps(plan), "You spent **£1,039** on utilities in Q1.")
    r = ask(books, "energy bills in q1?", "GBP", llm=llm, today=TODAY)
    assert r.method == "ai" and r.tool == "category_total"
    assert r.data["category"] == "Utilities"
    assert r.answer.startswith("You spent")
    # The phrasing prompt carried the computed data, not just the question.
    assert '"category": "Utilities"' in llm.prompts[1]


def test_chat_llm_bad_tool_args_fall_back_to_rules(books):
    llm = ScriptedLLM(json.dumps({"tool": "category_total", "args": {"category": "zzzz"}}))
    r = ask(books, "How much did we spend on wages?", "GBP", llm=llm, today=TODAY)
    assert r.tool == "category_total" and r.method == "rules"
    assert "£35,399" in r.answer


def test_chat_llm_offline_uses_template(books):
    llm = ScriptedLLM(LLMError("down"), LLMError("down"))
    r = ask(books, "What are our biggest expenses?", "GBP", llm=llm, today=TODAY)
    assert r.method == "rules" and "Payroll" in r.answer


def test_chat_endpoint(client, books):
    r = client.post(
        "/chat",
        json={"question": "Which invoices are overdue?", "use_llm": False, "today": "2026-11-17"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool"] == "invoices"
    assert body["data"]["invoices"][0]["days_overdue"] == 165
    assert client.post("/chat", json={"question": ""}).status_code == 422


# ---- exports ----------------------------------------------------------------


def test_tax_summary_reconciles_with_reports(client, books):
    s = client.get("/export/summary").json()
    rep = client.get("/reports/summary").json()
    assert s["income"] == rep["income"]
    total_out = s["allowable_expenses"] + s["disallowable_expenses"] + s["uncategorized_out"]
    assert total_out == pytest.approx(rep["expenses"])
    assert s["taxable_profit_estimate"] == pytest.approx(s["income"] - s["allowable_expenses"])
    assert s["unpaid_invoices_at_end"] == 486.0
    assert any("uncategorized" in w for w in s["warnings"])


def test_disallowable_category(client, books):
    cats = {c["name"]: c["id"] for c in client.get("/categories").json()}
    client.patch(f"/categories/{cats['Rent']}", json={"tax_deductible": False})
    s = client.get("/export/summary").json()
    assert s["disallowable_expenses"] == 13200.0


def test_transactions_csv(client, books):
    r = client.get("/export/transactions.csv", params={"start": "2026-01-01", "end": "2026-01-31"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert len(rows) == 58
    assert all(row["Date"].startswith("2026-01") for row in rows)
    assert {"Allowable expense", "Income", "Needs review"} <= {row["Tax treatment"] for row in rows}


def test_tax_pack_pdf_and_zip(client, books):
    pdf = client.get("/export/tax-pack.pdf").content
    assert pdf[:5] == b"%PDF-"
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        text = "\n".join(p.extract_text() or "" for p in doc.pages)
    assert "Tax pack" in text and "Estimated taxable profit" in text
    assert "£118,701.17" in text
    assert "INV-2026-021" in text  # unpaid at period end

    z = zipfile.ZipFile(io.BytesIO(client.get("/export/tax-pack.zip").content))
    names = z.namelist()
    assert any(n.endswith(".pdf") for n in names)
    assert "invoices.csv" in names and "README.txt" in names


def test_tax_years_endpoint_and_empty_export(client):
    assert client.get("/export/tax-years").json() == []
    assert client.get("/export/tax-pack.pdf").status_code == 404
