"""LLM-as-judge eval over the ``~/Downloads/upload_docs/`` folders.

For each folder we treat it as a **complete pipeline input** — the image files are
OCR'd + extracted by the live model, and ``claim.json`` carries the rest of the claim
metadata. We run the **live** pipeline (Tesseract OCR → DeepSeek → adjudication) and
then ask the LLM **judge** whether the actual decision matches the folder's documented
``flow.txt`` expectation. There is no deterministic assertion of the outcome — the judge
decides (the only deterministic part is a tiny invariant sanity check that can never
disagree with a correct decision).

Every case is logged to **Langfuse**: a single trace with the pipeline steps as child
spans, a ``judge_match`` score, and an item in the ``plum-claims-judge`` **dataset**
(input = the claim, expected_output = the documented expectation, source_trace_id linking
back to the trace) so the run can be re-evaluated later.

Run with Langfuse keys set but ``ENABLE_OBSERVABILITY`` **off**, so ``run_claim``'s own
per-claim trace stays disabled and this module owns exactly one trace per case::

    LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... LANGFUSE_HOST=http://localhost:3766 \\
        uv run python -m eval.judge_eval
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.graph import run_claim
from app.llm.deepseek import deepseek_json
from app.observability.datasets import JUDGE_DATASET
from app.observability.tracing import get_langfuse
from app.schemas.claim import ClaimInput, DocumentInput
from app.schemas.decision import ClaimResult

UPLOAD_DOCS = Path.home() / "Downloads" / "upload_docs"

_JUDGE_PROMPT = (
    "You are a meticulous QA reviewer for a health-insurance claims pipeline. You are given "
    "(A) the DOCUMENTED EXPECTATION for a test scenario and (B) the pipeline's ACTUAL output. "
    "Decide whether the actual output is CORRECT for this scenario: the same decision/status, an "
    "approved amount equal to the expected one (exact rupees), and the key rejection reasons "
    "present in spirit. Wording may differ; judge the substance. If the scenario documents a "
    "stop for member action (missing/unreadable/mismatched documents), the actual must also stop "
    "for the same reason.\n\n"
    "Reply with ONLY a JSON object: "
    '{{"match": true|false, "reason": "<one concise sentence>", '
    '"expected_decision": "<short>", "actual_decision": "<short>"}}.\n\n'
    "=== A) DOCUMENTED EXPECTATION (from the scenario's flow.txt) ===\n{expected}\n\n"
    "=== B) ACTUAL PIPELINE OUTPUT ===\n{actual}\n"
)


def build_claim(folder: Path) -> tuple[ClaimInput, dict[str, Any]]:
    meta = json.loads((folder / "claim.json").read_text())
    docs = [
        DocumentInput(file_id=f"U{i + 1}", file_name=fn, image_ref=str(folder / fn))
        for i, fn in enumerate(meta["files"])
    ]
    claim = ClaimInput(**meta["input"], documents=docs, mode="live", claim_id=meta["case_id"])
    return claim, meta


def actual_summary(result: ClaimResult) -> dict[str, Any]:
    d = result.decision
    return {
        "decision": d.decision.value if d.decision else None,
        "status": d.status.value,
        "approved_amount": d.approved_amount,
        "rejection_reasons": d.rejection_reasons,
        "confidence": d.confidence,
        "degraded": d.degraded,
        "eligible_from": d.eligible_from,
        "member_message": d.document_problem.message if d.document_problem else None,
        "line_items": [
            {"description": li.description, "amount": li.amount, "status": li.status.value}
            for li in d.line_items
        ],
        "trace": [f"[{e.status.value}] {e.step}: {e.detail}" for e in result.trace],
    }


async def judge(expected_text: str, actual: dict[str, Any]) -> dict[str, Any]:
    prompt = _JUDGE_PROMPT.format(expected=expected_text, actual=json.dumps(actual, indent=2))
    data = await deepseek_json(prompt)
    return {
        "match": bool(data.get("match")),
        "reason": str(data.get("reason", "")),
        "expected_decision": str(data.get("expected_decision", "")),
        "actual_decision": str(data.get("actual_decision", "")),
    }


def _log_langfuse(
    meta: dict[str, Any],
    claim: ClaimInput,
    result: ClaimResult,
    verdict: dict[str, Any],
    expected_text: str,
) -> None:
    # Observability must NEVER corrupt the eval verdict — swallow everything (mirrors
    # app/observability/tracing._emit). A Langfuse hiccup can't flip a passing case to fail.
    try:
        lf = get_langfuse()
        if lf is None:
            return
        case_id = meta["case_id"]
        actual = actual_summary(result)
        trace_id = None
        with lf.start_as_current_observation(
            as_type="span",
            name=f"judge {case_id} — {meta['case_name']}",
            input=claim.model_dump(mode="json"),
            metadata={"judge": verdict, "case_id": case_id},
        ) as root:
            trace_id = lf.get_current_trace_id()  # capture inside the span → links the dataset item
            for ev in result.trace:
                with lf.start_as_current_observation(
                    as_type="span", name=ev.step, metadata={"status": ev.status.value}
                ) as span:
                    span.update(output=ev.detail)
            root.update(output=actual)
            lf.score_current_trace(
                name="judge_match", value=1.0 if verdict["match"] else 0.0, comment=verdict["reason"]
            )
        try:
            lf.create_dataset(name=JUDGE_DATASET, description="Live folder runs scored by the LLM judge.")
        except Exception:
            pass  # dataset already exists → reuse it
        lf.create_dataset_item(
            dataset_name=JUDGE_DATASET,
            input=claim.model_dump(mode="json"),
            expected_output={"case_name": meta["case_name"], "documentation": expected_text},
            metadata={"judge": verdict, "actual": actual},
            id=case_id,
            source_trace_id=trace_id,  # navigable from the dataset item back to its judge trace
        )
        lf.flush()
    except Exception:
        pass


async def main() -> int:
    if not UPLOAD_DOCS.exists():
        print(f"No upload_docs at {UPLOAD_DOCS} — run `uv run python -m eval.make_upload_docs` first.")
        return 1
    folders = sorted(p for p in UPLOAD_DOCS.iterdir() if p.is_dir())
    rows: list[tuple[str, bool, str, str]] = []
    n_pass = 0
    for folder in folders:
        claim, meta = build_claim(folder)
        expected_text = (folder / "flow.txt").read_text()
        try:
            result = await run_claim(claim, claim_id=meta["case_id"])
            actual = actual_summary(result)
            verdict = await judge(expected_text, actual)
            _log_langfuse(meta, claim, result, verdict, expected_text)
        except Exception as exc:  # noqa: BLE001
            verdict = {"match": False, "reason": f"EXCEPTION {type(exc).__name__}: {exc}", "actual_decision": "—"}
        ok = verdict["match"]
        n_pass += ok
        rows.append((meta["case_id"], ok, verdict.get("actual_decision", ""), verdict["reason"]))
        mark = "✅" if ok else "❌"
        print(f"{mark} {meta['case_id']} {folder.name[:46]:46} → {verdict.get('actual_decision', '')}")
        print(f"      judge: {verdict['reason']}")
    print(f"\nLLM-JUDGE: {n_pass}/{len(folders)} folders judged correct")
    _write_report(rows, n_pass)
    return 0 if n_pass == len(folders) else 1


def _write_report(rows: list[tuple[str, bool, str, str]], n_pass: int) -> None:
    out = get_settings().policy_file.parent / "EVAL_REPORT_JUDGE.md"
    lines = [
        "# LLM-as-Judge Eval Report (upload_docs folders)",
        "",
        f"**Result: {n_pass}/{len(rows)} folders judged correct.** Each folder under "
        "`~/Downloads/upload_docs/` is run through the *live* pipeline (Tesseract OCR → DeepSeek → "
        "adjudication), then an **LLM judge** decides whether the actual decision matches the "
        "folder's documented `flow.txt` expectation — no hard-coded assertions. Every case is "
        "logged to Langfuse (trace + `judge_match` score + `plum-claims-judge` dataset item). "
        "Generated by `eval/judge_eval.py`.",
        "",
        "| Case | Judge | Actual | Reason |",
        "|------|-------|--------|--------|",
    ]
    for cid, ok, actual, reason in rows:
        lines.append(f"| {cid} | {'✅' if ok else '❌'} | {actual} | {reason} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
