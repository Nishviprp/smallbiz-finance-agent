"""ORM models."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

CATEGORY_KINDS = ("income", "expense", "transfer")
# How a transaction got its category.
CATEGORY_SOURCES = ("none", "rule", "keyword", "llm", "user")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="expense")
    tax_deductible: Mapped[bool] = mapped_column(default=True)
    is_default: Mapped[bool] = mapped_column(default=False)


class Upload(Base):
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


class Transaction(Base):
    __tablename__ = "transactions"

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
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CategoryRule(Base):
    """'If description contains <pattern>, use <category>'. Created by users or learned."""

    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    pattern: Mapped[str] = mapped_column(String(200), unique=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    category: Mapped[Category] = relationship(lazy="joined")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
