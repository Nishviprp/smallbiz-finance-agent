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
    invoices_paid: int = 0
    receipts_linked: int = 0


# ---- Receipts ---------------------------------------------------------------


class ReceiptOut(ORM):
    id: int
    vendor: str | None
    date: dt.date | None
    total: Money | None
    tax: Money | None
    currency: str
    transaction_id: int | None
    extraction_method: str
    notes: str | None
    warnings: list[str] = []


class ReceiptUpdate(BaseModel):
    vendor: str | None = Field(default=None, max_length=200)
    date: dt.date | None = None
    total: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    transaction_id: int | None = None
    notes: str | None = None


# ---- Invoices ---------------------------------------------------------------

InvoiceStatus = Literal["unpaid", "paid", "void"]


class InvoiceIn(BaseModel):
    number: str | None = Field(default=None, max_length=64)
    client: str = Field(min_length=1, max_length=200)
    client_email: str | None = Field(default=None, max_length=200)
    issue_date: dt.date
    due_date: dt.date | None = None  # default: issue date + 30 days
    amount: Decimal = Field(gt=0)
    tax: Decimal | None = Field(default=None, ge=0)
    notes: str | None = None


class InvoiceUpdate(BaseModel):
    number: str | None = Field(default=None, max_length=64)
    client: str | None = Field(default=None, min_length=1, max_length=200)
    client_email: str | None = Field(default=None, max_length=200)
    issue_date: dt.date | None = None
    due_date: dt.date | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    tax: Decimal | None = Field(default=None, ge=0)
    status: InvoiceStatus | None = None
    paid_date: dt.date | None = None
    notes: str | None = None


class InvoiceOut(ORM):
    id: int
    number: str | None
    client: str
    client_email: str | None
    issue_date: dt.date
    due_date: dt.date
    amount: Money
    tax: Money | None
    currency: str
    status: str
    effective_status: str = ""  # unpaid | overdue | paid | void
    days_overdue: int = 0
    paid_date: dt.date | None
    transaction_id: int | None
    notes: str | None
    extraction_method: str | None = None
    warnings: list[str] = []


class MarkPaidIn(BaseModel):
    paid_date: dt.date | None = None
    transaction_id: int | None = None


class AlertItemOut(BaseModel):
    invoice_id: int
    number: str | None
    client: str
    amount: Money
    due_date: dt.date
    days: int


class InvoiceAlertsOut(BaseModel):
    today: dt.date
    overdue: list[AlertItemOut]
    due_soon: list[AlertItemOut]
    total_outstanding: Money
    total_overdue: Money
    aging: dict[str, Money]
