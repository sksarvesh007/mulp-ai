"""Targeted tests closing the last coverage gaps in edge branches."""

from __future__ import annotations

from app.engine.conditions import match_exclusion
from app.engine.eligibility import evaluate_eligibility
from app.engine.names import name_matches
from app.engine.view import ClaimView
from app.extraction.eval_extractor import EvalExtractor
from app.graph import run_claim
from app.graph.nodes import _writer
from app.schemas.claim import ClaimInput


def test_exclusion_direct_substring_fallback(policy) -> None:
    # "war" is not in the synonym table → exercises the head-word fallback path
    assert match_exclusion("Injury sustained during war", policy) == "War or nuclear hazard"


def test_name_matches_honorific_only_returns_true() -> None:
    # all tokens stripped as honorifics → cannot assert a mismatch
    assert name_matches("Dr.", "Rajesh Kumar") is True


def test_name_matches_reverse_initial() -> None:
    # long side carries the initial ("R") vs short side full ("Rajesh")
    assert name_matches("Rajesh Kumar", "R Kumar") is True


def test_name_matches_exact_middle_token() -> None:
    # middle given-name token is identical (exercises the equal-token branch)
    assert name_matches("Arjun Kumar Verma", "Arjun K Verma") is True
    assert name_matches("Arjun Kumar Verma", "Anil Kumar Verma") is False


def test_waiting_specific_condition_passes(policy) -> None:
    # diabetes specific condition matched, but treatment is AFTER eligibility → pass
    v = ClaimView(condition_text="Type 2 Diabetes Mellitus")
    c = ClaimInput(
        member_id="EMP005",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-12-15",
        claimed_amount=1500,
    )
    r = evaluate_eligibility(c, v, policy)
    assert not r.hard_reject


def test_stream_writer_outside_graph_is_noop() -> None:
    w = _writer()
    assert callable(w)
    assert w({"event": "x"}) is None


def test_get_extractor_factory() -> None:
    from app.deps import get_extractor

    assert isinstance(get_extractor("eval"), EvalExtractor)
    # live falls back to EvalExtractor until a live backend module exists
    assert get_extractor("live") is not None


def test_build_review_item_confirmed_correct() -> None:
    from app.observability.datasets import build_review_item

    actual = {"decision": "APPROVED", "approved_amount": 1350}
    expected, meta = build_review_item(actual, {"is_correct": True, "criteria": [], "expected_notes": ""})
    assert expected["verdict"] == "confirmed_correct"
    assert expected["decision"] == actual  # the model's own decision is the golden example
    assert meta["human_verdict"] == "correct"


def test_build_review_item_corrected() -> None:
    from app.observability.datasets import build_review_item

    actual = {"decision": "APPROVED", "approved_amount": 8000}
    review = {"is_correct": False, "criteria": ["approved_amount"], "expected_notes": "Cap at claimed 5000."}
    expected, meta = build_review_item(actual, review)
    assert expected["verdict"] == "corrected"
    assert expected["correction"] == "Cap at claimed 5000."
    assert expected["criteria_failed"] == ["approved_amount"]
    assert meta["human_verdict"] == "incorrect" and meta["actual_decision"] == actual


def test_build_review_item_corrected_without_notes_has_placeholder() -> None:
    from app.observability.datasets import build_review_item

    expected, _ = build_review_item({}, {"is_correct": False, "criteria": ["trace"]})
    assert "reviewer flagged" in expected["correction"]


async def test_runner_attaches_failures_on_gate_path(monkeypatch, cases) -> None:
    from app.extraction import eval_extractor

    original = eval_extractor.EvalExtractor.classify
    state = {"n": 0}

    async def flaky(self, doc):  # type: ignore[no-untyped-def]
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom: classifier down")
        return await original(self, doc)

    monkeypatch.setattr(eval_extractor.EvalExtractor, "classify", flaky)
    result = await run_claim(ClaimInput(**cases["TC004"]["input"], mode="eval"))
    assert result.decision.degraded is True
    assert result.decision.component_failures
