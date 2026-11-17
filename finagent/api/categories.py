from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, CategoryRule, Transaction
from ..schemas import CategoryIn, CategoryOut, CategoryUpdate

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.scalars(select(Category).order_by(Category.kind, Category.name)).all()


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryIn, db: Session = Depends(get_db)):
    cat = Category(name=body.name.strip(), kind=body.kind, tax_deductible=body.tax_deductible)
    db.add(cat)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Category '{body.name}' already exists") from None
    return cat


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, body: CategoryUpdate, db: Session = Depends(get_db)):
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(404, "Category not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cat, field, value.strip() if isinstance(value, str) else value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A category with that name already exists") from None
    return cat


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.get(Category, category_id)
    if cat is None:
        raise HTTPException(404, "Category not found")
    # Transactions fall back to uncategorized; the category's rules are removed.
    db.execute(
        update(Transaction)
        .where(Transaction.category_id == category_id)
        .values(category_id=None, category_source="none", confidence=None)
    )
    db.execute(delete(CategoryRule).where(CategoryRule.category_id == category_id))
    db.delete(cat)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
