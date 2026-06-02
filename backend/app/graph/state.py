"""LangGraph shared state. Fan-in keys use ``operator.add`` reducers so the parallel
``Send`` workers (classify, extract) can write concurrently without InvalidUpdateError."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.engine.results import AdjudicationResult, EligibilityResult, FraudResult, GateResult
from app.engine.view import ClaimView
from app.schemas.claim import ClaimInput
from app.schemas.decision import ClaimDecision
from app.schemas.extraction import ExtractedDocument
from app.schemas.trace import ComponentFailure, TraceEvent


def _or_flag(a: bool, b: bool) -> bool:
    return bool(a) or bool(b)


class ClaimState(TypedDict, total=False):
    # inputs
    claim: ClaimInput

    # fan-in accumulators (parallel writes → reducers required)
    classified_docs: Annotated[list[ExtractedDocument], operator.add]
    extracted_docs: Annotated[list[ExtractedDocument], operator.add]
    trace_events: Annotated[list[TraceEvent], operator.add]
    failures: Annotated[list[ComponentFailure], operator.add]
    degraded: Annotated[bool, _or_flag]

    # per-stage results (single writer each → last-write-wins)
    gate_result: GateResult | None
    view: ClaimView | None
    eligibility_result: EligibilityResult | None
    fraud_result: FraudResult | None
    adjudication_result: AdjudicationResult | None
    decision: ClaimDecision | None
