from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.decision import ClaimDecision, ClaimResult
from app.schemas.enums import ClaimStatus, Decision

client = TestClient(app)


def _tc004(cases) -> dict:
    return {**cases["TC004"]["input"], "mode": "eval"}


def test_healthz() -> None:
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_submit_and_get_claim(cases) -> None:
    payload = {**_tc004(cases), "claim_id": "API_TC004"}
    r = client.post("/claims", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["decision"] == "APPROVED"
    assert body["decision"]["approved_amount"] == 1350
    assert body["trace"]

    got = client.get(f"/claims/{body['claim_id']}")
    assert got.status_code == 200
    assert got.json()["decision"]["approved_amount"] == 1350


def test_list_claims(cases) -> None:
    client.post("/claims", json={**_tc004(cases), "claim_id": "API_LIST"})
    r = client.get("/claims")
    assert r.status_code == 200
    assert any(c["claim_id"] == "API_LIST" for c in r.json())


def test_get_unknown_claim_404() -> None:
    assert client.get("/claims/NOPE").status_code == 404
    assert client.get("/claims/NOPE/trace").status_code == 404


def test_get_trace(cases) -> None:
    client.post("/claims", json={**_tc004(cases), "claim_id": "API_TRACE"})
    r = client.get("/claims/API_TRACE/trace")
    assert r.status_code == 200
    assert len(r.json()["trace"]) > 0


def test_gate_case_via_api(cases) -> None:
    r = client.post("/claims", json={**cases["TC001"]["input"], "mode": "eval", "claim_id": "API_TC001"})
    body = r.json()
    assert body["decision"]["decision"] is None
    assert body["decision"]["status"] == "NEEDS_MEMBER_ACTION"
    assert body["decision"]["document_problem"]["problem_type"] == "DOCUMENT_PRESENCE"


def test_stream_sse(cases) -> None:
    r = client.post("/claims/stream", json={**_tc004(cases), "claim_id": "API_STREAM"})
    assert r.status_code == 200
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    types = {e["type"] for e in events}
    assert "node" in types or "progress" in types
    result_events = [e for e in events if e["type"] == "result"]
    assert result_events and result_events[0]["result"]["decision"]["approved_amount"] == 1350


def test_members_endpoint() -> None:
    r = client.get("/members")
    assert r.status_code == 200
    members = r.json()
    assert any(m["member_id"] == "EMP001" and m["name"] == "Rajesh Kumar" for m in members)


def test_scenarios_endpoint() -> None:
    r = client.get("/scenarios")
    assert r.status_code == 200
    scenarios = r.json()
    assert len(scenarios) == 12
    assert scenarios[0]["case_id"] == "TC001"
    assert "input" in scenarios[0]
    # ground truth travels with each scenario so the UI can show it beside the live result
    assert "expected" in scenarios[0]
    tc004 = next(s for s in scenarios if s["case_id"] == "TC004")
    assert tc004["expected"]["decision"] == "APPROVED"
    assert tc004["expected"]["approved_amount"] == 1350


def test_eval_endpoint() -> None:
    r = client.post("/eval")
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] == 12 and body["total"] == 12


def test_upload_route_streams_sse(monkeypatch) -> None:
    """The upload endpoint now STREAMS the live pipeline as SSE (same formatter as
    /claims/stream) instead of blocking — so it feels fast. It must still run the LIVE
    backend on the uploaded files and deliver a final ``result`` event."""
    canned = ClaimResult(
        claim_id="UP1",
        decision=ClaimDecision(decision=Decision.APPROVED, status=ClaimStatus.DECIDED, approved_amount=1000),
    )

    async def fake_stream_claim(claim, claim_id=None):  # type: ignore[no-untyped-def]
        assert claim.mode.value == "live"
        assert claim.documents[0].image_ref
        yield {"type": "node", "node": "intake"}
        yield {"type": "result", "result": canned}

    monkeypatch.setattr("app.api.routes.stream_claim", fake_stream_claim)
    files = {"files": ("bill.png", b"\x89PNG fake bytes", "image/png")}
    data = {
        "member_id": "EMP001",
        "policy_id": "PLUM_GHI_2024",
        "claim_category": "CONSULTATION",
        "treatment_date": "2024-11-01",
        "claimed_amount": "1500",
    }
    r = client.post("/claims/upload", data=data, files=files)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert "node" in types and "done" in types
    result = next(e for e in events if e["type"] == "result")["result"]
    assert result["decision"]["approved_amount"] == 1000
    # the streamed result is persisted (the shared formatter stores it)
    assert client.get("/claims/UP1").json()["decision"]["approved_amount"] == 1000


def test_invalid_claim_body_returns_422() -> None:
    r = client.post("/claims", json={"member_id": "EMP001"})  # missing required fields
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "validation_error"
    assert isinstance(body["detail"], list)


def test_bad_enum_returns_422(cases) -> None:
    payload = {**cases["TC004"]["input"], "mode": "eval", "claim_category": "NOT_A_CATEGORY"}
    r = client.post("/claims", json=payload)
    assert r.status_code == 422


def test_unhandled_error_returns_clean_500(monkeypatch, cases) -> None:
    async def boom(claim):  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom")

    monkeypatch.setattr("app.api.routes.run_claim", boom)
    safe_client = TestClient(app, raise_server_exceptions=False)
    r = safe_client.post("/claims", json={**cases["TC004"]["input"], "mode": "eval"})
    assert r.status_code == 500
    assert r.json()["error"] == "internal_error"
    assert "kaboom" not in r.text  # no stack trace / internal detail leaked


def test_negative_amount_returns_422(cases) -> None:
    payload = {**cases["TC004"]["input"], "mode": "eval", "claimed_amount": -100}
    r = client.post("/claims", json=payload)
    assert r.status_code == 422


def test_review_unknown_claim_404() -> None:
    r = client.post("/review", json={"claim_id": "NOPE", "is_correct": False})
    assert r.status_code == 404


def test_review_saves_to_dataset(monkeypatch, cases) -> None:
    # process a claim so it (and its input) is in the store
    client.post("/claims", json={**_tc004(cases), "claim_id": "API_REVIEW"})

    captured: dict = {}

    def fake_save_review(*, claim_id, claim_input, actual, review):  # type: ignore[no-untyped-def]
        captured.update(claim_id=claim_id, claim_input=claim_input, actual=actual, review=review)
        return {"saved": True, "dataset": "plum-claims-reviewed", "item_id": claim_id}

    monkeypatch.setattr("app.api.routes.save_review", fake_save_review)
    r = client.post(
        "/review",
        json={
            "claim_id": "API_REVIEW",
            "is_correct": False,
            "criteria": ["approved_amount", "reasons"],
            "expected_notes": "Should have been rejected for waiting period.",
        },
    )
    assert r.status_code == 200
    assert r.json()["saved"] is True and r.json()["dataset"] == "plum-claims-reviewed"
    # the endpoint fed the saver the original input + the actual decision
    assert captured["claim_id"] == "API_REVIEW"
    assert captured["claim_input"]["member_id"] == "EMP001"
    assert captured["actual"]["approved_amount"] == 1350
    assert captured["review"]["is_correct"] is False
    assert captured["review"]["criteria"] == ["approved_amount", "reasons"]
