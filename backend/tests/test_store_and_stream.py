from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.db.repository import ClaimRepository
from app.main import app
from app.schemas.claim import ClaimInput
from app.schemas.decision import ClaimDecision, ClaimResult
from app.schemas.enums import ClaimStatus, Decision

client = TestClient(app)


def _result(cid: str, decision: Decision = Decision.APPROVED, amount: int = 1000) -> ClaimResult:
    return ClaimResult(
        claim_id=cid,
        decision=ClaimDecision(decision=decision, status=ClaimStatus.DECIDED, approved_amount=amount),
    )


def _claim(cid: str) -> ClaimInput:
    return ClaimInput(
        claim_id=cid,
        member_id="EMP001",
        policy_id="PLUM_GHI_2024",
        claim_category="CONSULTATION",
        treatment_date="2024-11-01",
        claimed_amount=1500,
    )


def test_repository_put_get_list_persist_upsert(tmp_path) -> None:
    url = f"sqlite:///{tmp_path / 'claims.db'}"
    repo = ClaimRepository(url)

    repo.put(_result("X1"), member_id="EMP001", category="CONSULTATION")
    got = repo.get("X1")
    assert got is not None and got.decision.approved_amount == 1000

    rows = repo.list()
    assert rows[0]["claim_id"] == "X1"
    assert rows[0]["member_id"] == "EMP001"
    assert rows[0]["category"] == "CONSULTATION"
    assert "created_at" in rows[0]

    assert repo.get("UNKNOWN") is None

    # persistence — a fresh repository on the same file sees the record
    assert ClaimRepository(url).get("X1") is not None

    # upsert — re-putting the same claim_id updates in place
    repo.put(_result("X1", decision=Decision.REJECTED, amount=0))
    assert repo.get("X1").decision.decision == Decision.REJECTED
    assert len(repo.list()) == 1


def test_repository_migrates_missing_columns(tmp_path) -> None:
    """A DB created with an older, narrower schema is brought forward additively, and a
    row that pre-existed the migration (NULL result_json / created_at) degrades gracefully
    instead of crashing get()/list()."""
    from sqlalchemy import create_engine, text

    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:  # legacy table missing every column added since
        conn.execute(text("CREATE TABLE claims (claim_id VARCHAR PRIMARY KEY, member_id VARCHAR)"))
        conn.execute(text("INSERT INTO claims (claim_id, member_id) VALUES ('LEGACY', 'EMP009')"))

    repo = ClaimRepository(url)  # __init__ should ALTER in the missing columns

    # the pre-existing legacy row has no result_json / created_at → read paths must not crash
    assert repo.get("LEGACY") is None
    assert repo.get_input("LEGACY") is None
    legacy_row = next(r for r in repo.list() if r["claim_id"] == "LEGACY")
    assert legacy_row["created_at"] is None

    # and a freshly-written row works normally on the migrated schema
    repo.put(_result("M1"), member_id="EMP001", category="CONSULTATION", claim=_claim("M1"))
    assert repo.get("M1") is not None
    assert repo.get_input("M1").member_id == "EMP001"
    assert next(r for r in repo.list() if r["claim_id"] == "M1")["category"] == "CONSULTATION"


def test_repository_stores_and_returns_claim_input(tmp_path) -> None:
    repo = ClaimRepository(f"sqlite:///{tmp_path / 'claims.db'}")

    # put without a claim → no stored input
    repo.put(_result("NOINPUT"))
    assert repo.get_input("NOINPUT") is None

    # put with the original claim → get_input round-trips it
    repo.put(_result("WITHINPUT"), claim=_claim("WITHINPUT"))
    restored = repo.get_input("WITHINPUT")
    assert restored is not None
    assert restored.member_id == "EMP001" and restored.claimed_amount == 1500

    # unknown id → None
    assert repo.get_input("UNKNOWN") is None


async def test_stream_degraded_gate_path(monkeypatch, cases) -> None:
    """Stream a claim where a classify worker fails → gate stops the claim, and the
    streamed result must still surface degraded + component_failures."""
    from app.extraction import eval_extractor

    original = eval_extractor.EvalExtractor.classify
    counter = {"n": 0}

    async def flaky(self, doc):  # type: ignore[no-untyped-def]
        counter["n"] += 1
        if counter["n"] == 1:
            raise RuntimeError("boom")
        return await original(self, doc)

    monkeypatch.setattr(eval_extractor.EvalExtractor, "classify", flaky)

    r = client.post(
        "/claims/stream",
        json={**cases["TC004"]["input"], "mode": "eval", "claim_id": "STREAM_DEGRADED"},
    )
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    result = next(e for e in events if e["type"] == "result")["result"]
    assert result["decision"]["degraded"] is True
    assert result["decision"]["component_failures"]
