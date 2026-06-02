from __future__ import annotations

from app.engine.confidence import compute_confidence
from app.schemas.extraction import ExtractedDocument


def _doc(**kw) -> ExtractedDocument:
    return ExtractedDocument(file_id="a", **kw)


def test_clean_base() -> None:
    c = compute_confidence([_doc()], manual_review=False, clarity_bonus=False, num_failures=0)
    assert c.final == 0.95


def test_clarity_bonus_clamped_to_max() -> None:
    c = compute_confidence([_doc()], manual_review=False, clarity_bonus=True, num_failures=0)
    assert c.final == 0.99


def test_manual_review_penalty() -> None:
    c = compute_confidence([_doc()], manual_review=True, clarity_bonus=False, num_failures=0)
    assert c.final == 0.85


def test_component_failure_penalty() -> None:
    c = compute_confidence([_doc()], manual_review=False, clarity_bonus=False, num_failures=1)
    assert c.final == 0.80


def test_low_conf_and_missing() -> None:
    c = compute_confidence(
        [_doc(low_confidence_fields=["a", "b"], ok=False)],
        manual_review=False,
        clarity_bonus=False,
        num_failures=0,
    )
    assert c.final == 0.84  # 0.95 - 2*0.03 - 0.05


def test_floor_at_zero() -> None:
    c = compute_confidence(
        [_doc(low_confidence_fields=["x"] * 40, ok=False)],
        manual_review=True,
        clarity_bonus=False,
        num_failures=5,
    )
    assert c.final == 0.0
    assert c.base == 0.95
