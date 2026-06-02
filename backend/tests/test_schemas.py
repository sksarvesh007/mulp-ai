from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.claim import ClaimInput
from app.schemas.extraction import ExtractedDocument, LineItem


def _claim(**kw) -> ClaimInput:
    base = dict(
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
    )
    base.update(kw)
    return ClaimInput(**base)


def test_claimed_amount_must_be_positive() -> None:
    _claim(claimed_amount=1)  # ok
    with pytest.raises(ValidationError):
        _claim(claimed_amount=0)
    with pytest.raises(ValidationError):
        _claim(claimed_amount=-100)


def test_ytd_must_be_non_negative() -> None:
    _claim(ytd_claims_amount=0)  # ok
    with pytest.raises(ValidationError):
        _claim(ytd_claims_amount=-5)


def test_line_item_amount_non_negative() -> None:
    LineItem(description="x", amount=0)  # ok
    with pytest.raises(ValidationError):
        LineItem(description="x", amount=-1)


def test_extraction_confidence_bounded() -> None:
    ExtractedDocument(file_id="a", confidence=0.5)  # ok
    with pytest.raises(ValidationError):
        ExtractedDocument(file_id="a", confidence=1.5)
    with pytest.raises(ValidationError):
        ExtractedDocument(file_id="a", confidence=-0.1)
