from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..services import analytics, export
from ..services.business import get_profile
from ..services.periods import tax_year_label, tax_years_covering
from .deps import get_tenant_db

router = APIRouter(prefix="/export", tags=["export"])


def _period(db: Session, start: dt.date | None, end: dt.date | None) -> tuple[dt.date, dt.date]:
    period = analytics.resolve_period(db, start, end)
    if period is None:
        raise HTTPException(404, "No transactions to export yet")
    return period


def _file(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/tax-years")
def tax_years(db: Session = Depends(get_tenant_db)):
    """Tax years that contain transactions, newest first (TAX_YEAR_START sets the boundary)."""
    profile = get_profile(db)
    rng = analytics.data_range(db)
    if rng is None:
        return []
    years = tax_years_covering(rng[0], rng[1], profile.tax_year_start)
    return [{"label": tax_year_label(y), "start": y[0], "end": y[1]} for y in reversed(years)]


@router.get("/summary")
def tax_summary(
    start: dt.date | None = None, end: dt.date | None = None, db: Session = Depends(get_tenant_db)
):
    """The tax-pack numbers as JSON (what the dashboard previews)."""
    pack = export.build_tax_pack(db, *_period(db, start, end), get_profile(db))
    return {
        "start": pack.start,
        "end": pack.end,
        "currency": pack.currency,
        "income": pack.income,
        "allowable_expenses": pack.allowable_expenses,
        "disallowable_expenses": pack.disallowable_expenses,
        "uncategorized_out": pack.uncategorized_out,
        "uncategorized_count": pack.uncategorized_count,
        "transfers_net": pack.transfers_net,
        "taxable_profit_estimate": pack.taxable_profit_estimate,
        "sales_tax_on_invoices": pack.sales_tax_on_invoices,
        "tax_on_receipts": pack.tax_on_receipts,
        "receipt_coverage_pct": pack.receipt_coverage_pct,
        "unpaid_invoices_at_end": sum((i.amount for i in pack.unpaid_at_end), export.ZERO),
        "categories": [vars(c) for c in pack.categories],
        "warnings": pack.warnings,
    }


@router.get("/transactions.csv")
def transactions_csv(
    start: dt.date | None = None, end: dt.date | None = None, db: Session = Depends(get_tenant_db)
):
    s, e = _period(db, start, end)
    return _file(
        export.ledger_csv(export.ledger(db, s, e)), f"transactions_{s}_{e}.csv", "text/csv"
    )


@router.get("/category-summary.csv")
def category_summary_csv(
    start: dt.date | None = None, end: dt.date | None = None, db: Session = Depends(get_tenant_db)
):
    s, e = _period(db, start, end)
    pack = export.build_tax_pack(db, s, e, get_profile(db))
    return _file(export.summary_csv(pack), f"category_summary_{s}_{e}.csv", "text/csv")


@router.get("/invoices.csv")
def invoices_csv(db: Session = Depends(get_tenant_db)):
    return _file(export.invoices_csv(db), "invoices.csv", "text/csv")


@router.get("/tax-pack.pdf")
def tax_pack_pdf(
    start: dt.date | None = None, end: dt.date | None = None, db: Session = Depends(get_tenant_db)
):
    s, e = _period(db, start, end)
    pack = export.build_tax_pack(db, s, e, get_profile(db))
    return _file(export.tax_pack_pdf(pack), f"tax_pack_{s}_{e}.pdf", "application/pdf")


@router.get("/tax-pack.zip")
def tax_pack_zip(
    start: dt.date | None = None, end: dt.date | None = None, db: Session = Depends(get_tenant_db)
):
    s, e = _period(db, start, end)
    pack = export.build_tax_pack(db, s, e, get_profile(db))
    return _file(export.tax_pack_zip(db, pack), f"tax_pack_{s}_{e}.zip", "application/zip")
