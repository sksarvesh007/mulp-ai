"""Assemble the multi-agent claims-processing graph.

Topology: intake → (fan-out) classify_doc* → gate → {format_blocker | (fan-out)
extract_doc*} → merge_extractions → consistency → {format_blocker | eligibility} →
fraud → adjudicate → score_route → finalize → END. The advisory AI agent is NOT a graph
node — it runs OFF the critical path (after the decision streams) in ``stream_claim`` so
it never blocks adjudication.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from app.engine.results import (
    AdjudicationResult,
    EligibilityResult,
    FraudResult,
    GateResult,
)
from app.engine.view import ClaimView
from app.graph import nodes
from app.graph.state import ClaimState
from app.schemas.claim import ClaimInput
from app.schemas.decision import ClaimDecision
from app.schemas.enums import (
    ClaimCategory,
    ClaimStatus,
    Decision,
    DocumentQuality,
    DocumentType,
    ExtractionMode,
    FraudSignalType,
    TraceStatus,
)
from app.schemas.extraction import ExtractedDocument
from app.schemas.trace import TraceEvent

# The HITL checkpointer round-trips our own typed state through msgpack. Register exactly
# the app types it serialises so deserialisation is explicitly allowed (no allow-all, no
# "unregistered type" warnings, future-proof against strict msgpack mode).
_CHECKPOINT_TYPES = [
    ClaimInput,
    ClaimDecision,
    ClaimCategory,
    ClaimStatus,
    Decision,
    DocumentQuality,
    DocumentType,
    ExtractionMode,
    FraudSignalType,
    TraceStatus,
    TraceEvent,
    ExtractedDocument,
    GateResult,
    ClaimView,
    EligibilityResult,
    FraudResult,
    AdjudicationResult,
]

# A single in-process checkpointer backs the HITL graph: it saves a paused claim's full
# state at the interrupt so a later resume can continue from that exact checkpoint. (A
# durable SqliteSaver/Postgres saver would drop in here unchanged for multi-process use.)
_HITL_CHECKPOINTER = MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_TYPES))


def build_graph(checkpointer: Any | None = None) -> Any:
    # The deterministic pipeline is always identical: the advisory AI agent is no longer a
    # graph node (it runs off the critical path in stream_claim after the decision streams).
    b = StateGraph(ClaimState)

    b.add_node("intake", nodes.intake)
    b.add_node("classify_doc", nodes.classify_doc)
    b.add_node("gate", nodes.gate)
    b.add_node("format_blocker", nodes.format_blocker)
    b.add_node("extract_doc", nodes.extract_doc)
    b.add_node("merge_extractions", nodes.merge_extractions)
    b.add_node("consistency", nodes.consistency)
    b.add_node("eligibility", nodes.eligibility)
    b.add_node("fraud", nodes.fraud)
    b.add_node("adjudicate", nodes.adjudicate_node)
    b.add_node("score_route", nodes.score_route)
    b.add_node("human_review", nodes.human_review)
    b.add_node("finalize", nodes.finalize)

    b.add_edge(START, "intake")
    b.add_conditional_edges("intake", nodes.fan_out_classify, ["classify_doc"])
    b.add_edge("classify_doc", "gate")
    b.add_conditional_edges("gate", nodes.route_after_gate, ["format_blocker", "extract_doc"])
    b.add_edge("extract_doc", "merge_extractions")
    # post-extraction: cross-check the declared claim against the extracted documents; a
    # mismatch routes to the member-action blocker, otherwise on to adjudication.
    b.add_edge("merge_extractions", "consistency")
    b.add_conditional_edges("consistency", nodes.route_after_consistency, ["format_blocker", "eligibility"])
    b.add_edge("eligibility", "fraud")
    b.add_edge("fraud", "adjudicate")
    b.add_edge("adjudicate", "score_route")
    # human_review is a pass-through unless a HITL claim was routed to MANUAL_REVIEW, in
    # which case it interrupt()s here (requires the HITL graph's checkpointer to pause).
    b.add_edge("score_route", "human_review")
    b.add_edge("human_review", "finalize")
    b.add_edge("format_blocker", "finalize")
    b.add_edge("finalize", END)

    return b.compile(checkpointer=checkpointer)


@lru_cache
def get_graph() -> Any:
    """Compiled graph singleton (no checkpointer; used for ainvoke + streaming)."""
    return build_graph()


@lru_cache
def get_hitl_graph() -> Any:
    """Compiled graph singleton WITH a checkpointer — required for the human-in-the-loop
    pause/resume path (``interrupt()`` errors without a checkpointer)."""
    return build_graph(checkpointer=_HITL_CHECKPOINTER)
