"""Langfuse **datasets** — turn a human review of a claim decision into a dataset
item you can later run evals against.

A reviewer either confirms the decision (it becomes a *golden* example) or marks it
wrong and supplies the correct expected outcome. Either way we upsert one
``create_dataset_item`` keyed by ``claim_id`` (re-reviewing replaces it) into the
``plum-claims-reviewed`` dataset, where:

* ``input``           = the original ``ClaimInput`` (so an eval can replay it),
* ``expected_output`` = the confirmed/corrected expected decision,
* ``metadata``        = the human verdict, the failed criteria, and the actual decision.

The Langfuse calls are network-bound and pragma-excluded; the payload-shaping
(:func:`build_review_item`) is pure and unit-tested.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.observability.tracing import get_langfuse

REVIEW_DATASET = "plum-claims-reviewed"
JUDGE_DATASET = "plum-claims-judge"


def build_review_item(
    actual: dict[str, Any],
    review: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pure: shape a human review into ``(expected_output, metadata)``.

    ``review`` = ``{is_correct: bool, criteria: list[str], expected_notes: str}``.
    When the reviewer confirms the decision, the actual decision *is* the golden
    expectation; when they reject it, the expectation is their written correction.
    """
    is_correct = bool(review.get("is_correct"))
    criteria = [str(c) for c in (review.get("criteria") or [])]
    notes = str(review.get("expected_notes") or "").strip()
    if is_correct:
        expected_output: dict[str, Any] = {"verdict": "confirmed_correct", "decision": actual}
    else:
        expected_output = {
            "verdict": "corrected",
            "correction": notes or "(reviewer flagged the criteria below without notes)",
            "criteria_failed": criteria,
        }
    metadata = {
        "human_verdict": "correct" if is_correct else "incorrect",
        "criteria": criteria,
        "notes": notes,
        "actual_decision": actual,
    }
    return expected_output, metadata


def save_review(
    *,
    claim_id: str,
    claim_input: dict[str, Any],
    actual: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:  # pragma: no cover - network (Langfuse server)
    """Upsert a reviewed claim as a Langfuse dataset item. Never raises."""
    expected_output, metadata = build_review_item(actual, review)
    lf = get_langfuse()
    if lf is None:
        return {"saved": False, "dataset": REVIEW_DATASET, "reason": "Langfuse is not configured."}
    try:
        try:
            lf.create_dataset(
                name=REVIEW_DATASET,
                description="Human-reviewed claim decisions — golden + corrected examples for evals.",
            )
        except Exception:
            pass  # dataset already exists → reuse it
        lf.create_dataset_item(
            dataset_name=REVIEW_DATASET,
            input=claim_input,
            expected_output=expected_output,
            metadata=metadata,
            id=claim_id,  # upsert by claim_id so re-reviewing replaces the item
        )
        lf.flush()
    except Exception as exc:
        return {"saved": False, "dataset": REVIEW_DATASET, "reason": str(exc)}
    return {
        "saved": True,
        "dataset": REVIEW_DATASET,
        "item_id": claim_id,
        "host": get_settings().langfuse_host,
    }
