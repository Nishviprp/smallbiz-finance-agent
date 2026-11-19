"""Transaction categorization pipeline.

Order of precedence:
  1. User rules       (learned from your edits — always win)
  2. Built-in keywords (instant, offline, common merchants)
  3. LLM              (Ollama / OpenAI / Claude, batched, validated)
Anything left stays uncategorized for review.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Hashable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..models import Category, CategoryRule
from .keywords import KEYWORDS
from .llm import LLMClient, LLMError, extract_json

log = logging.getLogger(__name__)

_NOISE_WORDS = {
    "card", "payment", "payments", "to", "from", "purchase", "pos", "visa", "mastercard",
    "debit", "credit", "contactless", "direct", "dd", "so", "bacs", "fpo", "fpi", "bgc",
    "ref", "on", "at", "the", "ltd", "limited", "inc", "llc", "plc", "co", "www", "com",
    "online", "transaction", "trx", "txn", "gbp", "usd", "eur", "faster", "standing", "order",
    "zelle", "ach", "eft", "ppd", "ccd", "web", "recurring", "pymt", "usataxpymt", "of",
}  # fmt: skip


def merchant_key(description: str, max_words: int = 3) -> str:
    """Reduce a raw bank description to a stable merchant key.

    'CARD PAYMENT TO ADOBE *CREATIVE CLD ON 12-03-2026' -> 'adobe creative cld'
    """
    text = description.lower()
    text = re.sub(r"\d[\d/\-.:,]*", " ", text)  # dates, refs, amounts
    text = re.sub(r"[^a-z&\s]", " ", text)
    words = [w for w in text.split() if w not in _NOISE_WORDS and len(w) > 1]
    return " ".join(words[:max_words])


_ACRONYMS = {
    "irs", "usps", "ups", "dhl", "aws", "hmrc", "vat", "llc", "nj", "ny", "ca", "tx", "fl", "uk",
    "us", "usa", "bt", "ee", "o2", "pse&g", "jcp&l", "atm", "pos", "dd", "ltd", "plc", "gst",
}  # fmt: skip


def pretty_merchant(key: str) -> str:
    """'nj division taxation' -> 'NJ Division Taxation'."""
    return " ".join(w.upper() if w in _ACRONYMS else w.capitalize() for w in key.split())


@dataclass(frozen=True)
class TxnInput:
    key: Hashable
    description: str
    amount: Decimal


@dataclass(frozen=True)
class Suggestion:
    category_id: int
    source: str  # rule | keyword | llm
    confidence: float


def _sign_ok(kind: str, amount: Decimal) -> bool:
    if kind == "income":
        return amount > 0
    if kind == "expense":
        return amount < 0
    return True  # transfers can go either way


class Categorizer:
    def __init__(
        self,
        categories: Sequence[Category],
        rules: Sequence[CategoryRule] = (),
        llm: LLMClient | None = None,
        batch_size: int = 25,
    ):
        self.categories = {c.id: c for c in categories}
        self.by_name = {c.name.lower(): c for c in categories}
        self.llm = llm
        self.batch_size = max(1, batch_size)
        self.rules = sorted(
            (r for r in rules if r.category_id in self.categories),
            key=lambda r: (r.priority, -len(r.pattern)),
        )
        # Longest keyword first so "uber eats" beats "uber".
        compiled: list[tuple[int, re.Pattern[str], Category]] = []
        for cat_name, words in KEYWORDS.items():
            cat = self.by_name.get(cat_name.lower())
            if cat is None:
                continue  # user deleted/renamed this default category
            for w in words:
                pattern = re.compile(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])")
                compiled.append((len(w), pattern, cat))
        compiled.sort(key=lambda t: -t[0])
        self._keywords = [(p, c) for _, p, c in compiled]

    # ---- individual stages -------------------------------------------------

    def match_rule(self, description: str) -> Suggestion | None:
        text = description.lower()
        key = merchant_key(description, max_words=10)
        for rule in self.rules:
            pat = rule.pattern.lower()
            if pat in text or pat in key:
                return Suggestion(rule.category_id, "rule", 1.0)
        return None

    def match_keyword(self, description: str, amount: Decimal) -> Suggestion | None:
        text = description.lower()
        for pattern, cat in self._keywords:
            if pattern.search(text) and _sign_ok(cat.kind, amount):
                return Suggestion(cat.id, "keyword", 0.9)
        return None

    def classify_llm(self, items: Sequence[TxnInput]) -> dict[Hashable, Suggestion]:
        if not self.llm or not items:
            return {}
        out: dict[Hashable, Suggestion] = {}
        for start in range(0, len(items), self.batch_size):
            batch = items[start : start + self.batch_size]
            try:
                out.update(self._classify_batch(batch))
            except LLMError as exc:
                log.warning("LLM categorization failed for batch of %d: %s", len(batch), exc)
        return out

    def _classify_batch(self, batch: Sequence[TxnInput]) -> dict[Hashable, Suggestion]:
        assert self.llm is not None
        cats = sorted(self.categories.values(), key=lambda c: (c.kind, c.name))
        cat_lines = "\n".join(f"- {c.name} ({c.kind})" for c in cats)
        index = {i: t for i, t in enumerate(batch)}
        rows = [
            {"id": i, "description": t.description, "amount": float(t.amount)}
            for i, t in index.items()
        ]
        system = (
            "You are a meticulous small-business bookkeeper. Categorize bank transactions "
            "using ONLY the provided category names. Positive amounts are money in, negative "
            "amounts are money out. Income categories only fit money in; expense categories "
            "only fit money out. If you are not reasonably sure, use null."
        )
        user = (
            f"Categories:\n{cat_lines}\n\nTransactions:\n{json.dumps(rows)}\n\n"
            'Reply as JSON: {"results": [{"id": <id>, "category": "<exact name or null>", '
            '"confidence": <0..1>}]}'
        )
        data = extract_json(self.llm.complete(system, user, json_mode=True))
        results = data.get("results", []) if isinstance(data, dict) else data
        out: dict[Hashable, Suggestion] = {}
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            txn = index.get(_as_int(item.get("id")))
            name = item.get("category")
            if txn is None or not isinstance(name, str):
                continue
            cat = self.by_name.get(name.strip().lower())
            if cat is None or not _sign_ok(cat.kind, txn.amount):
                continue
            conf = _clamp(item.get("confidence", 0.6))
            out[txn.key] = Suggestion(cat.id, "llm", conf)
        return out

    # ---- full pipeline -----------------------------------------------------

    def categorize(
        self, items: Iterable[TxnInput], use_llm: bool = True
    ) -> dict[Hashable, Suggestion]:
        results: dict[Hashable, Suggestion] = {}
        leftovers: list[TxnInput] = []
        for t in items:
            s = self.match_rule(t.description) or self.match_keyword(t.description, t.amount)
            if s:
                results[t.key] = s
            else:
                leftovers.append(t)
        if use_llm and leftovers:
            results.update(self.classify_llm(leftovers))
        return results


def _as_int(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clamp(v: object) -> float:
    try:
        return max(0.0, min(1.0, float(v)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.6
