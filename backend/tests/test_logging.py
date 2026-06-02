"""Structured-logging helpers + the request-logging middleware.

Uses ``structlog.testing.capture_logs`` (which captures emitted events as dicts) so we can
assert on the structured fields without parsing rendered output."""

from __future__ import annotations

import pytest
import structlog
from fastapi.testclient import TestClient

from app.main import app
from app.observability.logs import bind, clear, get_logger, log_stage

client = TestClient(app)


def test_log_stage_emits_start_and_done_with_timing() -> None:
    with structlog.testing.capture_logs() as caps:
        with log_stage(get_logger("t"), "thing", foo="bar") as extra:
            extra["result"] = 42
    events = [c["event"] for c in caps]
    assert "thing.start" in events and "thing.done" in events
    done = next(c for c in caps if c["event"] == "thing.done")
    # input fields + mid-stage extras + timing all land on the terminal line
    assert done["foo"] == "bar" and done["result"] == 42
    assert isinstance(done["elapsed_ms"], float)


def test_log_stage_logs_error_and_reraises() -> None:
    with structlog.testing.capture_logs() as caps:
        with pytest.raises(ValueError):
            with log_stage(get_logger("t"), "boom", ctx="x"):
                raise ValueError("nope")
    err = next(c for c in caps if c["event"] == "boom.error")
    assert err["error_type"] == "ValueError" and err["error"] == "nope"
    assert err["ctx"] == "x" and err["log_level"] == "error" and "elapsed_ms" in err


def test_log_stage_custom_level() -> None:
    # the `level` param controls the start/done lines (error is always error)
    with structlog.testing.capture_logs() as caps:
        with log_stage(get_logger("t"), "loud", level="warning"):
            pass
    start = next(c for c in caps if c["event"] == "loud.start")
    done = next(c for c in caps if c["event"] == "loud.done")
    assert start["log_level"] == "warning" and done["log_level"] == "warning"


def test_bind_and_clear_manage_context() -> None:
    # bind() puts identifiers into structlog's contextvars (merged onto every line by the
    # configured processor chain); clear() removes them.
    clear()
    bind(claim_id="CLM_TEST", request_id="req123")
    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("claim_id") == "CLM_TEST" and ctx.get("request_id") == "req123"
    clear()
    assert "claim_id" not in structlog.contextvars.get_contextvars()


def test_setup_logging_configures_both_renderers() -> None:
    from app.observability.setup import setup_logging

    try:
        setup_logging("INFO", json_logs=True)
        setup_logging("DEBUG", json_logs=False)
        get_logger("x").info("hello")  # must not raise under either renderer
    finally:
        # restore a sane, configured state (not structlog's bare defaults) for later tests
        setup_logging("INFO", json_logs=False)


def test_request_middleware_sets_request_id_header() -> None:
    # the middleware tags every response with a correlation id
    r = client.get("/members")
    assert r.status_code == 200
    assert r.headers.get("X-Request-ID")
