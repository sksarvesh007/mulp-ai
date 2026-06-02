// Mirrors the backend canonical schemas (app/schemas).

export type Decision = "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW";
export type ClaimStatus = "DECIDED" | "NEEDS_MEMBER_ACTION" | "PENDING_REVIEW";
export type ReviewAction = "APPROVED" | "REJECTED" | "PARTIAL";
export type TraceStatusValue = "pass" | "fail" | "skip" | "info";

export interface TraceEvent {
  step: string;
  status: TraceStatusValue;
  detail: string;
  policy_ref: string | null;
  data: Record<string, unknown>;
  ts: string | null;
}

export interface LineItemDecision {
  description: string;
  amount: number;
  status: "COVERED" | "EXCLUDED" | "REDUCED";
  approved_amount: number;
  reason: string | null;
}

export interface FinancialBreakdown {
  base: number;
  is_network: boolean;
  network_discount: number;
  after_discount: number;
  copay: number;
  after_copay: number;
  clamps: string[];
  final: number;
}

export interface FraudSignal {
  type: string;
  detail: string;
  data: Record<string, unknown>;
}

export interface ComponentFailure {
  component: string;
  error_type: string;
  impact: string;
  recoverable: boolean;
}

export interface ConfidenceDelta {
  reason: string;
  delta: number;
}

export interface ConfidenceBreakdown {
  base: number;
  deltas: ConfidenceDelta[];
  final: number;
}

export interface DocumentProblem {
  problem_type:
    | "DOCUMENT_PRESENCE"
    | "DOCUMENT_READABILITY"
    | "PATIENT_IDENTITY_MISMATCH"
    | "CLAIM_DOCUMENT_MISMATCH";
  message: string;
  file_ids: string[];
  required_action: string;
}

export interface ToolCall {
  name: string;
  arguments: string;
  output: string;
}

export interface AIAssessment {
  summary: string;
  concerns: string[];
  recommended_action: string;
  tools_used: string[];
  tool_calls: ToolCall[];
}

export interface ClaimDecision {
  decision: Decision | null;
  status: ClaimStatus;
  approved_amount: number | null;
  rejection_reasons: string[];
  line_items: LineItemDecision[];
  financial_breakdown: FinancialBreakdown | null;
  fraud_signals: FraudSignal[];
  eligible_from: string | null;
  confidence: number | null;
  confidence_breakdown: ConfidenceBreakdown | null;
  degraded: boolean;
  component_failures: ComponentFailure[];
  document_problem: DocumentProblem | null;
  reason: string | null;
  notes: string[];
  ai_assessment: AIAssessment | null;
}

export interface HumanReviewRequest {
  proposed_decision: string;
  reason: string;
  fraud_signals: FraudSignal[];
  claimed_amount: number;
  options: string[];
}

export interface HumanReviewVerdict {
  action: ReviewAction;
  approved_amount: number | null;
  reviewer: string;
  note: string;
}

export interface ClaimResult {
  claim_id: string;
  decision: ClaimDecision;
  trace: TraceEvent[];
  // present only when the claim paused at a human-in-the-loop checkpoint (PENDING_REVIEW)
  review_request: HumanReviewRequest | null;
}

export interface ClaimSummary {
  claim_id: string;
  member_id: string;
  category: string;
  decision: Decision | null;
  status: ClaimStatus;
  approved_amount: number | null;
  confidence: number | null;
  degraded: boolean;
  created_at: string;
}

export interface Member {
  member_id: string;
  name: string;
  relationship: string | null;
}

export interface ReviewResponse {
  saved: boolean;
  dataset: string;
  item_id?: string;
  host?: string;
  reason?: string;
}

export interface ScenarioExpected {
  decision: Decision | null;
  approved_amount?: number;
  rejection_reasons?: string[];
  notes?: string;
  confidence_score?: string;
  system_must?: string[];
}

export interface Scenario {
  case_id: string;
  case_name: string;
  description: string;
  input: Record<string, unknown>;
  expected: ScenarioExpected;
}

// A one-click upload example: realistic documents + the matching claim-form values, grouped
// by outcome. Selecting it prefills the form and fetches the document images into the picker.
export interface UploadSample {
  id: string;
  bucket: "approved" | "rejected" | "hitl";
  label: string;
  description: string;
  tc?: string; // the documented test case this example mirrors (e.g. "TC004"), if any
  form: {
    member_id: string;
    claim_category: string;
    treatment_date: string;
    claimed_amount: number;
    hospital_name: string;
  };
  files: string[];
  seed?: { member_id: string; treatment_date: string; count: number };
}

export type StreamEvent =
  | { type: "progress"; event: string; node?: string; error?: string; file_id?: string }
  | { type: "node"; node: string }
  | { type: "result"; result: ClaimResult }
  // a HITL pause: the claim routed to MANUAL_REVIEW and is awaiting a human verdict
  | { type: "pending_review"; result: ClaimResult }
  // The advisory AI agent runs OFF the critical path, so its assessment arrives AFTER the
  // result as a late event - present for any streamed claim (demo or upload) when enabled.
  | { type: "ai_assessment"; assessment: AIAssessment }
  // the server hit an error mid-stream; the client surfaces a retryable message (no result)
  | { type: "error" }
  | { type: "done" };
