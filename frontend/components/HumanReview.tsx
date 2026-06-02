"use client";

import { useState } from "react";
import { resumeClaim, toFriendlyMessage } from "@/lib/api";
import { fmtINR } from "@/lib/format";
import type { ClaimResult, HumanReviewRequest, ReviewAction } from "@/lib/types";
import { Card, CardHeader, Eyebrow, Pill } from "./primitives";

const ACTIONS: { key: ReviewAction; label: string }[] = [
  { key: "APPROVED", label: "Approve" },
  { key: "PARTIAL", label: "Partial" },
  { key: "REJECTED", label: "Reject" },
];

/**
 * Surfaced when a claim PAUSED at a human-in-the-loop checkpoint (status PENDING_REVIEW).
 * Shows the proposed decision + why, then submits a verdict that RESUMES the graph from
 * its checkpoint; the resulting final ClaimResult is handed back via `onResolved`.
 */
export function HumanReview({
  claimId,
  request,
  onResolved,
}: {
  claimId: string;
  request: HumanReviewRequest;
  onResolved: (result: ClaimResult) => void;
}) {
  const [action, setAction] = useState<ReviewAction>("APPROVED");
  const [amount, setAmount] = useState<string>(String(request.claimed_amount));
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState<"idle" | "saving" | "error">("idle");
  const [error, setError] = useState("");

  const needsAmount = action !== "REJECTED";

  const submit = async () => {
    setStatus("saving");
    setError("");
    try {
      const result = await resumeClaim(claimId, {
        action,
        approved_amount: needsAmount ? Number(amount) || 0 : null,
        reviewer: reviewer.trim(),
        note: note.trim(),
      });
      onResolved(result);
    } catch (e) {
      setStatus("error");
      setError(toFriendlyMessage(e));
    }
  };

  const actionBtn = (active: boolean) =>
    `pressable rounded-md border px-3.5 py-2 text-sm transition-colors ${
      active ? "border-review bg-review/10 text-review" : "border-border text-ink-muted hover:bg-surface-2"
    }`;

  return (
    <Card className="border-review/30 animate-fade-up">
      <CardHeader title="Human review required" hint="paused for a person" />
      <div className="space-y-4 px-5 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone="review">paused · pending review</Pill>
          <span className="text-xs text-ink-faint">
            The pipeline routed this claim to {request.proposed_decision.replace(/_/g, " ").toLowerCase()} and
            saved its state. Submit a verdict to resume it.
          </span>
        </div>

        <p className="text-sm leading-relaxed text-ink-muted">{request.reason}</p>

        {request.fraud_signals.length > 0 && (
          <div className="space-y-1.5 rounded-md border border-border bg-surface-2/40 p-4">
            <Eyebrow>Why it was flagged</Eyebrow>
            <ul className="space-y-1">
              {request.fraud_signals.map((s, i) => (
                <li key={i} className="text-sm text-ink-muted">
                  <span className="text-review">●</span> {s.detail}
                </li>
              ))}
            </ul>
          </div>
        )}

        <fieldset className="space-y-3">
          <legend className="text-xs font-medium uppercase tracking-[0.12em] text-ink-faint">
            Your verdict
          </legend>
          <div className="flex flex-wrap gap-2">
            {ACTIONS.filter((a) => request.options.includes(a.key)).map((a) => (
              <button
                key={a.key}
                type="button"
                onClick={() => setAction(a.key)}
                aria-pressed={action === a.key}
                className={actionBtn(action === a.key)}
              >
                {a.label}
              </button>
            ))}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {needsAmount && (
              <label className="block">
                <span className="mb-1.5 block text-xs text-ink-faint">
                  Approved amount (₹) · claimed {fmtINR(request.claimed_amount)}
                </span>
                <input
                  type="number"
                  value={amount}
                  min={0}
                  max={request.claimed_amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
                />
              </label>
            )}
            <label className="block">
              <span className="mb-1.5 block text-xs text-ink-faint">Reviewer</span>
              <input
                type="text"
                value={reviewer}
                placeholder="e.g. Asha"
                onChange={(e) => setReviewer(e.target.value)}
                className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-brand"
              />
            </label>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-xs text-ink-faint">Note (optional)</span>
            <textarea
              value={note}
              rows={2}
              placeholder="Reasoning for this verdict…"
              onChange={(e) => setNote(e.target.value)}
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-brand"
            />
          </label>
        </fieldset>

        <button
          type="button"
          onClick={submit}
          disabled={status === "saving"}
          className="pressable rounded-md border border-brand bg-brand/10 px-3.5 py-2 text-sm text-brand hover:bg-brand/20 disabled:opacity-50"
        >
          {status === "saving" ? "Resuming…" : "Submit & resume"}
        </button>

        {status === "error" && (
          <p role="alert" aria-live="assertive" className="text-sm text-rejected">
            Could not resume: {error}
          </p>
        )}
      </div>
    </Card>
  );
}
