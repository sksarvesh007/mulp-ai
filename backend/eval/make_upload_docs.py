"""Generate ``~/Downloads/upload_docs/<docN_slug>/`` folders — one per claim scenario.

Each folder holds the scenario's **document images** (upload them in the app's
"Upload documents · LLM" tab) and a **flow.txt** describing the form values to enter and
the exact expected pipeline flow + outcome (taken from the verified engine, eval mode).

Run:  uv run python -m eval.make_upload_docs
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.graph import run_claim
from app.policy.repository import PolicyRepository
from app.schemas.claim import ClaimInput
from eval.docgen import _lines_for, _render

OUT = Path.home() / "Downloads" / "upload_docs"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:32]


def _fmt_inr(n: int | None) -> str:
    return "—" if n is None else f"Rs {n:,}"


async def main() -> None:
    settings = get_settings()
    policy = PolicyRepository.from_file()
    members = {m["member_id"]: m["name"] for m in policy.members}
    cases = json.loads(settings.test_cases_file.read_text())["test_cases"]

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    index: list[str] = ["UPLOAD DOCS — 12 claim scenarios for the Plum Claims app", "=" * 58, ""]

    for n, case in enumerate(cases, 1):
        inp = case["input"]
        # category is in the folder name so the required form value is impossible to miss
        folder = OUT / f"doc{n}_{_slug(inp['claim_category'])}_{_slug(case['case_name'])}"
        folder.mkdir(parents=True, exist_ok=True)

        # 1) render the document image(s)
        files: list[str] = []
        for i, doc in enumerate(inp["documents"]):
            doc_type = doc.get("actual_type", "DOCUMENT")
            lines = _lines_for(doc_type, doc.get("content"), doc.get("patient_name_on_doc"))
            fname = f"{doc_type.lower()}_{i + 1}.png"
            _render(lines, folder / fname, unreadable=(doc.get("quality") == "UNREADABLE"))
            files.append(fname)

        # 2) run the scenario through the engine (eval mode = the verified outcome)
        result = await run_claim(ClaimInput(**inp, mode="eval"), claim_id=case["case_id"])
        d = result.decision
        decision = d.decision.value if d.decision else "NEEDS_MEMBER_ACTION (claim stopped early)"

        # 3) write flow.txt
        member = members.get(inp["member_id"], inp["member_id"])
        lines_out: list[str] = []
        lines_out.append(f"SCENARIO {case['case_id']} — {case['case_name']}")
        lines_out.append("=" * 60)
        lines_out.append("")
        lines_out.append(">>> STEP 1 — SET THESE FORM VALUES *BEFORE* RUNNING (this is what made the trace differ!)")
        lines_out.append(f"    Member         : {inp['member_id']}  ({member})")
        lines_out.append(f"    Category       : {inp['claim_category']}   <-- IMPORTANT, the default is CONSULTATION")
        lines_out.append(f"    Treatment date : {inp.get('treatment_date', '-')}")
        lines_out.append(f"    Claimed amount : {inp.get('claimed_amount', '-')}")
        lines_out.append(f"    Hospital       : {inp.get('hospital_name') or '(leave blank)'}")
        lines_out.append("")
        lines_out.append(">>> STEP 2 — UPLOAD THESE FILES (in this folder), then click 'Run with AI extraction':")
        for f in files:
            lines_out.append(f"    - {f}")
        lines_out.append("")
        lines_out.append(f"WHAT THIS TESTS: {case['description']}")
        lines_out.append("")
        lines_out.append("EXPECTED OUTCOME:")
        lines_out.append(f"  Decision        : {decision}")
        if d.approved_amount is not None:
            lines_out.append(f"  Approved amount : {_fmt_inr(d.approved_amount)}")
        if d.rejection_reasons:
            lines_out.append(f"  Reasons         : {', '.join(d.rejection_reasons)}")
        if d.eligible_from:
            lines_out.append(f"  Eligible from   : {d.eligible_from}")
        if d.confidence is not None:
            lines_out.append(f"  Confidence      : {d.confidence}")
        if d.reason:
            lines_out.append(f"  Reason          : {d.reason}")
        if d.document_problem:
            lines_out.append(f"  Member message  : {d.document_problem.message}")
        if d.line_items:
            lines_out.append("  Line items      :")
            for li in d.line_items:
                extra = f" ({li.reason})" if li.reason else ""
                lines_out.append(f"     - {li.description}: {_fmt_inr(li.amount)} -> {li.status.value}{extra}")
        lines_out.append("")
        lines_out.append("EXPECTED PIPELINE FLOW (stage by stage):")
        for ev in result.trace:
            lines_out.append(f"  [{ev.status.value.upper():4}] {ev.step} — {ev.detail}")
        lines_out.append("")

        caveats = []
        if inp.get("claims_history"):
            caveats.append(
                "This scenario's MANUAL_REVIEW comes from prior same-day claims history, which the "
                "upload form cannot carry. Uploading only the documents will NOT reproduce the fraud "
                "flag — use the 'Try a scenario' chip (TC009) or the API with claims_history."
            )
        if inp.get("simulate_component_failure"):
            caveats.append(
                "This scenario simulates a mid-pipeline component failure (a flag, not something in a "
                "document). Uploading the documents alone won't trigger it — use the 'Try a scenario' "
                "chip (TC011) or the API with simulate_component_failure=true."
            )
        if any(doc.get("quality") == "UNREADABLE" for doc in inp["documents"]):
            caveats.append(
                "One image is intentionally blurred to be unreadable, so OCR fails and the gate asks "
                "for a re-upload — this is the expected behaviour for this scenario."
            )
        if caveats:
            lines_out.append("NOTES:")
            for c in caveats:
                lines_out.append(f"  ! {c}")
            lines_out.append("")

        (folder / "flow.txt").write_text("\n".join(lines_out), encoding="utf-8")
        # Machine-readable, *complete* input: the full claim metadata (minus documents,
        # which are the image files) so the folder is a self-contained pipeline input —
        # used by eval/judge_eval.py. ``files`` lists the images to OCR.
        claim_meta = {k: v for k, v in inp.items() if k != "documents"}
        (folder / "claim.json").write_text(
            json.dumps(
                {
                    "case_id": case["case_id"],
                    "case_name": case["case_name"],
                    "member_name": member,
                    "files": files,
                    "input": claim_meta,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        index.append(f"{folder.name}/  →  {case['case_id']} {case['case_name']} ({decision})")

    index += [
        "",
        "HOW TO USE:",
        "  1. Open the app, go to the 'Upload documents · LLM' tab.",
        "  2. Pick a doc folder, upload all its image(s), and enter the form values from its flow.txt.",
        "  3. Click 'Run with AI extraction' — the live pipeline OCRs + extracts + adjudicates.",
        "  Folders are also one-click via the 'Try a scenario' chips (TC001–TC012).",
    ]
    (OUT / "README.txt").write_text("\n".join(index), encoding="utf-8")
    print(f"Wrote {len(cases)} scenario folders to {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
