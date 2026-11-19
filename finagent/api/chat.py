from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.business import get_profile
from ..services.chat import ChatTurn, ask
from ..services.llm import get_llm

router = APIRouter(prefix="/chat", tags=["chat"])


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)
    tool: str | None = None
    args: dict | None = None


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[TurnIn] = Field(default_factory=list, max_length=20)
    use_llm: bool = True
    today: dt.date | None = None  # for reproducible answers / tests


class ChatOut(BaseModel):
    answer: str
    tool: str
    args: dict
    data: Any
    method: str
    start: dt.date | None
    end: dt.date | None


@router.post("", response_model=ChatOut)
def chat(body: ChatIn, db: Session = Depends(get_db)):
    """Ask a question about your books in plain English. Read-only: nothing is changed."""
    profile = get_profile(db)
    result = ask(
        db,
        body.question,
        profile.currency,
        history=[ChatTurn(t.role, t.content, t.tool, t.args) for t in body.history],
        llm=get_llm() if body.use_llm else None,
        today=body.today,
        dayfirst=profile.date_dayfirst,
    )
    return ChatOut(**vars(result))
