"""Default chart of accounts for a small business. Users can edit/add/remove freely."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category

# (name, kind, tax_deductible)
DEFAULT_CATEGORIES: list[tuple[str, str, bool]] = [
    # Income
    ("Sales", "income", False),
    ("Services Income", "income", False),
    ("Interest Income", "income", False),
    ("Other Income", "income", False),
    # Expenses
    ("Cost of Goods Sold", "expense", True),
    ("Rent", "expense", True),
    ("Utilities", "expense", True),
    ("Payroll", "expense", True),
    ("Software & Subscriptions", "expense", True),
    ("Marketing & Advertising", "expense", True),
    ("Office Supplies", "expense", True),
    ("Equipment", "expense", True),
    ("Travel", "expense", True),
    ("Vehicle & Fuel", "expense", True),
    ("Meals & Entertainment", "expense", False),
    ("Telephone & Internet", "expense", True),
    ("Insurance", "expense", True),
    ("Professional Fees", "expense", True),
    ("Bank Fees", "expense", True),
    ("Shipping & Postage", "expense", True),
    ("Repairs & Maintenance", "expense", True),
    ("Taxes & Licenses", "expense", True),
    ("Training", "expense", True),
    ("Other Expenses", "expense", True),
    # Non-P&L movements
    ("Transfers", "transfer", False),
    ("Owner Drawings", "transfer", False),
    ("Owner Investment", "transfer", False),
    ("Loan", "transfer", False),
]


def seed_defaults(db: Session) -> int:
    """Insert default categories once (only when the table is empty)."""
    if db.scalar(select(Category.id).limit(1)) is not None:
        return 0
    db.add_all(
        Category(name=name, kind=kind, tax_deductible=deductible, is_default=True)
        for name, kind, deductible in DEFAULT_CATEGORIES
    )
    db.commit()
    return len(DEFAULT_CATEGORIES)
