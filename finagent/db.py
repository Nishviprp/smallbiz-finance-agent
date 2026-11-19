"""Database engine, sessions and multi-business (tenant) isolation.

Isolation is enforced centrally, not per query:
  * Every session that serves a request carries the current business id in `session.info`.
  * A `do_orm_execute` hook adds `WHERE business_id = :current` to every SELECT, UPDATE and
    DELETE that touches a tenant table (via `with_loader_criteria`).
  * A `before_flush` hook stamps new rows with the current business id and refuses to write
    rows that belong to another business.
  * A query on tenant tables from a session with NO business set raises, so a forgotten
    scope fails loudly instead of leaking every business's data.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, with_loader_criteria

from .config import get_settings

log = logging.getLogger(__name__)

BUSINESS_KEY = "business_id"
GLOBAL_KEY = "global_access"  # set only by trusted admin/auth code paths


class Base(DeclarativeBase):
    pass


class TenantScopeError(RuntimeError):
    """Raised when tenant data is queried without a business in scope."""


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite"):
        return None
    db_path = url.split("///", 1)[-1]
    return Path(db_path) if db_path and db_path != ":memory:" else None


def _make_engine(url: str) -> Engine:
    connect_args: dict = {}
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        connect_args["check_same_thread"] = False
        path = _sqlite_path(url)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def get_engine() -> Engine:
    global _engine, _session_factory
    if _engine is None:
        _engine = _make_engine(get_settings().database_url)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


def reset_engine() -> None:
    """Dispose the current engine (used by tests and settings reloads)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


# ---- tenant scoping -------------------------------------------------------------


def _tenant_models() -> tuple[type, ...]:
    from .models import TENANT_MODELS

    return TENANT_MODELS


def scope_session(db: Session, business_id: int) -> Session:
    db.info[BUSINESS_KEY] = int(business_id)
    db.info.pop(GLOBAL_KEY, None)
    return db


def global_session() -> Session:
    """A session that may read across businesses — for auth/admin code only."""
    db = get_session_factory()()
    db.info[GLOBAL_KEY] = True
    return db


@event.listens_for(Session, "do_orm_execute")
def _apply_tenant_filter(state) -> None:
    if not (state.is_select or state.is_update or state.is_delete):
        return
    tenant_models = _tenant_models()
    touched = {m.class_ for m in state.all_mappers} & set(tenant_models)
    if not touched:
        return
    bid = state.session.info.get(BUSINESS_KEY)
    if bid is None:
        if state.session.info.get(GLOBAL_KEY):
            return
        names = ", ".join(sorted(c.__name__ for c in touched))
        raise TenantScopeError(f"Query on {names} without a business in scope")
    for model in tenant_models:
        state.statement = state.statement.options(
            with_loader_criteria(model, lambda cls: cls.business_id == bid, include_aliases=True)
        )


@event.listens_for(Session, "before_flush")
def _stamp_business(session: Session, _ctx, _instances) -> None:
    tenant_models = _tenant_models()
    bid = session.info.get(BUSINESS_KEY)
    for obj in list(session.new) + list(session.dirty):
        if not isinstance(obj, tenant_models):
            continue
        if obj.business_id is None:
            if bid is None:
                raise TenantScopeError(f"Cannot save {type(obj).__name__} without a business")
            obj.business_id = bid
        elif bid is not None and obj.business_id != bid:
            raise TenantScopeError(f"{type(obj).__name__} belongs to another business")


# ---- request dependency (local mode / no-auth contexts use api.deps) -------------


def get_db() -> Iterator[Session]:
    """Unscoped session. Tenant queries on it raise — routes use api.deps.get_tenant_db."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


# ---- schema ---------------------------------------------------------------------


def _is_pre_accounts_schema(engine: Engine) -> bool:
    insp = inspect(engine)
    if "transactions" not in insp.get_table_names():
        return False
    return "business_id" not in {c["name"] for c in insp.get_columns("transactions")}


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    engine = get_engine()
    if _is_pre_accounts_schema(engine):
        url = get_settings().database_url
        path = _sqlite_path(url)
        if path is None:
            raise RuntimeError(
                "This database was created by v0.2 or older (no business accounts). "
                "Point DATABASE_URL at a new, empty database for v0.3+."
            )
        backup = path.with_name(path.stem + ".v02-backup" + path.suffix)
        reset_engine()
        shutil.move(str(path), str(backup))
        for extra in ("-wal", "-shm"):
            Path(str(path) + extra).unlink(missing_ok=True)
        log.warning("Old v0.2 database moved to %s; starting a fresh v0.3 database.", backup)
        engine = get_engine()
    Base.metadata.create_all(engine)
