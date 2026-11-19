"""Request dependencies: who is calling, and which business's books they may touch."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session_factory, scope_session
from ..services.auth import local_business, resolve


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def get_tenant_db(request: Request) -> Iterator[Session]:
    """A DB session locked to the caller's business. Every data route uses this."""
    db = get_session_factory()()
    try:
        if get_settings().auth_mode == "local":
            biz = local_business(db)
            request.state.user = None
        else:
            found = resolve(db, bearer_token(request) or "")
            if found is None:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    "Please log in.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            request.state.user, biz = found
        request.state.business = biz
        scope_session(db, biz.id)
        yield db
    finally:
        db.close()


TenantDB = Depends(get_tenant_db)
