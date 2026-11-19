"""Business profile: name, country, currency, date format, tax year.

Stored in the database so the dashboard's setup wizard can change it — no .env editing needed.
Values from .env / environment act as defaults until the owner saves their own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AppSetting, Invoice, Receipt, Transaction
from .periods import parse_month_day

# Sensible defaults per country. Everything stays editable.
COUNTRIES: dict[str, dict] = {
    "US": {"name": "United States", "currency": "USD", "date_dayfirst": False, "tax_year_start": "01-01"},
    "CA": {"name": "Canada", "currency": "CAD", "date_dayfirst": False, "tax_year_start": "01-01"},
    "GB": {"name": "United Kingdom", "currency": "GBP", "date_dayfirst": True, "tax_year_start": "04-06"},
    "IE": {"name": "Ireland", "currency": "EUR", "date_dayfirst": True, "tax_year_start": "01-01"},
    "EU": {"name": "Eurozone (other)", "currency": "EUR", "date_dayfirst": True, "tax_year_start": "01-01"},
    "AU": {"name": "Australia", "currency": "AUD", "date_dayfirst": True, "tax_year_start": "07-01"},
    "NZ": {"name": "New Zealand", "currency": "NZD", "date_dayfirst": True, "tax_year_start": "04-01"},
    "IN": {"name": "India", "currency": "INR", "date_dayfirst": True, "tax_year_start": "04-01"},
    "OTHER": {"name": "Other", "currency": "USD", "date_dayfirst": False, "tax_year_start": "01-01"},
}  # fmt: skip

CURRENCIES = ("USD", "CAD", "GBP", "EUR", "AUD", "NZD", "INR", "CHF", "SGD", "AED", "ZAR")


@dataclass
class BusinessProfile:
    business_name: str
    country: str
    currency: str
    date_dayfirst: bool
    tax_year_start: str
    setup_complete: bool

    def as_dict(self) -> dict:
        return asdict(self)


_FIELDS = ("business_name", "country", "currency", "date_dayfirst", "tax_year_start")


def _defaults() -> BusinessProfile:
    s = get_settings()
    return BusinessProfile(
        business_name=s.business_name,
        country="US" if s.currency == "USD" else "OTHER",
        currency=s.currency,
        date_dayfirst=s.date_dayfirst,
        tax_year_start=s.tax_year_start,
        setup_complete=False,
    )


def get_profile(db: Session) -> BusinessProfile:
    p = _defaults()
    stored = {row.key: row.value for row in db.scalars(select(AppSetting))}
    for key in _FIELDS:
        if key in stored:
            raw = stored[key]
            setattr(p, key, raw == "true" if key == "date_dayfirst" else raw)
    p.setup_complete = stored.get("setup_complete") == "true"
    return p


def update_profile(
    db: Session, changes: dict, *, relabel_existing: bool = False
) -> BusinessProfile:
    """Save changes. With relabel_existing, records keep their amounts but take the new
    currency code (useful when the currency was simply set wrong — no conversion happens)."""
    current = get_profile(db)
    if "country" in changes and changes["country"] not in COUNTRIES:
        raise ValueError(f"Unknown country '{changes['country']}'")
    if "currency" in changes:
        code = str(changes["currency"]).upper().strip()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("Currency must be a 3-letter code like USD")
        changes["currency"] = code
    if "tax_year_start" in changes:
        parse_month_day(changes["tax_year_start"])  # raises ValueError if invalid
    if "business_name" in changes:
        name = str(changes["business_name"]).strip()
        if not name:
            raise ValueError("Business name cannot be empty")
        changes["business_name"] = name[:120]

    for key, value in changes.items():
        if key not in _FIELDS:
            continue
        text = ("true" if value else "false") if key == "date_dayfirst" else str(value)
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=text))
        else:
            row.value = text
    row = db.get(AppSetting, "setup_complete")
    if row is None:
        db.add(AppSetting(key="setup_complete", value="true"))
    else:
        row.value = "true"

    if relabel_existing:
        target = changes.get("currency", current.currency)
        for model in (Transaction, Receipt, Invoice):
            db.execute(update(model).where(model.currency != target).values(currency=target))
    db.commit()
    return get_profile(db)


def has_mixed_currency(db: Session, currency: str) -> int:
    """How many transactions carry a different currency code than the profile."""
    return len(
        list(
            db.scalars(select(Transaction.id).where(Transaction.currency != currency).limit(10_000))
        )
    )
