from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import BankConnection
from ..services import banking
from ..services.crypto import decrypt
from ..services.plaid import PlaidError, PlaidNotConfigured, get_plaid, plaid_configured
from .deps import get_tenant_db

router = APIRouter(prefix="/bank", tags=["bank feeds"])


class ConnectIn(BaseModel):
    public_token: str = Field(min_length=10, max_length=300)
    institution_name: str | None = Field(default=None, max_length=120)
    use_llm: bool = True


class SyncIn(BaseModel):
    connection_id: int | None = None
    use_llm: bool = True


def _plaid():
    try:
        return get_plaid()
    except PlaidNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc


def _plaid_error(exc: PlaidError) -> HTTPException:
    return HTTPException(
        502 if exc.code == "NETWORK_ERROR" else 400, f"Bank error: {exc.user_message}"
    )


def _conn_out(c: BankConnection) -> dict:
    return {
        "id": c.id,
        "institution": c.institution_name,
        "status": c.status,
        "error": c.error,
        "last_synced_at": c.last_synced_at,
        "accounts": [
            {"id": a.id, "name": a.name, "mask": a.mask, "type": a.type, "subtype": a.subtype}
            for a in c.accounts
        ],
    }


@router.get("/status")
def bank_status(db: Session = Depends(get_tenant_db)):
    s = get_settings()
    return {
        "configured": plaid_configured(),
        "env": s.plaid_env,
        "auto_sync_hours": s.bank_sync_hours,
        "connections": [
            _conn_out(c) for c in db.scalars(select(BankConnection).order_by(BankConnection.id))
        ],
    }


@router.post("/link-token")
def link_token(
    request: Request, connection_id: int | None = None, db: Session = Depends(get_tenant_db)
):
    """Token for Plaid Link. With connection_id: repair a connection that needs re-login."""
    plaid = _plaid()
    user = getattr(request.state, "user", None)
    client_user_id = f"business-{request.state.business.id}" + (f"-user-{user.id}" if user else "")
    access_token = None
    if connection_id is not None:
        conn = db.get(BankConnection, connection_id)
        if conn is None:
            raise HTTPException(404, "Bank connection not found")
        access_token = decrypt(conn.access_token_enc)
    try:
        return {"link_token": plaid.create_link_token(client_user_id, access_token=access_token)}
    except PlaidError as exc:
        raise _plaid_error(exc) from exc


@router.post("/connect")
def connect(body: ConnectIn, db: Session = Depends(get_tenant_db)):
    """Finish Plaid Link: store the (encrypted) bank link and import transactions."""
    plaid = _plaid()
    try:
        conn, result = banking.connect(
            db, body.public_token, institution_name=body.institution_name, plaid=plaid,
            use_llm=body.use_llm,
        )  # fmt: skip
    except PlaidError as exc:
        raise _plaid_error(exc) from exc
    return {"connection": _conn_out(conn), "sync": asdict(result)}


@router.post("/sandbox-connect")
def sandbox_connect(db: Session = Depends(get_tenant_db)):
    """Sandbox only: connect Plaid's test bank without the Link popup (for demos)."""
    plaid = _plaid()
    try:
        public_token = plaid.sandbox_public_token()
        conn, result = banking.connect(
            db, public_token, institution_name="First Platypus Bank (test)", plaid=plaid
        )
    except PlaidError as exc:
        raise _plaid_error(exc) from exc
    return {"connection": _conn_out(conn), "sync": asdict(result)}


@router.post("/sync")
def sync(body: SyncIn, db: Session = Depends(get_tenant_db)):
    _plaid()
    if body.connection_id is not None:
        conn = db.get(BankConnection, body.connection_id)
        if conn is None:
            raise HTTPException(404, "Bank connection not found")
        results = [banking.sync_connection(db, conn, use_llm=body.use_llm)]
    else:
        results = banking.sync_all(db, use_llm=body.use_llm)
    return {"results": [asdict(r) for r in results]}


@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(connection_id: int, db: Session = Depends(get_tenant_db)):
    """Unlink the bank. Transactions already imported stay in your books."""
    conn = db.get(BankConnection, connection_id)
    if conn is None:
        raise HTTPException(404, "Bank connection not found")
    banking.disconnect(db, conn, plaid=_plaid())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
