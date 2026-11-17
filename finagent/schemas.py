"""API request/response models."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float)]
CategoryKind = Literal["income", "expense", "transfer"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Categories -------------------------------------------------------------


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: CategoryKind = "expense"
    tax_deductible: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    kind: CategoryKind | None = None
    tax_deductible: bool | None = None


class CategoryOut(ORM):
    id: int
    name: str
    kind: str
    tax_deductible: bool
    is_default: bool


# ---- Rules ------------------------------------------------------------------


class RuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=200)
    category_id: int
    priority: int = 100
    apply_to_existing: bool = True


class RuleOut(ORM):
    id: int
    pattern: str
    category_id: int
    priority: int


# ---- Transactions -----------------------------------------------------------


class TransactionOut(ORM):
    id: int
    date: dt.date
    description: str
    amount: Money
    currency: str
    account: str | None
    category_id: int | None
    category_name: str | None = None
    category_source: str
    confidence: float | None
    notes: str | None

    @classmethod
    def from_model(cls, t) -> TransactionOut:
        out = cls.model_validate(t)
        out.category_name = t.category.name if t.category else None
        return out


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class TransactionUpdate(BaseModel):
    category_id: int | None = None
    notes: str | None = None
    # Learn a rule from this edit and apply it to similar, non-manual transactions.
    remember: bool = False


class TransactionUpdateResult(BaseModel):
    transaction: TransactionOut
    rule_created: RuleOut | None = None
    also_updated: int = 0


class RecategorizeIn(BaseModel):
    only_uncategorized: bool = True
    use_llm: bool = True


# ---- Imports ----------------------------------------------------------------


class ImportOut(BaseModel):
    upload_id: int
    filename: str
    imported: int
    duplicates: int
    skipped: int
    categorized: dict[str, int]
    uncategorized: int
    warnings: list[str]
