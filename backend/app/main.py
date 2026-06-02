"""FastAPI application factory."""

from __future__ import annotations

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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Plum Claims Processing API",
        version="0.1.0",
        description="Multi-agent health-insurance claims adjudication (LangGraph).",
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
    setup_observability(app, settings)
    return app


app = create_app()
