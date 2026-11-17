"""Bank statement PDF importer.

Strategy (first one that works wins):
  1. Tables detected in the PDF  -> reuse the CSV column logic
  2. Text lines "date ... description ... amount [balance]" -> balance deltas fix the sign
  3. LLM extraction from the text (if an LLM is configured)
"""

from __future__ import annotations

import csv
import io
import logging
import re
from decimal import Decimal

from ..services.llm import LLMClient, LLMError, extract_json
from .bank_csv import _is_header, parse_bank_csv
from .common import ParsedStatement, ParsedTxn, clean_text, infer_dayfirst, parse_amount, parse_date
from .text import pdf_tables, pdf_text

log = logging.getLogger(__name__)

_DATE_START = re.compile(
    r"^(?P<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\.?(?:\s+\d{2,4})?)\s+(?P<rest>.+)$"
)
_MONEY = re.compile(r"\(?-?[£$€]?\s?\d{1,3}(?:[,\s]?\d{3})*(?:[.,]\d{2})\)?(?:\s?(?:CR|DR))?-?")
_OPENING = re.compile(r"(balance brought forward|opening balance|previous balance)", re.I)
_SKIP_LINE = re.compile(r"(balance carried forward|closing balance|^page \d)", re.I)


def parse_pdf_statement(
    data: bytes, default_dayfirst: bool = True, llm: LLMClient | None = None
) -> ParsedStatement:
    # 1. Tables
    tables = pdf_tables(data)
    rows: list[list[str]] = []
    header: list[str] | None = None
    for table in tables:
        for row in table:
            if header is None and _is_header(row):
                header = row
            elif header is not None and len(row) == len(header) and not _is_header(row):
                rows.append(row)
    if header and rows:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        try:
            return parse_bank_csv(buf.getvalue(), default_dayfirst=default_dayfirst)
        except ValueError:
            log.info("PDF tables found but unusable, trying text lines")

    text = pdf_text(data)
    if not text:
        raise ValueError(
            "This PDF has no text layer (it is probably a scan). "
            "Export a CSV from your bank instead, or upload pages as receipt images."
        )

    # 2. Text lines
    parsed = _parse_text_lines(text, default_dayfirst)
    if len(parsed.rows) >= 2:
        return parsed

    # 3. LLM
    if llm is not None:
        try:
            return _parse_with_llm(text, llm, default_dayfirst)
        except (LLMError, ValueError) as exc:
            log.warning("LLM PDF extraction failed: %s", exc)

    raise ValueError("Could not find transactions in this PDF.")


def _parse_text_lines(text: str, default_dayfirst: bool) -> ParsedStatement:
    candidates: list[tuple[str, str, list[str]]] = []
    opening: Decimal | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line or _SKIP_LINE.search(line):
            continue
        if _OPENING.search(line):
            found = _MONEY.findall(line)
            if found and opening is None and not candidates:
                opening = parse_amount(found[-1])
            continue
        m = _DATE_START.match(line)
        if not m:
            continue
        rest = m.group("rest")
        amounts = _MONEY.findall(rest)
        if not amounts:
            continue
        # Description is everything before the first trailing amount.
        first = rest.find(amounts[0]) if len(amounts) <= 1 else rest.rfind(amounts[-2])
        desc = clean_text(rest[:first])
        if not desc:
            continue
        candidates.append((m.group("date"), desc, amounts[-2:]))

    dayfirst = infer_dayfirst((c[0] for c in candidates), default=default_dayfirst)
    out = ParsedStatement()
    prev_balance = opening
    for date_s, desc, nums in candidates:
        date = parse_date(date_s, dayfirst)
        values = [parse_amount(n) for n in nums]
        if date is None or any(v is None for v in values):
            out.skipped += 1
            continue
        if len(values) == 2:
            amount, balance = values
            if prev_balance is not None and amount is not None and balance is not None:
                delta = balance - prev_balance
                if abs(abs(delta) - abs(amount)) < Decimal("0.01"):
                    amount = delta  # balance movement tells us in vs out
            prev_balance = balance
        else:
            amount = values[0]
        if amount:
            out.rows.append(ParsedTxn(date, desc, amount))
    return out


def _parse_with_llm(text: str, llm: LLMClient, default_dayfirst: bool) -> ParsedStatement:
    system = (
        "You extract bank statement transactions from text. Money out must be negative, "
        "money in positive. Never invent transactions; skip balance lines."
    )
    user = (
        'Return JSON: {"transactions": [{"date": "YYYY-MM-DD", "description": "...", '
        '"amount": -12.34}]}\n\nStatement text:\n' + text[:15000]
    )
    data = extract_json(llm.complete(system, user, json_mode=True))
    items = data.get("transactions", []) if isinstance(data, dict) else []
    out = ParsedStatement()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        date = parse_date(it.get("date"), default_dayfirst)
        amount = parse_amount(it.get("amount"))
        desc = clean_text(it.get("description"))
        if date and amount:
            out.rows.append(ParsedTxn(date, desc or "(no description)", amount))
        else:
            out.skipped += 1
    if not out.rows:
        raise ValueError("LLM returned no transactions")
    out.warnings.append("Read by AI from PDF text — please spot-check amounts.")
    return out
