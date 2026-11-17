import json
from decimal import Decimal

import pytest
from sqlalchemy import select

from finagent.models import Category, CategoryRule
from finagent.services.categorizer import Categorizer, TxnInput, merchant_key
from finagent.services.llm import LLMError, extract_json


class FakeLLM:
    name = "fake"

    def __init__(self, reply: str | Exception):
        self.reply = reply
        self.calls = 0

    def complete(self, system, user, *, json_mode=False):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


@pytest.fixture
def cats(db):
    return {c.name: c for c in db.scalars(select(Category))}


def test_merchant_key():
    assert merchant_key("CARD PAYMENT TO ADOBE *CREATIVE CLD ON 12-03-2026") == "adobe creative cld"
    assert merchant_key("DD BRITISH GAS BUSINESS 9981") == "british gas business"


def test_keyword_longest_match_wins(cats):
    c = Categorizer(list(cats.values()))
    s = c.match_keyword("UBER EATS ORDER 1234", Decimal("-18.00"))
    assert s and s.category_id == cats["Meals & Entertainment"].id
    s = c.match_keyword("UBER TRIP LONDON", Decimal("-12.00"))
    assert s and s.category_id == cats["Travel"].id


def test_keyword_respects_sign(cats):
    c = Categorizer(list(cats.values()))
    # 'sumup' is a Sales keyword; an outgoing SumUp line must not become income.
    assert c.match_keyword("SUMUP PAYOUT", Decimal("500")).category_id == cats["Sales"].id
    assert c.match_keyword("SUMUP CARD READER", Decimal("-29")) is None


def test_keyword_word_boundaries(cats):
    c = Categorizer(list(cats.values()))
    assert c.match_keyword("CURRENT ACCOUNT INTEREST", Decimal("-1")) is None  # not 'rent'


def test_user_rule_beats_keyword(cats):
    rule = CategoryRule(pattern="uber", category_id=cats["Vehicle & Fuel"].id, priority=10)
    c = Categorizer(list(cats.values()), [rule])
    out = c.categorize([TxnInput(1, "UBER EATS", Decimal("-10"))])
    assert out[1].source == "rule"
    assert out[1].category_id == cats["Vehicle & Fuel"].id


def test_llm_results_validated(cats):
    reply = json.dumps(
        {
            "results": [
                {"id": 0, "category": "Repairs & Maintenance", "confidence": 0.8},
                {"id": 1, "category": "Made Up Category", "confidence": 0.9},
                {"id": 2, "category": "Sales", "confidence": 0.9},  # wrong sign
            ]
        }
    )
    llm = FakeLLM(f"```json\n{reply}\n```")
    c = Categorizer(list(cats.values()), llm=llm)
    items = [
        TxnInput("a", "J SMITH WINDOW CLEANING", Decimal("-25")),
        TxnInput("b", "MYSTERY", Decimal("-5")),
        TxnInput("c", "MYSTERY 2", Decimal("-5")),
    ]
    out = c.categorize(items)
    assert out["a"].source == "llm"
    assert out["a"].category_id == cats["Repairs & Maintenance"].id
    assert "b" not in out and "c" not in out


def test_llm_failure_is_non_fatal(cats):
    c = Categorizer(list(cats.values()), llm=FakeLLM(LLMError("offline")))
    out = c.categorize([TxnInput(1, "SOMETHING ODD", Decimal("-3"))])
    assert out == {}


def test_llm_batches(cats):
    llm = FakeLLM('{"results": []}')
    c = Categorizer(list(cats.values()), llm=llm, batch_size=2)
    c.categorize([TxnInput(i, f"ODD {i}", Decimal("-1")) for i in range(5)])
    assert llm.calls == 3


def test_extract_json_with_prose():
    assert extract_json('Sure! {"a": 1} hope this helps') == {"a": 1}
    with pytest.raises(LLMError):
        extract_json("no json here")
