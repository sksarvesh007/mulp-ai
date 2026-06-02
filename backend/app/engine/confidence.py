"""Stage 8 — Confidence scoring. One deterministic model, every contribution
itemized in the breakdown so the score is reproducible (never a magic constant).

Anchors (verified): clean approval ≈ 0.95 (>0.85); clear hard-reject ≈ 0.99 (>0.90);
a degraded run is strictly lower than a clean approval (one component failure = -0.15).
"""

from __future__ import annotations

from app.schemas.extraction import ExtractedDocument
from app.schemas.trace import ConfidenceBreakdown, ConfidenceDelta

# Tunable constants (kept named, not inline magic).
BASE = 0.95
MAX = 0.99
MISSING_FIELD_PENALTY = 0.05
LOW_CONF_FIELD_PENALTY = 0.03
COMPONENT_FAILURE_PENALTY = 0.15
MANUAL_REVIEW_PENALTY = 0.10
CLARITY_BONUS = 0.05


def compute_confidence(
    extracted: list[ExtractedDocument],
    *,
    manual_review: bool,
    clarity_bonus: bool,
    num_failures: int,
) -> ConfidenceBreakdown:
    deltas: list[ConfidenceDelta] = []

    low_conf = sum(len(d.low_confidence_fields) for d in extracted)
    missing = sum(1 for d in extracted if not d.ok)

    if low_conf:
        deltas.append(
            ConfidenceDelta(
                reason=f"{low_conf} low-confidence extracted field(s)",
                delta=-LOW_CONF_FIELD_PENALTY * low_conf,
            )
        )
    if missing:
        deltas.append(
            ConfidenceDelta(
                reason=f"{missing} document(s) could not be extracted",
                delta=-MISSING_FIELD_PENALTY * missing,
            )
        )
    if num_failures:
        deltas.append(
            ConfidenceDelta(
                reason=f"{num_failures} component(s) failed/skipped",
                delta=-COMPONENT_FAILURE_PENALTY * num_failures,
            )
        )
    if manual_review:
        deltas.append(
            ConfidenceDelta(
                reason="routed to manual review (inherently uncertain)",
                delta=-MANUAL_REVIEW_PENALTY,
            )
        )
    if clarity_bonus:
        deltas.append(
            ConfidenceDelta(reason="clear-cut decision backed by an explicit policy rule", delta=CLARITY_BONUS)
        )

    final = BASE + sum(d.delta for d in deltas)
    final = round(max(0.0, min(MAX, final)), 2)
    return ConfidenceBreakdown(base=BASE, deltas=deltas, final=final)
