import type { ClaimResult } from "@/lib/types";
import { confidenceWord, decisionMeta, fmtINR, friendlyComponent } from "@/lib/format";
import { Card, CardHeader, Eyebrow, Pill } from "./primitives";
import { ReviewPanel } from "./ReviewPanel";
import { TraceTimeline } from "./Trace";

export function DecisionView({ result }: { result: ClaimResult }) {
  const d = result.decision;
  const meta = decisionMeta(d.decision);
  const isGate = d.decision === null;

  return (
    <div className="space-y-5">
      {/* headline */}
      <Card className={`overflow-hidden ${meta.border} animate-fade-up`}>
        <div className={`flex flex-wrap items-center justify-between gap-4 ${meta.bg} px-5 py-4`}>
          <div className="flex items-center gap-3">
            <span className={`size-2.5 rounded-full ${meta.dot}`} />
            <div>
              <Eyebrow>{result.claim_id}</Eyebrow>
              <h2 className={`text-2xl ${meta.text}`}>{meta.label}</h2>
            </div>
          </div>
          {!isGate && (
            <div className="text-right">
              <Eyebrow>Approved amount</Eyebrow>
              <p className="font-display text-3xl text-ink">{fmtINR(d.approved_amount)}</p>
            </div>
          )}
        </div>
        {d.reason && <p className="px-5 py-3.5 text-sm leading-relaxed text-ink-muted">{d.reason}</p>}
        <div className="flex flex-wrap gap-2 px-5 pb-4">
          {d.rejection_reasons.map((r) => (
            <Pill key={r} tone="rejected">
              {r.replace(/_/g, " ").toLowerCase()}
            </Pill>
          ))}
          {d.eligible_from && <Pill tone="neutral">covered from {d.eligible_from}</Pill>}
          {d.degraded && <Pill tone="review">some checks skipped · manual review</Pill>}
          {d.confidence != null && <Pill tone="neutral">{confidenceWord(d.confidence)}</Pill>}
        </div>
      </Card>

      {/* AI assessment (advisory - from the agentic reviewer, does not change the decision) */}
      {d.ai_assessment && (
        <Card className="border-brand/30 animate-fade-up">
          <CardHeader title="AI assessment" hint="advisory · doesn't change the decision" />
          <div className="space-y-3 px-5 py-4">
            <p className="text-sm leading-relaxed text-ink">{d.ai_assessment.summary}</p>
            {d.ai_assessment.recommended_action && (
              <p className="text-sm text-ink-muted">
                What to do: <span className="text-ink">{d.ai_assessment.recommended_action}</span>
              </p>
            )}
            {d.ai_assessment.concerns.length > 0 && (
              <ul className="space-y-1">
                {d.ai_assessment.concerns.map((c, i) => (
                  <li key={i} className="text-sm text-ink-muted">
                    <span className="text-brand">•</span> {c}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      )}

      {/* member action (gate stop) */}
      {d.document_problem && (
        <Card className="border-amber/30 animate-fade-up">
          <CardHeader title="What you need to do" />
          <div className="space-y-2 px-5 py-4">
            <p className="text-sm leading-relaxed text-ink">{d.document_problem.message}</p>
            <p className="text-sm text-amber">→ {d.document_problem.required_action}</p>
          </div>
        </Card>
      )}

      {/* financial breakdown */}
      {d.financial_breakdown && (
        <Card className="animate-fade-up">
          <CardHeader title="How the amount was calculated" />
          <dl className="divide-y divide-border text-sm">
            <Row k="Billed / covered base" v={fmtINR(d.financial_breakdown.base)} />
            {d.financial_breakdown.is_network && (
              <Row
                k="Network discount"
                v={`- ${fmtINR(d.financial_breakdown.network_discount)}`}
                accent="text-approved"
              />
            )}
            {d.financial_breakdown.copay > 0 && (
              <Row k="Co-pay" v={`- ${fmtINR(d.financial_breakdown.copay)}`} accent="text-partial" />
            )}
            {d.financial_breakdown.clamps.map((c) => (
              <Row key={c} k="Cap applied" v={c} accent="text-ink-faint" />
            ))}
            <div className="flex items-center justify-between px-5 py-3">
              <dt className="text-ink">Final approved</dt>
              <dd className="font-display text-lg text-ink">{fmtINR(d.financial_breakdown.final)}</dd>
            </div>
          </dl>
        </Card>
      )}

      {/* line items */}
      {d.line_items.length > 0 && (
        <Card className="animate-fade-up">
          <CardHeader title="Line items" hint={`${d.line_items.length} item(s)`} />
          <ul className="divide-y divide-border">
            {d.line_items.map((li, i) => (
              <li key={i} className="flex items-start justify-between gap-4 px-5 py-3">
                <div>
                  <p className="text-sm text-ink">{li.description}</p>
                  {li.reason && <p className="mt-0.5 text-xs text-ink-faint">{li.reason}</p>}
                </div>
                <div className="text-right">
                  <p className="text-sm text-ink-muted">{fmtINR(li.amount)}</p>
                  <Pill tone={li.status === "COVERED" ? "approved" : "rejected"}>
                    {li.status.toLowerCase()}
                  </Pill>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* fraud signals */}
      {d.fraud_signals.length > 0 && (
        <Card className="border-review/30 animate-fade-up">
          <CardHeader title="Anomaly signals" />
          <ul className="space-y-1.5 px-5 py-4">
            {d.fraud_signals.map((s, i) => (
              <li key={i} className="text-sm text-ink-muted">
                <span className="text-review">●</span> {s.detail}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {/* degradation + notes */}
      {(d.notes.length > 0 || d.component_failures.length > 0) && (
        <Card className="animate-fade-up">
          <CardHeader title="Processing notes" />
          <div className="space-y-2 px-5 py-4 text-sm text-ink-muted">
            {d.component_failures.map((f, i) => (
              <p key={i}>
                <span className="text-rejected">⚠</span>{" "}
                <span className="text-ink">{friendlyComponent(f.component)}</span> {f.impact}
              </p>
            ))}
            {d.notes.map((n, i) => (
              <p key={i}>{n}</p>
            ))}
          </div>
        </Card>
      )}

      {/* step-by-step processing - always visible, in plain language. The advisory AI agent's
          tool calls are intentionally excluded here (too technical); its plain-language take
          is the "AI assessment" card above, and its full detail lives in the Langfuse trace. */}
      {(() => {
        const steps = result.trace.filter(
          (e) => e.step !== "agentic_review" && !e.step.startsWith("agent."),
        );
        return (
          <Card className="animate-fade-up">
            <CardHeader title="How this claim was processed" hint={`${steps.length} steps`} />
            <TraceTimeline trace={steps} />
          </Card>
        );
      })()}

      {/* confidence math - kept optional (the only genuinely technical part) */}
      {d.confidence_breakdown && d.confidence_breakdown.deltas.length > 0 && (
        <details className="group animate-fade-up rounded-lg border border-border bg-surface/70 backdrop-blur-sm">
          <summary className="pressable flex cursor-pointer items-center justify-between px-5 py-3.5 text-sm text-ink-muted hover:text-ink">
            <span>How the confidence score was calculated</span>
            <span className="text-ink-faint transition-transform group-open:rotate-180">⌄</span>
          </summary>
          <ul className="divide-y divide-border border-t border-border text-sm">
            <Row k="Base" v={d.confidence_breakdown.base.toFixed(2)} />
            {d.confidence_breakdown.deltas.map((dl, i) => (
              <Row
                key={i}
                k={dl.reason}
                v={`${dl.delta > 0 ? "+" : ""}${dl.delta.toFixed(2)}`}
                accent={dl.delta > 0 ? "text-approved" : "text-rejected"}
              />
            ))}
          </ul>
        </details>
      )}

      {/* human review → Langfuse dataset */}
      <ReviewPanel result={result} />
    </div>
  );
}

function Row({ k, v, accent = "text-ink-muted" }: { k: string; v: string; accent?: string }) {
  return (
    <div className="flex items-center justify-between px-5 py-2.5">
      <dt className="text-ink-muted">{k}</dt>
      <dd className={accent}>{v}</dd>
    </div>
  );
}
