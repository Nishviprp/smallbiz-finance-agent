from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..services.business import (
    COUNTRIES,
    CURRENCIES,
    get_profile,
    has_mixed_currency,
    update_profile,
)
from ..services.ingest import load_demo, reset_books
from .deps import get_tenant_db

router = APIRouter(prefix="/settings", tags=["settings"])


class ProfileIn(BaseModel):
    business_name: str | None = Field(default=None, max_length=120)
    country: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    date_dayfirst: bool | None = None
    tax_year_start: str | None = Field(default=None, pattern=r"^\d{1,2}-\d{1,2}$")
    relabel_existing: bool = False


@router.get("")
def read_settings(db: Session = Depends(get_tenant_db)):
    p = get_profile(db)
    return {**p.as_dict(), "other_currency_transactions": has_mixed_currency(db, p.currency)}


@router.put("")
def save_settings(body: ProfileIn, db: Session = Depends(get_tenant_db)):
    changes = body.model_dump(exclude_unset=True, exclude={"relabel_existing"})
    changes = {k: v for k, v in changes.items() if v is not None}
    try:
        p = update_profile(db, changes, relabel_existing=body.relabel_existing)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**p.as_dict(), "other_currency_transactions": has_mixed_currency(db, p.currency)}


@router.get("/countries")
def countries():
    """Country presets for the setup wizard, and common currency codes."""
    return {"countries": COUNTRIES, "currencies": CURRENCIES}


class ResetIn(BaseModel):
    confirm: str


@router.post("/demo")
def demo(db: Session = Depends(get_tenant_db)):
    """Load the demo café: 6 months of transactions, two invoices and two receipts."""
    try:
        r = load_demo(db)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return vars(r)


@router.post("/reset")
def reset(body: ResetIn, db: Session = Depends(get_tenant_db)):
    """Delete all transactions, invoices, receipts, rules and uploads. Type DELETE to confirm."""
    if body.confirm != "DELETE":
        raise HTTPException(400, 'Type "DELETE" to confirm.')
    return {"deleted": reset_books(db)}
