"""The /analytics aggregation over the claim store."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.db.repository import ClaimRepository
from app.main import app
from app.schemas.decision import ClaimDecision, ClaimResult
from app.schemas.enums import ClaimStatus, Decision

client = TestClient(app)


def _result(cid: str, decision, status: ClaimStatus, *, approved=None, confidence=None, degraded=False) -> ClaimResult:
    return ClaimResult(
        claim_id=cid,
        decision=ClaimDecision(
            decision=decision, status=status, approved_amount=approved, confidence=confidence, degraded=degraded
        ),
        trace=[],
    )


def test_analytics_endpoint_shape() -> None:
    r = client.get("/analytics")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "total_claims", "approved", "partial", "rejected", "review", "action",
        "approval_rate", "total_approved_amount", "avg_confidence", "degraded_count",
        "by_decision", "by_category", "over_time", "confidence_buckets",
    ):
        assert key in body
    assert len(body["confidence_buckets"]) == 5


def test_analytics_aggregation(tmp_path) -> None:
    repo = ClaimRepository(f"sqlite:///{tmp_path / 'a.db'}")
    repo.put(_result("A1", Decision.APPROVED, ClaimStatus.DECIDED, approved=1000, confidence=0.9), category="DENTAL")
    repo.put(_result("A2", Decision.APPROVED, ClaimStatus.DECIDED, approved=500, confidence=0.8), category="DENTAL")
    repo.put(_result("P1", Decision.PARTIAL, ClaimStatus.DECIDED, approved=300, confidence=0.7), category="VISION")
    repo.put(_result("R1", Decision.REJECTED, ClaimStatus.DECIDED, confidence=0.95, degraded=True), category="VISION")
    repo.put(_result("N1", None, ClaimStatus.NEEDS_MEMBER_ACTION), category="DENTAL")
    repo.put(_result("H1", None, ClaimStatus.PENDING_REVIEW), category="VISION")

    a = repo.analytics()
    assert a["total_claims"] == 6
    assert a["approved"] == 2 and a["partial"] == 1 and a["rejected"] == 1
    assert a["action"] == 1 and a["review"] == 1  # None+NEEDS_ACTION → action; None+PENDING → review
    assert a["total_approved_amount"] == 1800
    assert a["approval_rate"] == round(3 / 4, 4)  # (approved+partial)/(approved+partial+rejected)
    assert a["degraded_count"] == 1
    # avg confidence over the four claims that have one
    assert a["avg_confidence"] == round((0.9 + 0.8 + 0.7 + 0.95) / 4, 4)
    cats = {c["category"]: c for c in a["by_category"]}
    assert cats["DENTAL"]["total"] == 3 and cats["DENTAL"]["approved"] == 2 and cats["DENTAL"]["action"] == 1
    assert cats["VISION"]["total"] == 3
    # confidence histogram: 0.7→bucket3, 0.8→bucket4, 0.9→bucket4, 0.95→bucket4
    assert a["confidence_buckets"][4]["count"] == 3 and a["confidence_buckets"][3]["count"] == 1


def test_analytics_empty_store(tmp_path) -> None:
    repo = ClaimRepository(f"sqlite:///{tmp_path / 'empty.db'}")
    a = repo.analytics()
    assert a["total_claims"] == 0 and a["approval_rate"] == 0.0 and a["avg_confidence"] is None
    assert a["by_decision"] == [] and a["over_time"] == []
