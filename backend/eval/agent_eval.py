"""LIVE end-to-end eval WITH the AI agent — runs all 12 cases through the exact upload
pipeline (render images → Tesseract OCR → DeepSeek classify+extract → deterministic
adjudication → advisory OpenAI-Agents-SDK reviewer) and reports, per case:

  • Expected behaviour   — the ground-truth decision/amount/reasons (test_cases.json)
  • What is required     — the case's ``system_must`` checklist
  • What the engine did   — the LIVE decision (from OCR+LLM perception, not pre-fed content)
  • What the AI agent chose — the advisory reviewer's recommended_action + summary + concerns

Unlike eval/live_harness.py (which uses run_claim and skips the agent), this consumes
``stream_claim`` — the same path the UI's upload + demo use — so the agentic node runs.

Run (sandbox DISABLED so tesseract can read files + DeepSeek is reachable):
    uv run python -m eval.agent_eval
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import get_settings
from app.graph import stream_claim
from eval.live_harness import build_live_claim


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run one case through the live streaming pipeline; capture decision + agent + live
    doc classification. Never raises — a failure is recorded on the row."""
    cid = case["case_id"]
    decision = None
    agent: dict[str, Any] | None = None
    live_doc_types: list[str] = []
    error: str | None = None
    try:
        async for e in stream_claim(build_live_claim(case), claim_id=cid):
            if e["type"] == "result":
                decision = e["result"].decision
                # what the LIVE OCR+LLM classified each uploaded image as
                live_doc_types = [
                    str(ev.data.get("doc_type"))
                    for ev in e["result"].trace
                    if ev.step == "classify_doc" and ev.data.get("doc_type")
                ]
            elif e["type"] == "ai_assessment":
                agent = e["assessment"]
    except Exception as exc:  # noqa: BLE001 - record, don't abort the whole sweep
        error = f"{type(exc).__name__}: {exc}"

    exp = case["expected"]
    eng = _engine_view(decision)
    return {
        "case_id": cid,
        "case_name": case["case_name"],
        "description": case["description"],
        "expected": {
            "decision": exp.get("decision"),
            "approved_amount": exp.get("approved_amount"),
            "rejection_reasons": exp.get("rejection_reasons"),
            "system_must": exp.get("system_must") or [],
            "notes": exp.get("notes"),
        },
        "engine": eng,
        "agent": agent,
        "live_doc_types": live_doc_types,
        "error": error,
        "match": _match(exp, decision),
    }


def _engine_view(decision: Any) -> dict[str, Any]:
    if decision is None:
        return {"decision": None, "status": None}
    d = decision
    return {
        "decision": d.decision.value if d.decision else None,
        "status": d.status.value if d.status else None,
        "approved_amount": d.approved_amount,
        "rejection_reasons": list(d.rejection_reasons),
        "reason": d.reason,
        "eligible_from": d.eligible_from,
        "confidence": d.confidence,
        "degraded": d.degraded,
        "document_problem": (d.document_problem.message if d.document_problem else None),
        "line_items": [
            {
                "description": li.description,
                "amount": li.amount,
                "status": li.status.value,
                "approved": li.approved_amount,
            }
            for li in d.line_items
        ],
        "financial_breakdown": (d.financial_breakdown.model_dump() if d.financial_breakdown else None),
        "fraud_signals": [s.type for s in d.fraud_signals],
    }


def _match(exp: dict[str, Any], decision: Any) -> dict[str, Any]:
    """Did the LIVE engine reproduce the ground truth? (Stop-cases expect decision=None.)"""
    got = decision.decision.value if (decision and decision.decision) else None
    decision_ok = exp.get("decision") == got
    amount_ok = exp.get("approved_amount") is None or (decision and exp["approved_amount"] == decision.approved_amount)
    reasons_ok = True
    if exp.get("rejection_reasons"):
        have = set(decision.rejection_reasons) if decision else set()
        reasons_ok = set(exp["rejection_reasons"]).issubset(have)
    return {
        "decision_ok": bool(decision_ok),
        "amount_ok": bool(amount_ok),
        "reasons_ok": bool(reasons_ok),
        "overall_ok": bool(decision_ok and amount_ok and reasons_ok),
    }


def _fmt_expected(exp: dict[str, Any]) -> str:
    if exp["decision"] is None:
        s = "STOP — needs member action (no claim decision)"
    else:
        s = exp["decision"]
        if exp.get("approved_amount") is not None:
            s += f" / ₹{exp['approved_amount']:,}"
    if exp.get("rejection_reasons"):
        s += f"  [{', '.join(exp['rejection_reasons'])}]"
    return s


def _fmt_engine(eng: dict[str, Any]) -> str:
    if eng.get("decision") is None:
        s = f"STOP ({eng.get('status') or 'no decision'})"
    else:
        s = eng["decision"]
        if eng.get("approved_amount") is not None:
            s += f" / ₹{eng['approved_amount']:,}"
    if eng.get("rejection_reasons"):
        s += f"  [{', '.join(eng['rejection_reasons'])}]"
    return s


def _print_case(r: dict[str, Any]) -> None:
    ok = r["match"]["overall_ok"] and not r["error"]
    mark = "✅" if ok else "❌"
    print(f"\n{mark} {r['case_id']} — {r['case_name']}")
    print(f"   live OCR/LLM saw : {r['live_doc_types'] or '(none readable)'}")
    print(f"   expected         : {_fmt_expected(r['expected'])}")
    print(f"   engine decided   : {_fmt_engine(r['engine'])}")
    if r["error"]:
        print(f"   ERROR            : {r['error']}")
    if r["agent"]:
        a = r["agent"]
        print(f"   AI agent action  : {a.get('recommended_action') or '(none)'}")
        print(f"   AI agent says    : {(a.get('summary') or '')[:160]}")
        if a.get("concerns"):
            print(f"   AI agent concerns: {a['concerns']}")
        print(f"   AI agent tools   : {a.get('tools_used')}")
    else:
        print("   AI agent         : (no assessment produced)")


def _write_report(rows: list[dict[str, Any]]) -> None:
    n_pass = sum(r["match"]["overall_ok"] and not r["error"] for r in rows)
    out = get_settings().policy_file.parent / "EVAL_REPORT_AGENT.md"
    L: list[str] = [
        "# Live Agentic Eval — engine vs. AI agent, across all 12 cases",
        "",
        f"**Engine reproduced the ground truth in {n_pass}/{len(rows)} cases via the LIVE path.**",
        "",
        "Every case's documents are rendered to images and pushed through the *exact upload "
        "pipeline* — **Tesseract OCR → DeepSeek (classify + extract) → deterministic adjudication "
        "→ advisory AI agent**. The agent is ADVISORY: it explains the decision and recommends a "
        "next step; it never changes the deterministic outcome. Generated by `eval/agent_eval.py`.",
        "",
        "| Case | Expected | Engine (live) | Match | AI agent recommends |",
        "|------|----------|---------------|:----:|---------------------|",
    ]
    for r in rows:
        ok = "✅" if (r["match"]["overall_ok"] and not r["error"]) else "❌"
        rec = (r["agent"] or {}).get("recommended_action") or ("ERROR" if r["error"] else "—")
        L.append(
            f"| {r['case_id']} | {_fmt_expected(r['expected'])} | {_fmt_engine(r['engine'])} | {ok} | {rec} |"
        )
    L += ["", "---", "", "## Per-case detail", ""]
    for r in rows:
        passed = r["match"]["overall_ok"] and not r["error"]
        L.append(f"### {r['case_id']} — {r['case_name']}  {'✅' if passed else '❌'}")
        L.append("")
        L.append(f"*{r['description']}*")
        L.append("")
        L.append(f"- **Live OCR/LLM classified the uploads as:** `{r['live_doc_types'] or '(none readable)'}`")
        L.append(f"- **Expected behaviour:** {_fmt_expected(r['expected'])}")
        if r["expected"]["system_must"]:
            L.append("- **What is required (`system_must`):**")
            for m in r["expected"]["system_must"]:
                L.append(f"  - {m}")
        L.append(f"- **Engine decided (live):** {_fmt_engine(r['engine'])}")
        eng = r["engine"]
        if eng.get("reason"):
            L.append(f"  - reason: {eng['reason']}")
        if eng.get("document_problem"):
            L.append(f"  - member message: {eng['document_problem']}")
        if eng.get("eligible_from"):
            L.append(f"  - eligible from: {eng['eligible_from']}")
        if eng.get("fraud_signals"):
            L.append(f"  - fraud signals: {', '.join(eng['fraud_signals'])}")
        if eng.get("degraded"):
            L.append(f"  - degraded: true · confidence: {eng.get('confidence')}")
        if eng.get("line_items"):
            L.append("  - line items:")
            for li in eng["line_items"]:
                L.append(
                    f"    - {li['description']}: ₹{li['amount']:,} → {li['status']} "
                    f"(approved ₹{li['approved']:,})"
                )
        if eng.get("financial_breakdown"):
            fb = eng["financial_breakdown"]
            L.append(
                f"  - money: base ₹{fb['base']:,} → −discount ₹{fb['network_discount']:,} "
                f"→ −co-pay ₹{fb['copay']:,} → final ₹{fb['final']:,}"
            )
        if r["error"]:
            L.append(f"- **ERROR:** {r['error']}")
        if r["agent"]:
            a = r["agent"]
            L.append(f"- **AI agent recommends:** {a.get('recommended_action') or '(none)'}")
            L.append(f"- **AI agent summary:** {a.get('summary') or ''}")
            if a.get("concerns"):
                L.append("- **AI agent concerns:**")
                for c in a["concerns"]:
                    L.append(f"  - {c}")
            L.append(f"- **AI agent tools used:** {', '.join(a.get('tools_used') or []) or '(none)'}")
        else:
            L.append("- **AI agent:** (no assessment produced)")
        L.append("")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"\nReport → {out}")


async def main() -> int:
    s = get_settings()
    print(
        f"agent enabled={s.enable_agentic_review}  has_llm={s.has_llm}  "
        f"provider={s.llm_provider}  model={s.deepseek_model}"
    )
    if not (s.enable_agentic_review and s.has_llm):
        print("⚠️  agent is OFF (ENABLE_AGENTIC_REVIEW / key) — the AI-agent column will be empty.")
    cases = json.loads(s.test_cases_file.read_text())["test_cases"]
    rows: list[dict[str, Any]] = []
    for case in cases:
        print(f"\n… running {case['case_id']} (live OCR+LLM+agent) …", flush=True)
        r = await run_case(case)
        _print_case(r)
        rows.append(r)
    n_pass = sum(r["match"]["overall_ok"] and not r["error"] for r in rows)
    print(f"\n{'=' * 60}\nENGINE vs GROUND TRUTH (live): {n_pass}/{len(rows)} matched")
    (s.policy_file.parent / "eval_report_agent.json").write_text(json.dumps(rows, indent=2, default=str))
    _write_report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
