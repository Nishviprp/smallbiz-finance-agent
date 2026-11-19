"""FastAPI application entrypoint: `uvicorn finagent.main:app --reload`."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import (
    auth,
    bank,
    categories,
    chat,
    export,
    invoices,
    receipts,
    reports,
    rules,
    transactions,
    uploads,
)
from .api import settings as settings_api
from .config import get_settings
from .db import get_session_factory, init_db, scope_session
from .services.auth import local_business
from .services.business import get_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def _bank_sync_loop(hours: float) -> None:
    """Sync bank feeds that are older than `hours`, checking every 15 minutes."""
    from .services.banking import sync_due_everywhere

    while True:
        try:
            n = await asyncio.to_thread(sync_due_everywhere, hours)
            if n:
                logging.getLogger(__name__).info("Background bank sync: %d connection(s)", n)
        except Exception:  # never let the loop die
            logging.getLogger(__name__).exception("Background bank sync failed")
        await asyncio.sleep(15 * 60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .services.plaid import plaid_configured

    init_db()
    task = None
    hours = get_settings().bank_sync_hours
    if hours > 0 and plaid_configured():
        task = asyncio.create_task(_bank_sync_loop(hours))
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SmallBiz Finance Agent",
        version=__version__,
        description="Open-source AI bookkeeping agent for small businesses.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    def health():
        """Public. In local mode it also returns the business profile (there is only one)."""
        out = {
            "status": "ok",
            "version": __version__,
            "llm_provider": settings.llm_provider,
            "auth_mode": settings.auth_mode,
            "allow_signup": settings.allow_signup,
        }
        if settings.auth_mode == "local":
            with get_session_factory()() as db:
                scope_session(db, local_business(db).id)
                profile = get_profile(db)
            out.update(
                currency=profile.currency,
                business_name=profile.business_name,
                setup_complete=profile.setup_complete,
                date_dayfirst=profile.date_dayfirst,
            )
        return out

    for r in (
        auth,
        bank,
        uploads,
        transactions,
        categories,
        rules,
        receipts,
        invoices,
        reports,
        export,
        chat,
        settings_api,
    ):
        app.include_router(r.router)
    return app


app = create_app()
