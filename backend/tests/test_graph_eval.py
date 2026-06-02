"""The 12-case regression suite, run end-to-end through the LangGraph pipeline."""

from __future__ import annotations

import json

import pytest

from app.core.config import get_settings
from app.graph import run_claim
from app.schemas.claim import ClaimInput

_CASES = json.loads(get_settings().test_cases_file.read_text())["test_cases"]


@pytest.mark.parametrize("tc", _CASES, ids=[c["case_id"] for c in _CASES])
async def test_case_matches_expected(tc: dict) -> None:
    result = await run_claim(ClaimInput(**tc["input"], mode="eval"), claim_id=tc["case_id"])
    exp = tc["expected"]
    d = result.decision
    dec = d.decision.value if d.decision else None

    assert dec == exp.get("decision"), f"{tc['case_id']} decision"
    if exp.get("approved_amount") is not None:
        assert d.approved_amount == exp["approved_amount"], f"{tc['case_id']} amount"
    if exp.get("rejection_reasons"):
        assert set(exp["rejection_reasons"]).issubset(set(d.rejection_reasons)), f"{tc['case_id']} reasons"
    assert len(result.trace) > 0, "trace must be populated for explainability"


async def test_tc011_graceful_degradation() -> None:
    tc = next(c for c in _CASES if c["case_id"] == "TC011")
    d = (await run_claim(ClaimInput(**tc["input"], mode="eval"), claim_id="TC011")).decision
    assert d.decision.value == "APPROVED"
    assert d.degraded is True
    assert d.confidence is not None and d.confidence < 0.95
    assert any("manual review" in n.lower() for n in d.notes)
    assert d.component_failures


@pytest.mark.parametrize("cid", ["TC001", "TC002", "TC003"])
async def test_gate_cases_stop_early(cid: str) -> None:
    tc = next(c for c in _CASES if c["case_id"] == cid)
    d = (await run_claim(ClaimInput(**tc["input"], mode="eval"))).decision
    assert d.decision is None
    assert d.status.value == "NEEDS_MEMBER_ACTION"
    assert d.document_problem is not None
    assert d.document_problem.message  # specific, non-empty


async def test_tc004_confidence_above_085() -> None:
    tc = next(c for c in _CASES if c["case_id"] == "TC004")
    d = (await run_claim(ClaimInput(**tc["input"], mode="eval"))).decision
    assert d.confidence > 0.85


async def test_tc012_confidence_above_090() -> None:
    tc = next(c for c in _CASES if c["case_id"] == "TC012")
    d = (await run_claim(ClaimInput(**tc["input"], mode="eval"))).decision
    assert d.confidence > 0.90
