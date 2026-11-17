"""Bank statement CSV importer that copes with real-world exports.

Supports: single signed amount column, separate debit/credit (money in/out) columns,
DR/CR type columns, preamble lines before the header, ; or , or tab delimiters,
UK/US/ISO dates (inferred per file), and European decimal commas.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal

from .common import ParsedStatement, ParsedTxn, clean_text, infer_dayfirst, parse_amount, parse_date

ALIASES: dict[str, set[str]] = {
    "date": {
        "date", "transaction date", "posting date", "posted date", "post date", "value date",
        "booking date", "trans date", "completed date", "txn date", "started date",
    },
    "description": {
        "description", "details", "narrative", "memo", "payee", "transaction description",
        "name", "merchant", "particulars", "transaction details", "reference", "counter party",
        "counterparty", "transaction",
    },
    "amount": {"amount", "value", "transaction amount", "net amount", "amt"},
    "debit": {
        "debit", "debit amount", "debits", "money out", "paid out", "withdrawal",
        "withdrawals", "out", "spent",
    },
    "credit": {
        "credit", "credit amount", "credits", "money in", "paid in", "deposit", "deposits",
        "in", "received",
    },
    "type": {"type", "transaction type", "dr/cr", "debit/credit", "cr/dr", "direction"},
}  # fmt: skip

_DEBIT_TYPES = {"debit", "dr", "d", "withdrawal", "out", "payment"}
_CREDIT_TYPES = {"credit", "cr", "c", "deposit", "in"}


def _norm_header(h: str) -> str:
    h = re.sub(r"\(.*?\)", "", h or "")  # 'Amount (GBP)' -> 'amount'
    return re.sub(r"\s+", " ", h.replace("_", " ")).strip().lower().lstrip("﻿")


def _map_columns(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normed = [_norm_header(h) for h in header]
    for field, aliases in ALIASES.items():
        for i, h in enumerate(normed):
            if h in aliases and i not in mapping.values():
                mapping[field] = i
                break
    # Secondary description columns (e.g. 'Name' + 'Memo') are merged later.
    return mapping


def _is_header(cells: list[str]) -> bool:
    m = _map_columns(cells)
    return "date" in m and ("amount" in m or "debit" in m or "credit" in m)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _sniff_delimiter(text: str) -> str:
    sample = "\n".join(text.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in ",;\t|"}
        return max(counts, key=counts.get)


def parse_bank_csv(data: bytes | str, default_dayfirst: bool = True) -> ParsedStatement:
    text = _decode(data) if isinstance(data, bytes) else data
    delimiter = _sniff_delimiter(text)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))

    header_idx = next((i for i, r in enumerate(rows[:50]) if _is_header(r)), None)
    if header_idx is None:
        raise ValueError(
            "Could not find a header row with a date and amount (or debit/credit) column."
        )

    header = rows[header_idx]
    cols = _map_columns(header)
    body = [r for r in rows[header_idx + 1 :] if any(c.strip() for c in r)]

    # Extra description-like columns to enrich short descriptions (e.g. Monzo 'Notes').
    desc_extra = [
        i
        for i, h in enumerate(header)
        if _norm_header(h) in ALIASES["description"] and i != cols.get("description")
    ]

    def cell(r: list[str], key: str) -> str:
        i = cols.get(key)
        return r[i].strip() if i is not None and i < len(r) else ""

    dayfirst = infer_dayfirst((cell(r, "date") for r in body), default=default_dayfirst)
    out = ParsedStatement()

    for line_no, r in enumerate(body, start=header_idx + 2):
        date = parse_date(cell(r, "date"), dayfirst)
        amount = _row_amount(r, cols, cell)
        parts = [cell(r, "description")] + [r[i] for i in desc_extra if i < len(r)]
        description = clean_text(" ".join(p for p in parts if p and p.strip()))

        if date is None or amount is None:
            out.skipped += 1
            if len(out.warnings) < 20:
                out.warnings.append(f"Line {line_no}: skipped (unreadable date or amount)")
            continue
        if amount == 0:
            out.skipped += 1
            continue
        out.rows.append(ParsedTxn(date, description or "(no description)", amount))

    if not out.rows:
        raise ValueError("No transactions could be read from this file.")
    return out


def _row_amount(r, cols, cell) -> Decimal | None:
    if "amount" in cols:
        amount = parse_amount(cell(r, "amount"))
        if amount is None:
            return None
        kind = cell(r, "type").strip().lower()
        if kind in _DEBIT_TYPES:
            return -abs(amount)
        if kind in _CREDIT_TYPES:
            return abs(amount)
        return amount

    debit = parse_amount(cell(r, "debit"))
    credit = parse_amount(cell(r, "credit"))
    if debit is None and credit is None:
        return None
    return abs(credit or Decimal(0)) - abs(debit or Decimal(0))
