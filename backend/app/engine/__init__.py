"""Deterministic decision engine — pure, testable rule functions.

LLMs only perceive (classify/extract); everything in this package is deterministic
Python driven by ``policy_terms.json``.
"""

from __future__ import annotations

from app.engine.adjudication import adjudicate
from app.engine.confidence import compute_confidence
from app.engine.decide import route_decision
from app.engine.eligibility import evaluate_eligibility
from app.engine.fraud import evaluate_fraud
from app.engine.gate import verify_claim_consistency, verify_documents
from app.engine.results import AdjudicationResult, EligibilityResult, FraudResult, GateResult
from app.engine.view import ClaimView, build_claim_view

__all__ = [
    "verify_documents",
    "verify_claim_consistency",
    "evaluate_eligibility",
    "evaluate_fraud",
    "adjudicate",
    "route_decision",
    "compute_confidence",
    "build_claim_view",
    "ClaimView",
    "GateResult",
    "EligibilityResult",
    "FraudResult",
    "AdjudicationResult",
]
