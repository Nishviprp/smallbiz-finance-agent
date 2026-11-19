"""ORM models."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

CATEGORY_KINDS = ("income", "expense", "transfer")
# How a transaction got its category.
CATEGORY_SOURCES = ("none", "rule", "keyword", "bank", "llm", "user")


# ---- Accounts ---------------------------------------------------------------


class Business(Base):
    """A tenant. Every piece of bookkeeping data belongs to exactly one business."""

    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class Membership(Base):
    """Which businesses a user can open, and with what role."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "business_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="owner")  # owner | member


class AuthSession(Base):
    """A login. Only a SHA-256 hash of the token is stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)


class TenantMixin:
    """Adds business_id. Queries on these models are scoped automatically (see db.py)."""

    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), index=True
    )


# ---- Bookkeeping ------------------------------------------------------------


class Category(TenantMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("business_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="expense")
    tax_deductible: Mapped[bool] = mapped_column(default=True)
    is_default: Mapped[bool] = mapped_column(default=False)


class Upload(TenantMixin, Base):
    """An imported file (statement, receipt, invoice)."""

    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(32))  # statement | receipt | invoice
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Transaction(TenantMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("business_id", "fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(500))
    # Signed: positive = money in, negative = money out.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    account: Mapped[str | None] = mapped_column(String(120), nullable=True)

    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[Category | None] = relationship(lazy="joined")
    category_source: Mapped[str] = mapped_column(String(16), default="none")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True
    )
    # Stable hash used to skip duplicates when the same statement is imported twice.
    fingerprint: Mapped[str] = mapped_column(String(80), index=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CategoryRule(TenantMixin, Base):
    """'If description contains <pattern>, use <category>'. Created by users or learned."""

    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("business_id", "pattern"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    category: Mapped[Category] = relationship(lazy="joined")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Receipt(TenantMixin, Base):
    """A purchase receipt (photo or PDF), optionally linked to the bank transaction it explains."""

    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True
    )
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    extraction_method: Mapped[str] = mapped_column(String(32), default="none")
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


INVOICE_STATUSES = ("unpaid", "paid", "void")


class Invoice(TenantMixin, Base):
    """A sales invoice you issued (money owed to you)."""

    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    client: Mapped[str] = mapped_column(String(200))
    client_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_date: Mapped[dt.date] = mapped_column(Date, index=True)
    due_date: Mapped[dt.date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # gross, incl. tax
    tax: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), default="unpaid", index=True)
    paid_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    upload_id: Mapped[int | None] = mapped_column(
        ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AppSetting(TenantMixin, Base):
    """Key/value store for the business profile set in the dashboard."""

    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("business_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text)


class BankConnection(TenantMixin, Base):
    """A bank login linked through Plaid (an "Item"). The access token is encrypted."""

    __tablename__ = "bank_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(100), index=True)
    access_token_enc: Mapped[str] = mapped_column(Text)
    institution_name: Mapped[str] = mapped_column(String(120), default="Bank")
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="ok")  # ok | needs_reauth | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    accounts: Mapped[list[BankAccount]] = relationship(
        back_populates="connection", cascade="all, delete-orphan", lazy="selectin"
    )


class BankAccount(TenantMixin, Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("bank_connections.id", ondelete="CASCADE"), index=True
    )
    connection: Mapped[BankConnection] = relationship(back_populates="accounts")
    account_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(120))
    mask: Mapped[str | None] = mapped_column(String(8), nullable=True)
    type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subtype: Mapped[str | None] = mapped_column(String(32), nullable=True)

    @property
    def label(self) -> str:
        bank = self.connection.institution_name if self.connection else ""
        tail = f" ••{self.mask}" if self.mask else ""
        return f"{bank} {self.name}{tail}".strip()


TENANT_MODELS: tuple[type, ...] = (
    Category, Upload, Transaction, CategoryRule, Receipt, Invoice, AppSetting,
    BankConnection, BankAccount,
)  # fmt: skip
