"""Log the 12-case eval run to Langfuse — a trace with a child span per case plus an
overall accuracy score. Requires the ``observability`` deps + Langfuse keys.
Invoked via ``uv run python -m eval.harness --langfuse``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.observability.tracing import get_langfuse

if TYPE_CHECKING:
    from eval.harness import CaseOutcome


def log_eval_run(outcomes: list[CaseOutcome]) -> None:  # pragma: no cover - requires langfuse + server
    lf = get_langfuse()
    if lf is None:
        return
    total = len(outcomes)
    n_pass = sum(o.passed for o in outcomes)
    with lf.start_as_current_observation(as_type="span", name="eval-12-cases", input={"total": total}) as root:
        for o in outcomes:
            with lf.start_as_current_observation(
                as_type="span",
                name=o.case_id,
                input={"case": o.case_name},
                metadata={"passed": o.passed, "mismatch": o.mismatch},
            ) as span:
                span.update(
                    output={
                        "decision": o.decision,
                        "approved_amount": o.approved_amount,
                        "confidence": o.confidence,
                    }
                )
        root.update(output={"passed": n_pass, "total": total})
        try:
            lf.score_current_trace(name="accuracy", value=n_pass / total if total else 0.0)
        except Exception:
            pass
    lf.flush()
