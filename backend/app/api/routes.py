"""HTTP API. Contracts:

GET  /healthz                  → {status}
POST /claims          (JSON)   → ClaimResult                 (run + store)
GET  /claims                   → list of claim summaries
GET  /claims/{id}              → ClaimResult                 (404 if unknown)
GET  /claims/{id}/trace        → {claim_id, trace[]}         (404 if unknown)
POST /claims/{id}/resume (JSON)→ ClaimResult                 (resume a HITL-paused claim)
POST /claims/stream   (JSON)   → text/event-stream of live pipeline progress + result
POST /claims/upload   (multipart) → text/event-stream of live pipeline progress + result
                                    (live extraction path — streamed so it feels fast)
POST /eval                     → {passed, total, cases[]}    (runs the 12 test cases)
POST /review          (JSON)   → {saved, dataset, ...}       (human review → Langfuse dataset)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.db.repository import store
from app.graph import resume_claim, run_claim, run_claim_hitl, stream_claim
from app.observability.datasets import save_review
from app.schemas.claim import ClaimInput, DocumentInput
from app.schemas.decision import ClaimResult, HumanReviewVerdict
from app.schemas.enums import ClaimStatus
from app.schemas.review import ReviewRequest

router = APIRouter()

_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "data" / "uploads"


@router.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok"}


@router.get("/members")
async def list_members() -> list[dict[str, Any]]:
    from app.deps import get_policy

    return [
        {"member_id": m["member_id"], "name": m["name"], "relationship": m.get("relationship")}
        for m in get_policy().members
    ]


@router.get("/scenarios")
async def list_scenarios() -> list[dict[str, Any]]:
    """The 12 test cases as one-click demo presets for the UI."""
    from app.core.config import get_settings

    data = json.loads(get_settings().test_cases_file.read_text())["test_cases"]
    return [
        {
            "case_id": c["case_id"],
            "case_name": c["case_name"],
            "description": c["description"],
            "input": c["input"],
            "expected": c.get("expected", {}),  # ground truth — shown next to the live result
        }
        for c in data
    ]


@router.post("/samples/seed")
async def seed_sample_history(body: dict[str, Any]) -> dict[str, Any]:
    """Seed prior same-day claims for the 'multiple same-day claims' upload example, so the
    next real submission trips the same-day velocity rule. No-op if the ledger isn't configured."""
    from app.db.ledger import seed_history

    seeded = await seed_history(
        str(body.get("member_id", "")),
        str(body.get("treatment_date", "")),
        int(body.get("count", 2)),
    )
    return {"seeded": seeded}


@router.post("/claims", response_model=ClaimResult)
async def submit_claim(claim: ClaimInput) -> ClaimResult:
    # HITL claims run through the checkpointed graph: a MANUAL_REVIEW outcome PAUSES and
    # comes back as PENDING_REVIEW (resume via POST /claims/{id}/resume). Everything else
    # is identical to the standard non-checkpointed path.
    result = await run_claim_hitl(claim) if claim.hitl else await run_claim(claim)
    store.put(result, member_id=claim.member_id, category=claim.claim_category.value, claim=claim)
    return result


@router.post("/claims/{claim_id}/resume", response_model=ClaimResult)
async def resume_review(claim_id: str, verdict: HumanReviewVerdict) -> ClaimResult:
    """Submit a human verdict to RESUME a claim paused at a HITL checkpoint, producing the
    final decision. 404 if the claim is unknown or not currently pending review."""
    existing = store.get(claim_id)
    if existing is None or existing.decision.status != ClaimStatus.PENDING_REVIEW:
        raise HTTPException(status_code=404, detail=f"No claim {claim_id} pending review")
    claim = store.get_input(claim_id)
    result = await resume_claim(claim_id=claim_id, verdict=verdict)
    store.put(
        result,
        member_id=claim.member_id if claim else "",
        category=claim.claim_category.value if claim else "",
        claim=claim,
    )
    return result


@router.get("/claims")
async def list_claims() -> list[dict[str, Any]]:
    return store.list()


@router.get("/claims/{claim_id}", response_model=ClaimResult)
async def get_claim(claim_id: str) -> ClaimResult:
    result = store.get(claim_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return result


@router.get("/claims/{claim_id}/trace")
async def get_trace(claim_id: str) -> dict[str, Any]:
    result = store.get(claim_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return {"claim_id": claim_id, "trace": [e.model_dump() for e in result.trace]}


@router.post("/review")
async def submit_review(review: ReviewRequest) -> dict[str, Any]:
    """Record a human's verdict on a decision as a Langfuse dataset item.

    The stored claim (input + decision) is the example; the reviewer's verdict /
    correction is the expected output. These items are what evals later run against.
    """
    result = store.get(review.claim_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Claim {review.claim_id} not found")
    claim_input = store.get_input(review.claim_id)
    outcome = save_review(
        claim_id=review.claim_id,
        claim_input=claim_input.model_dump(mode="json") if claim_input is not None else {},
        actual=result.decision.model_dump(mode="json"),
        review={
            "is_correct": review.is_correct,
            "criteria": review.criteria,
            "expected_notes": review.expected_notes,
        },
    )
    return outcome


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Emit an SSE heartbeat if no pipeline event arrives within this window, so a platform proxy
# doesn't idle-timeout the streaming connection while a slow OCR/LLM node is running.
_SSE_HEARTBEAT_S = 10.0


def _sse_stream(claim: ClaimInput) -> StreamingResponse:
    """Stream ``stream_claim(claim)`` as Server-Sent Events. Progress/node events pass
    through; the ``result`` event is persisted and re-serialised to JSON. Shared by the
    JSON ``/claims/stream`` endpoint and the multipart ``/claims/upload`` endpoint so both
    drive the same live UI from the same formatter."""

    async def gen() -> AsyncIterator[str]:
        # A producer task drives the pipeline and pushes events onto a queue; the response loop
        # reads them with a timeout and emits an SSE comment heartbeat during long gaps (a slow
        # OCR/LLM node sends no events for many seconds). Without it the platform proxy
        # idle-timeouts the streaming connection mid-pipeline and the decision never arrives.
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def produce() -> None:
            try:
                async for event in stream_claim(claim):
                    await queue.put(("event", event))
            except Exception:  # never leak a traceback over the wire — signal a clean error frame
                await queue.put(("error", None))
            finally:
                await queue.put(("done", None))

        task = asyncio.create_task(produce())
        try:
            while True:
                try:
                    kind, event = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_S)
                except TimeoutError:
                    yield ": keepalive\n\n"  # SSE comment — ignored by clients, keeps the proxy warm
                    continue
                if kind == "done":
                    break
                if kind == "error":
                    yield f'data: {json.dumps({"type": "error"})}\n\n'
                    break
                # Both a final decision and a HITL pause carry a ClaimResult to persist (the paused
                # one is PENDING_REVIEW, so POST /claims/{id}/resume can find + resume it).
                if event.get("type") in ("result", "pending_review"):
                    result: ClaimResult = event["result"]
                    store.put(result, member_id=claim.member_id, category=claim.claim_category.value, claim=claim)
                    payload = {"type": event["type"], "result": result.model_dump(mode="json")}
                else:
                    payload = event
                yield f"data: {json.dumps(payload)}\n\n"
            yield 'data: {"type":"done"}\n\n'
        finally:
            task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/claims/stream")
async def stream(claim: ClaimInput) -> StreamingResponse:
    return _sse_stream(claim)


@router.post("/eval")
async def run_eval_endpoint() -> dict[str, Any]:
    from eval.harness import run_eval

    outcomes = await run_eval()
    return {
        "passed": sum(o.passed for o in outcomes),
        "total": len(outcomes),
        "cases": [
            {
                "case_id": o.case_id,
                "name": o.case_name,
                "passed": o.passed,
                "decision": o.decision,
                "approved_amount": o.approved_amount,
                "confidence": o.confidence,
                "mismatch": o.mismatch,
            }
            for o in outcomes
        ],
    }


@router.post("/claims/upload")
async def upload_claim(
    member_id: str = Form(...),
    policy_id: str = Form(...),
    claim_category: str = Form(...),
    treatment_date: str = Form(...),
    claimed_amount: int = Form(...),
    hospital_name: str | None = Form(None),
    files: list[UploadFile] = File(...),
) -> StreamingResponse:
    """Run the LIVE pipeline on uploaded documents and STREAM progress as SSE (same
    formatter as /claims/stream) so the upload feels fast — the live pipeline animates from
    real node events and the decision arrives as it's reached, not after a blocking wait."""
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    docs: list[DocumentInput] = []
    for i, f in enumerate(files):
        dest = _UPLOAD_DIR / f"{uuid.uuid4().hex}_{f.filename}"
        dest.write_bytes(await f.read())
        docs.append(DocumentInput(file_id=f"U{i + 1}", file_name=f.filename, image_ref=str(dest)))
    claim = ClaimInput(
        member_id=member_id,
        policy_id=policy_id,
        claim_category=claim_category,
        treatment_date=treatment_date,
        claimed_amount=claimed_amount,
        hospital_name=hospital_name,
        documents=docs,
        mode="live",
        hitl=True,  # an upload that routes to MANUAL_REVIEW pauses for human review (resumable)
    )
    return _sse_stream(claim)
