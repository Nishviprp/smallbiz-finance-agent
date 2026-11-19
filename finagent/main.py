"""FastAPI application entrypoint: `uvicorn finagent.main:app --reload`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import categories, chat, export, invoices, receipts, reports, rules, transactions, uploads
from .api import settings as settings_api
from .config import get_settings
from .db import get_session_factory, init_db
from .services.business import get_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


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
        with get_session_factory()() as db:
            profile = get_profile(db)
        return {
            "status": "ok",
            "version": __version__,
            "llm_provider": settings.llm_provider,
            "currency": profile.currency,
            "business_name": profile.business_name,
            "setup_complete": profile.setup_complete,
            "date_dayfirst": profile.date_dayfirst,
        }

    for r in (
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
