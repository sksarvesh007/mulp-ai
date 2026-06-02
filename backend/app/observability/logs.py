"""Structured-logging helpers on top of structlog.

The whole backend logs through ``get_logger(__name__)`` and the ``log_stage`` timing
context manager, so every major process emits a uniform pair of events:

    <event>.start                         (info/debug, with the call's input fields)
    <event>.done   elapsed_ms=…           (info/debug, plus anything added mid-stage)
    <event>.error  elapsed_ms=… error=…   (error, on an exception — then re-raised)

Cross-cutting identifiers (``request_id``, ``claim_id``) are bound into structlog's
contextvars so they appear on every line within a request / claim without being threaded
through call signatures. The renderer + level are configured in ``observability.setup``.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from typing import Any

import structlog

# Re-exported so modules do `from app.observability.logs import get_logger`.
get_logger = structlog.get_logger


def bind(**fields: Any) -> None:
    """Bind identifiers (e.g. ``claim_id``) onto every subsequent log line in this context."""
    structlog.contextvars.bind_contextvars(**fields)


def clear() -> None:
    """Drop all context-bound identifiers (call at the end of a request)."""
    structlog.contextvars.clear_contextvars()


@contextlib.contextmanager
def log_stage(logger: Any, event: str, *, level: str = "info", **fields: Any) -> Iterator[dict[str, Any]]:
    """Time a block and log ``{event}.start`` / ``{event}.done`` (with ``elapsed_ms``), or
    ``{event}.error`` on an exception (logged, then re-raised).

    Yields a mutable dict — values added to it during the block are merged into the terminal
    ``.done`` / ``.error`` line, so a caller can attach results discovered mid-stage::

        with log_stage(log, "llm.vision", model=m, images=n) as s:
            resp = await client.create(...)
            s["total_tokens"] = resp.usage.total_tokens
    """
    extra: dict[str, Any] = {}
    start = time.perf_counter()
    getattr(logger, level)(f"{event}.start", **fields)
    try:
        yield extra
    except Exception as exc:
        logger.error(
            f"{event}.error",
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
            error=str(exc),
            error_type=type(exc).__name__,
            **fields,
            **extra,
        )
        raise
    else:
        getattr(logger, level)(
            f"{event}.done",
            elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
            **fields,
            **extra,
        )
