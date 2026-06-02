"use client";

import { motion } from "motion/react";

const STEPS = [
  { key: "intake", label: "Intake", desc: "Validate the submission" },
  { key: "classify_doc", label: "Classify documents", desc: "Identify each document type" },
  { key: "gate", label: "Document gate", desc: "Completeness · readability · patient match" },
  { key: "extract_doc", label: "Extract", desc: "Pull structured fields from documents" },
  { key: "merge_extractions", label: "Merge", desc: "Aggregate line items & totals" },
  { key: "eligibility", label: "Eligibility", desc: "Waiting · exclusions · pre-auth" },
  { key: "fraud", label: "Fraud & anomaly", desc: "Velocity & high-value signals" },
  { key: "adjudicate", label: "Adjudicate", desc: "Discount → co-pay → limits" },
  { key: "score_route", label: "Decision", desc: "Confidence & routing" },
  { key: "finalize", label: "Finalize", desc: "Assemble the audit trace" },
];

export function Pipeline({
  done,
  running,
}: {
  done: Set<string>;
  running: boolean;
}) {
  const gateStopped = done.has("format_blocker");
  const lastDone = STEPS.reduce((acc, s, i) => (done.has(s.key) ? i : acc), -1);
  const activeIndex = running ? lastDone + 1 : -1;

  return (
    <ol className="space-y-1">
      {STEPS.map((step, i) => {
        const isDone = done.has(step.key);
        const isActive = i === activeIndex && !gateStopped;
        const isGateFail = step.key === "gate" && gateStopped;
        const state = isGateFail ? "fail" : isDone ? "done" : isActive ? "active" : "pending";
        return (
          <li
            key={step.key}
            className="flex items-start gap-3 rounded-md px-2 py-1.5"
            style={{ opacity: state === "pending" ? 0.4 : 1, transition: "opacity .25s var(--ease-out)" }}
          >
            <span className="relative mt-0.5 grid size-5 shrink-0 place-items-center">
              {state === "done" && (
                <motion.span
                  initial={{ scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={{ duration: 0.25, ease: [0.23, 1, 0.32, 1] }}
                  className="grid size-5 place-items-center rounded-full bg-approved/20 text-[11px] text-approved"
                >
                  ✓
                </motion.span>
              )}
              {state === "fail" && (
                <span className="grid size-5 place-items-center rounded-full bg-rejected/20 text-[11px] text-rejected">
                  ✕
                </span>
              )}
              {state === "active" && (
                <span className="pulse-ring grid size-5 place-items-center rounded-full bg-brand/20 text-[10px] text-brand">
                  <span className="size-1.5 rounded-full bg-brand" />
                </span>
              )}
              {state === "pending" && <span className="size-2 rounded-full bg-ink-faint/40" />}
            </span>
            <div className="min-w-0">
              <p
                className={`text-sm ${
                  state === "active" ? "text-ink" : state === "fail" ? "text-rejected" : "text-ink-muted"
                }`}
              >
                {step.label}
              </p>
              <p className="text-xs text-ink-faint">{step.desc}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
