"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.observability.setup import setup_observability

log = structlog.get_logger()


def _error(status: int, error: str, detail: Any) -> JSONResponse:
    """Uniform error envelope so clients never receive a raw stack trace."""
    return JSONResponse(status_code=status, content={"error": error, "detail": detail})


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Wire observability AFTER the server binds its port. Langfuse/OTel init can take
    ~15-20s; doing it at import time delayed the port bind past the platform's deploy
    port-scan timeout (the cause of an intermittent 'no open ports detected' deploy
    failure). A telemetry hiccup must never block startup, so it is best-effort."""
    try:
        setup_observability(app, get_settings())
    except Exception as exc:  # pragma: no cover - defensive; telemetry never blocks boot
        log.warning("observability_setup_failed", error=str(exc))
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Mulp Claims Processing API",
        version="0.1.0",
        description="Multi-agent health-insurance claims adjudication (LangGraph).",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "validation_error", exc.errors())

    @app.exception_handler(Exception)
    async def _on_unhandled(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled_error", error=str(exc), error_type=type(exc).__name__)
        return _error(500, "internal_error", "An unexpected error occurred while processing the request.")

    app.include_router(router)
    return app


app = create_app()
