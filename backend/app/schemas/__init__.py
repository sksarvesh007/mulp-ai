"""Canonical schema package — the single source of truth for all data contracts."""

from __future__ import annotations

from .claim import ClaimHistoryItem, ClaimInput, DocumentInput
from .decision import (
    ClaimDecision,
    ClaimResult,
    DocumentProblem,
    FinancialBreakdown,
    FraudSignal,
    LineItemDecision,
)
from .enums import (
    ClaimCategory,
    ClaimStatus,
    Decision,
    DocumentProblemType,
    DocumentQuality,
    DocumentType,
    ExtractionMode,
    FraudSignalType,
    LineItemStatus,
    RejectionReason,
    TraceStatus,
)
from .extraction import ExtractedDocument, ExtractedField, LineItem
from .trace import ComponentFailure, ConfidenceBreakdown, ConfidenceDelta, TraceEvent

__all__ = [
    "ClaimInput",
    "DocumentInput",
    "ClaimHistoryItem",
    "ExtractedDocument",
    "ExtractedField",
    "LineItem",
    "ClaimDecision",
    "ClaimResult",
    "DocumentProblem",
    "FinancialBreakdown",
    "FraudSignal",
    "LineItemDecision",
    "TraceEvent",
    "ComponentFailure",
    "ConfidenceBreakdown",
    "ConfidenceDelta",
    "ClaimCategory",
    "ClaimStatus",
    "Decision",
    "DocumentProblemType",
    "DocumentQuality",
    "DocumentType",
    "ExtractionMode",
    "FraudSignalType",
    "LineItemStatus",
    "RejectionReason",
    "TraceStatus",
]
