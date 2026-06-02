"""Observability wiring.

Three complementary layers (see docs/PLAN.md §7):
  1. Domain decision-trace  — the TraceEvent list on every ClaimResult (always on).
  2. MLflow                 — GenAI tracing + the 12-case eval run.
  3. OpenTelemetry          — FastAPI + per-node spans → OTLP collector.

Layers 2 & 3 are enabled only when ``ENABLE_OBSERVABILITY=true`` and the optional
``observability`` dependency group is installed, so the core app + tests run without
them. Structured logging (structlog) is always configured.
"""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI

from app.core.config import Settings


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
    )


def setup_observability(app: FastAPI, settings: Settings) -> None:
    setup_logging(settings.log_level)
    if not settings.enable_observability:
        return
    _wire_telemetry(app, settings)  # pragma: no cover - optional deps + network


def _wire_telemetry(app: FastAPI, settings: Settings) -> None:  # pragma: no cover
    log = structlog.get_logger()
    langfuse_on = False
    try:
        # Initialising Langfuse (v3/v4 SDK) sets up the GLOBAL OpenTelemetry provider with
        # Langfuse's exporter — so any OTel spans go to Langfuse. Per-claim domain traces are
        # still emitted explicitly (observability/tracing.py), even for deterministic runs.
        from app.observability.tracing import get_langfuse

        client = get_langfuse()
        if client is not None and client.auth_check():
            langfuse_on = True
            log.info("langfuse_enabled", host=settings.langfuse_host)
            # Trace the OpenAI Agents SDK: the agent's LLM generations (model, input, output,
            # token usage) and tool calls are captured as nested observations in Langfuse.
            try:
                from openinference.instrumentation.openai_agents import OpenAIAgentsInstrumentor

                OpenAIAgentsInstrumentor().instrument()
                log.info("openai_agents_instrumented")
            except Exception as exc:
                log.warning("openai_agents_instrument_failed", error=str(exc))
        else:
            log.warning("langfuse_keys_missing_or_unreachable", host=settings.langfuse_host)
    except Exception as exc:
        log.warning("langfuse_setup_failed", error=str(exc))

    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # When Langfuse owns the global provider, do NOT replace it (that would silently break
        # the Agents-SDK→Langfuse export). Only build a local OTLP→Jaeger provider when Langfuse
        # is not active. Either way, FastAPI is instrumented onto the active provider.
        if not langfuse_on:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
            )
            trace.set_tracer_provider(provider)
            log.info("otel_enabled", endpoint=settings.otel_exporter_otlp_endpoint)
        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:
        log.warning("otel_setup_failed", error=str(exc))
