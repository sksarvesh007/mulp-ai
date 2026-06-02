import type { ClaimResult, Decision, ScenarioExpected } from "@/lib/types";
import { decisionMeta, fmtINR } from "@/lib/format";
import { Card, CardHeader, Pill } from "./primitives";

function decisionLabel(d: Decision | null): string {
  return d ? decisionMeta(d).label : "Stopped · action needed";
}

type RowResult = { label: string; expected: string; pipeline: string; match: boolean | null };

/**
 * Side-by-side of a scenario's **ground truth** (from docs/test_cases.json, served by the
 * API) and **our pipeline's live result** - with a deterministic per-field match check.
 * Nothing here is hardcoded: the expectation comes from the dataset, the result from the run.
 */
export function GroundTruth({
  expected,
  result,
  caseId,
}: {
  expected: ScenarioExpected;
  result: ClaimResult;
  caseId: string;
}) {
  const got = result.decision;

  const rows: RowResult[] = [
    {
      label: "Decision",
      expected: decisionLabel(expected.decision),
      pipeline: decisionLabel(got.decision),
      match: expected.decision === got.decision,
    },
  ];

  if (expected.approved_amount != null) {
    rows.push({
      label: "Approved amount",
      expected: fmtINR(expected.approved_amount),
      pipeline: fmtINR(got.approved_amount),
      match: expected.approved_amount === got.approved_amount,
    });
  }

  const expReasons = expected.rejection_reasons ?? [];
  if (expReasons.length > 0) {
    rows.push({
      label: "Rejection reasons",
      expected: expReasons.join(", ").toLowerCase().replace(/_/g, " "),
      pipeline: got.rejection_reasons.join(", ").toLowerCase().replace(/_/g, " ") || "-",
      match: expReasons.every((r) => got.rejection_reasons.includes(r)),
    });
  }

  const checks = rows.map((r) => r.match).filter((m): m is boolean => m !== null);
  const overall = checks.length > 0 && checks.every(Boolean);

  return (
    <Card className={`animate-fade-up ${overall ? "border-approved/30" : "border-rejected/30"}`}>
      <CardHeader title={`Expected vs actual · ${caseId}`} hint="reference result vs this system" />
      <div className="px-5 py-4">
        <Pill tone={overall ? "approved" : "rejected"}>
          {overall ? "✓ Matches the expected result" : "✗ Differs from the expected result"}
        </Pill>

        <div className="mt-4 overflow-hidden rounded-md border border-border">
          <div className="grid grid-cols-[1.1fr_1fr_1fr_auto] bg-surface-2/50 px-3 py-2 text-[11px] font-medium uppercase tracking-[0.1em] text-ink-faint">
            <span>Field</span>
            <span>Expected</span>
            <span>This system</span>
            <span className="text-right">·</span>
          </div>
          {rows.map((r) => (
            <div
              key={r.label}
              className="grid grid-cols-[1.1fr_1fr_1fr_auto] items-center border-t border-border px-3 py-2.5 text-sm"
            >
              <span className="text-ink-muted">{r.label}</span>
              <span className="text-ink">{r.expected}</span>
              <span className={r.match === false ? "text-rejected" : "text-ink"}>{r.pipeline}</span>
              <span className="text-right">
                {r.match === null ? (
                  <span className="text-ink-faint">-</span>
                ) : r.match ? (
                  <span className="text-approved">✓</span>
                ) : (
                  <span className="text-rejected">✕</span>
                )}
              </span>
            </div>
          ))}
        </div>

        {expected.system_must && expected.system_must.length > 0 && (
          <div className="mt-3">
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-ink-faint">
              The system must
            </p>
            <ul className="mt-1.5 space-y-1">
              {expected.system_must.map((m, i) => (
                <li key={i} className="text-sm text-ink-muted">
                  <span className="text-sky">•</span> {m}
                </li>
              ))}
            </ul>
          </div>
        )}

        {(expected.notes || expected.confidence_score) && (
          <p className="mt-3 text-xs text-ink-faint">
            {expected.notes}
            {expected.notes && expected.confidence_score ? " · " : ""}
            {expected.confidence_score ? `expected confidence ${expected.confidence_score}` : ""}
          </p>
        )}

        <p className="mt-3 text-[11px] text-ink-faint">
          The expected result is the reference for this example; this system&apos;s result is
          computed fresh on every run - nothing is pre-filled.
        </p>
      </div>
    </Card>
  );
}
