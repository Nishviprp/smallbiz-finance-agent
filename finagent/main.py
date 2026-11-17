"""FastAPI application entrypoint: `uvicorn finagent.main:app --reload`."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import categories, rules, transactions, uploads
from .config import get_settings
from .db import init_db

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
        return {"status": "ok", "version": __version__, "llm_provider": settings.llm_provider}

    for r in (uploads, transactions, categories, rules):
        app.include_router(r.router)
    return app


app = create_app()
