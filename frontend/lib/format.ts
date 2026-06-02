import type { Decision } from "./types";

export const fmtINR = (n: number | null | undefined): string =>
  n == null ? "-" : `₹${n.toLocaleString("en-IN")}`;

type DecisionMeta = { label: string; text: string; bg: string; border: string; dot: string };

export const DECISION_META: Record<string, DecisionMeta> = {
  APPROVED: { label: "Approved", text: "text-approved", bg: "bg-approved/10", border: "border-approved/30", dot: "bg-approved" },
  PARTIAL: { label: "Partially approved", text: "text-partial", bg: "bg-partial/10", border: "border-partial/30", dot: "bg-partial" },
  REJECTED: { label: "Rejected", text: "text-rejected", bg: "bg-rejected/10", border: "border-rejected/30", dot: "bg-rejected" },
  MANUAL_REVIEW: { label: "Manual review", text: "text-review", bg: "bg-review/10", border: "border-review/30", dot: "bg-review" },
  NEEDS_MEMBER_ACTION: { label: "Action needed", text: "text-amber", bg: "bg-amber/10", border: "border-amber/30", dot: "bg-amber" },
};

export function decisionMeta(decision: Decision | null): DecisionMeta {
  if (decision) return DECISION_META[decision];
  return DECISION_META.NEEDS_MEMBER_ACTION;
}

export const TRACE_STATUS: Record<string, { text: string; dot: string; glyph: string }> = {
  pass: { text: "text-approved", dot: "bg-approved", glyph: "✓" },
  fail: { text: "text-rejected", dot: "bg-rejected", glyph: "✕" },
  skip: { text: "text-ink-faint", dot: "bg-ink-faint", glyph: "-" },
  info: { text: "text-sky", dot: "bg-sky", glyph: "•" },
};

export const titleCase = (s: string): string =>
  s.replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// Plain-language confidence band - friendlier than a raw 0-1 score for non-technical users.
export function confidenceWord(c: number): string {
  if (c >= 0.85) return "High confidence";
  if (c >= 0.6) return "Moderate confidence";
  return "Low confidence";
}

// Human-readable names for internal pipeline components (never show raw codes like "fraud").
const FRIENDLY_COMPONENT: Record<string, string> = {
  intake: "Intake",
  classify: "Document classification",
  extract: "Document extraction",
  merge: "Data merge",
  eligibility: "Eligibility checks",
  fraud: "Fraud & anomaly screening",
  adjudication: "Adjudication",
  confidence: "Confidence scoring",
};
export const friendlyComponent = (name: string): string => FRIENDLY_COMPONENT[name] ?? titleCase(name);

// Plain-language labels for the processing steps shown in the timeline (no raw step codes).
const FRIENDLY_STEP: Record<string, string> = {
  intake: "Claim received",
  classify_doc: "Documents identified",
  "gate.presence": "Required documents present",
  "gate.readability": "Documents readable",
  "gate.patient_identity": "Patient identity match",
  extract_doc: "Details read from documents",
  merge_extractions: "Details combined",
  "eligibility.member": "Member eligibility",
  "eligibility.deadline": "Submission deadline",
  "eligibility.category": "Category covered",
  "eligibility.exclusion": "Exclusions checked",
  "eligibility.waiting_period": "Waiting period",
  "eligibility.pre_auth": "Pre-authorisation",
  "eligibility.policy": "Policy check",
  "fraud.scan": "Fraud & anomaly check",
  fraud: "Fraud & anomaly check",
  "adjudication.line_items": "Covered items assessed",
  "adjudication.copay": "Co-pay applied",
  adjudication: "Adjudication",
  finalize: "Decision finalised",
  // agent tool calls
  required_documents: "AI tool · required documents",
  member_profile: "AI tool · member profile",
  category_terms: "AI tool · category terms",
  fraud_thresholds: "AI tool · fraud thresholds",
};
export const friendlyStep = (step: string): string => FRIENDLY_STEP[step] ?? titleCase(step);

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
