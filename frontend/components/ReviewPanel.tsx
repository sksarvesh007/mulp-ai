"use client";

import { useState } from "react";
import { submitReview, toFriendlyMessage } from "@/lib/api";
import type { ClaimResult, ReviewResponse } from "@/lib/types";
import { Card, CardHeader } from "./primitives";

type Verdict = "correct" | "wrong" | null;

// The aspects a reviewer can flag as wrong - these become `criteria` on the dataset item.
const CRITERIA: { key: string; label: string }[] = [
  { key: "decision", label: "Decision (approve / reject / review)" },
  { key: "approved_amount", label: "Approved amount" },
  { key: "rejection_reasons", label: "Rejection reasons" },
  { key: "financial_breakdown", label: "Amount breakdown" },
  { key: "confidence", label: "Confidence score" },
  { key: "trace", label: "Pipeline / trace steps" },
];

export function ReviewPanel({ result }: { result: ClaimResult }) {
  const [verdict, setVerdict] = useState<Verdict>(null);
  const [criteria, setCriteria] = useState<Set<string>>(new Set());
  const [notes, setNotes] = useState("");
  // "info" = a clean non-success (e.g. Langfuse not configured) - distinct from "error".
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "info" | "error">("idle");
  const [resp, setResp] = useState<ReviewResponse | null>(null);
  const [error, setError] = useState("");

  const toggle = (key: string) =>
    setCriteria((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const pick = (v: Verdict) => {
    setVerdict(v);
    setStatus("idle");
    setResp(null);
    setError("");
    setCriteria(new Set()); // don't carry a prior 'wrong' selection into a new verdict
    setNotes("");
  };

  // A 'wrong' verdict needs at least one signal; 'correct' never carries criteria/notes.
  const wrongIncomplete = verdict === "wrong" && criteria.size === 0 && notes.trim() === "";

  const save = async () => {
    const isCorrect = verdict === "correct";
    setStatus("saving");
    setError("");
    try {
      const r = await submitReview({
        claim_id: result.claim_id,
        is_correct: isCorrect,
        criteria: isCorrect ? [] : [...criteria],
        expected_notes: isCorrect ? "" : notes.trim(),
      });
      setResp(r);
      if (r.saved) {
        setStatus("saved");
      } else {
        setStatus("info"); // not persisted, but not a failure (e.g. Langfuse off)
        setError(r.reason ?? "Review was not persisted.");
      }
    } catch (e) {
      setStatus("error");
      setError(toFriendlyMessage(e));
    }
  };

  const btn =
    "pressable rounded-md border px-3.5 py-2 text-sm transition-colors disabled:opacity-50";

  return (
    <Card className="animate-fade-up">
      <CardHeader title="Review this decision" hint="help improve accuracy" />
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm text-ink-muted">
          Is this the right outcome? Your feedback is saved as an example - a correct one to confirm
          the decision, or a correction when it&apos;s wrong - so the system can be reviewed and
          improved later.
        </p>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => pick("correct")}
            aria-pressed={verdict === "correct"}
            className={`${btn} ${
              verdict === "correct"
                ? "border-approved bg-approved/10 text-approved"
                : "border-border text-ink-muted hover:bg-surface-2"
            }`}
          >
            ✓ Looks correct
          </button>
          <button
            type="button"
            onClick={() => pick("wrong")}
            aria-pressed={verdict === "wrong"}
            className={`${btn} ${
              verdict === "wrong"
                ? "border-rejected bg-rejected/10 text-rejected"
                : "border-border text-ink-muted hover:bg-surface-2"
            }`}
          >
            ✗ Looks wrong
          </button>
        </div>

        {verdict === "wrong" && (
          <fieldset className="space-y-3 rounded-md border border-border bg-surface-2/40 p-4 animate-fade-up">
            <legend className="px-1 text-xs font-medium uppercase tracking-[0.12em] text-ink-faint">
              What&apos;s wrong?
            </legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {CRITERIA.map((c) => (
                <label
                  key={c.key}
                  className="flex cursor-pointer items-center gap-2 text-sm text-ink-muted"
                >
                  <input
                    type="checkbox"
                    checked={criteria.has(c.key)}
                    onChange={() => toggle(c.key)}
                    className="size-4 accent-brand"
                  />
                  {c.label}
                </label>
              ))}
            </div>
            <div className="space-y-1.5">
              <label htmlFor="review-notes" className="text-sm text-ink-muted">
                What should the outcome have been?
              </label>
              <textarea
                id="review-notes"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                placeholder="e.g. Should be REJECTED - diabetes is within the 24-month waiting period."
                className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-brand"
              />
            </div>
          </fieldset>
        )}

        {verdict && status !== "saved" && (
          <div className="space-y-1.5">
            <button
              type="button"
              onClick={save}
              disabled={status === "saving" || wrongIncomplete}
              className={`${btn} border-brand bg-brand/10 text-brand hover:bg-brand/20`}
            >
              {status === "saving" ? "Saving…" : "Save to Langfuse dataset"}
            </button>
            {wrongIncomplete && (
              <p className="text-xs text-ink-faint">
                Select at least one criterion or describe the correct outcome.
              </p>
            )}
          </div>
        )}

        {status === "saved" && resp && (
          <p role="status" aria-live="polite" className="text-sm text-approved">
            ✓ Saved to dataset <code className="text-ink">{resp.dataset}</code>
            {resp.host && (
              <>
                {" - "}
                <a
                  href={resp.host}
                  target="_blank"
                  rel="noreferrer"
                  className="underline decoration-dotted hover:text-ink"
                >
                  open in Langfuse
                </a>
              </>
            )}
          </p>
        )}
        {status === "info" && (
          <p role="status" aria-live="polite" className="text-sm text-ink-muted">
            Not persisted - {error}
          </p>
        )}
        {status === "error" && (
          <p role="alert" aria-live="assertive" className="text-sm text-rejected">
            Could not save: {error}
          </p>
        )}
      </div>
    </Card>
  );
}
