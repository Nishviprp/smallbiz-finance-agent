from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import analytics

router = APIRouter(prefix="/reports", tags=["reports"])


def _period(db: Session, start: dt.date | None, end: dt.date | None):
    return analytics.resolve_period(db, start, end)


@router.get("/range")
def data_range(db: Session = Depends(get_db)):
    """First and last transaction dates (useful for date pickers)."""
    rng = analytics.data_range(db)
    return {"start": rng[0], "end": rng[1]} if rng else {"start": None, "end": None}


@router.get("/summary")
def summary(
    start: dt.date | None = None,
    end: dt.date | None = None,
    today: dt.date | None = None,
    db: Session = Depends(get_db),
):
    period = _period(db, start, end)
    if period is None:
        return {"empty": True}
    return analytics.summary(db, *period, today=today)


@router.get("/monthly")
def monthly(
    start: dt.date | None = None, end: dt.date | None = None, db: Session = Depends(get_db)
):
    period = _period(db, start, end)
    return analytics.monthly(db, *period) if period else []


@router.get("/pnl")
def pnl(start: dt.date | None = None, end: dt.date | None = None, db: Session = Depends(get_db)):
    period = _period(db, start, end)
    return analytics.pnl(db, *period) if period else {"empty": True}


@router.get("/top-expenses")
def top_expenses(
    start: dt.date | None = None,
    end: dt.date | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    period = _period(db, start, end)
    if period is None:
        return {"total_expenses": 0, "categories": [], "merchants": []}
    return analytics.top_expenses(db, *period, limit=limit)


@router.get("/category-trends")
def category_trends(
    start: dt.date | None = None,
    end: dt.date | None = None,
    kind: str = Query(default="expense", pattern="^(income|expense)$"),
    top: int = Query(default=5, ge=1, le=7),
    db: Session = Depends(get_db),
):
    period = _period(db, start, end)
    if period is None:
        return {"months": [], "kind": kind, "series": []}
    return analytics.category_trends(db, *period, kind=kind, top=top)
