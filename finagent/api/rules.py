from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, CategoryRule, Transaction
from ..schemas import RuleIn, RuleOut
from .deps import get_tenant_db

router = APIRouter(prefix="/rules", tags=["rules"])


def upsert_rule(db: Session, pattern: str, category_id: int, priority: int = 100) -> CategoryRule:
    pattern = " ".join(pattern.lower().split())
    rule = db.scalar(select(CategoryRule).where(CategoryRule.pattern == pattern))
    if rule:
        rule.category_id, rule.priority = category_id, priority
    else:
        rule = CategoryRule(pattern=pattern, category_id=category_id, priority=priority)
        db.add(rule)
    db.flush()
    return rule


def apply_rule(db: Session, rule: CategoryRule, exclude_id: int | None = None) -> int:
    """Apply a rule to all transactions not categorized by hand. Returns count updated."""
    from ..services.categorizer import merchant_key

    pat = rule.pattern.lower()
    n = 0
    for t in db.scalars(select(Transaction).where(Transaction.category_source != "user")):
        if t.id == exclude_id or t.category_id == rule.category_id:
            continue
        if pat in t.description.lower() or pat in merchant_key(t.description, max_words=10):
            t.category_id, t.category_source, t.confidence = rule.category_id, "rule", 1.0
            n += 1
    return n


@router.get("", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_tenant_db)):
    return db.scalars(
        select(CategoryRule).order_by(CategoryRule.priority, CategoryRule.pattern)
    ).all()


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleIn, db: Session = Depends(get_tenant_db)):
    if db.get(Category, body.category_id) is None:
        raise HTTPException(404, "Category not found")
    rule = upsert_rule(db, body.pattern, body.category_id, body.priority)
    if body.apply_to_existing:
        apply_rule(db, rule)
    db.commit()
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, db: Session = Depends(get_tenant_db)):
    rule = db.get(CategoryRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
