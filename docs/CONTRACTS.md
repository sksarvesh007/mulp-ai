# Component Contracts

Every significant component's **input · output · errors**, precise enough to reimplement
without reading the code. All types live in `backend/app/schemas` (the single source of
truth). **Money is integer rupees throughout.**

## Shared data models (`app/schemas`)

```python
ClaimInput(claim_id?, member_id, policy_id, claim_category: ClaimCategory,
           treatment_date: str, claimed_amount: int, hospital_name?, ytd_claims_amount=0,
           submission_date?, pre_auth_reference?, claims_history: [ClaimHistoryItem],
           documents: [DocumentInput], mode: "eval"|"live", simulate_component_failure=False)
DocumentInput(file_id, file_name?, actual_type?: DocumentType, quality?: DocumentQuality,
              patient_name_on_doc?, content?: dict, image_ref?)
ExtractedDocument(file_id, doc_type, quality, patient_name?, doctor_name?, diagnosis?,
                  treatment?, hospital_name?, medicines[], tests_ordered[], line_items[LineItem],
                  total?, confidence: float, low_confidence_fields[], notes[], ok: bool, source)
ClaimDecision(decision: Decision|None, status: ClaimStatus, approved_amount: int|None,
              rejection_reasons[str], line_items[LineItemDecision], financial_breakdown?,
              fraud_signals[FraudSignal], eligible_from?, confidence?: float,
              confidence_breakdown?, degraded: bool, component_failures[], document_problem?,
              reason?, notes[])
TraceEvent(step, status: pass|fail|skip|info, detail, policy_ref?, data: dict, ts)
ClaimResult(claim_id, decision: ClaimDecision, trace: [TraceEvent])
```

---

## PolicyRepository — `app/policy/repository.py`
- **Purpose:** load + query `policy_terms.json`; the only ingress for policy values.
- **In:** `from_file(path?) ` (defaults to `settings.policy_file`).
- **Out:** typed accessors — `per_claim_limit`, `annual_opd_limit`, `category(name)`,
  `specific_waiting_conditions`, `excluded_conditions`, `document_requirements(cat)`,
  `is_network_hospital(name)`, `member(id)`, `covered_names_for(id)`, `fraud_thresholds`, …
- **Errors:** `PolicyNotFoundError` (missing file), `PolicyError` (malformed JSON / missing
  top-level keys / unknown category or category-without-requirements).

## Extractor (Protocol) — `app/extraction/base.py`
- **Purpose:** perception layer; swappable backend selected by `mode`.
- **In:** `classify(DocumentInput)`, `extract(DocumentInput)` (both async).
- **Out:** `ExtractedDocument` (classify populates type/quality/patient; extract fills fields).
- **Errors:** never raises for bad content — returns `ok=False` / low confidence so the
  pipeline degrades. `EvalExtractor` trusts provided `content`; `LiveExtractor` uses
  DeepSeek (text+OCR) or Gemini (vision), falling back to `content` when present.

## DocumentVerificationGate — `app/engine/gate.py::verify_documents`
- **In:** `(ClaimInput, [ExtractedDocument] (classified), PolicyRepository)`.
- **Out:** `GateResult(passed: bool, problem: DocumentProblem|None, trace)`.
- **Logic:** 1a presence (required types present) → 1b readability (required doc not
  `UNREADABLE`) → 1c patient identity (same surname across docs; matches member/dependents).
  First failure wins; message is specific (names uploaded vs required type / the unreadable
  file / both patient names).
- **Errors:** none raised (deterministic); `PolicyError` propagates if requirements missing.

## EligibilityEvaluator — `app/engine/eligibility.py::evaluate_eligibility`
- **In:** `(ClaimInput, ClaimView, PolicyRepository)`.
- **Out:** `EligibilityResult(hard_reject, reasons[RejectionReason], eligible_from?, headline?,
  category_covered, member_valid, trace)`.
- **Logic order:** member/policy validity → submission (deadline, min amount) → category
  covered → **exclusion → waiting → pre-auth**. First hard-reject terminates.
- **Errors:** none raised.

## FraudDetector — `app/engine/fraud.py::evaluate_fraud`
- **In:** `(ClaimInput, PolicyRepository, alteration_flags?)`.
- **Out:** `FraudResult(manual_review: bool, signals[FraudSignal], score: float, trace)`.
- **Logic:** same-day & monthly velocity, high-value auto-review, document-alteration; any
  signal ⇒ `manual_review=True`. **Never rejects.**

## AdjudicationEngine — `app/engine/adjudication.py::adjudicate`
- **In:** `(ClaimInput, ClaimView, PolicyRepository, EligibilityResult, FraudResult)`.
- **Out:** `AdjudicationResult(skipped, approved_amount: int, has_excluded, per_claim_exceeded,
  line_items[LineItemDecision], breakdown: FinancialBreakdown?, trace)`.
- **Logic:** short-circuits if eligibility hard-reject or fraud manual-review. Else: line-item
  classification (dental/vision) → per-claim limit (OPD ⇒ full reject) → **network discount
  then co-pay** → sub-limit (dental/vision/alt-med) + annual-OPD caps.
- **Errors:** none raised; `PolicyError` if category missing.

## ConfidenceScorer — `app/engine/confidence.py::compute_confidence`
- **In:** `([ExtractedDocument], manual_review, clarity_bonus, num_failures)`.
- **Out:** `ConfidenceBreakdown(base=0.95, deltas[ConfidenceDelta], final)` — clamped [0, 0.99],
  every contribution itemized.

## DecisionRouter — `app/engine/decide.py::route_decision`
- **In:** `(eligibility, fraud, adjudication, extracted, degraded, failures)`.
- **Out:** `ClaimDecision`. Precedence: hard-reject → manual-review (fraud or financial
  degradation) → per-claim reject → nothing-payable → partial → approved.

## Orchestrator — `app/graph` (`run_claim`, `stream_claim`)
- **In:** `ClaimInput`. **Out:** `ClaimResult` (`stream_claim` yields progress events then a
  `result` event). **Errors:** never raises to the caller — node failures become degraded
  state via `@resilient_node`.

---

## FastAPI surface — `app/api/routes.py`

| Method | Path | Request | Response | Codes |
|---|---|---|---|---|
| GET | `/healthz` | — | `{status:"ok"}` | 200 |
| GET | `/members` | — | `[{member_id,name,relationship}]` | 200 |
| GET | `/scenarios` | — | `[{case_id,case_name,description,input,expected}]` (12 cases; `expected` = ground truth) | 200 |
| POST | `/claims` | `ClaimInput` | `ClaimResult` | 200 / 422 |
| GET | `/claims` | — | `[ClaimSummary]` | 200 |
| GET | `/claims/{id}` | — | `ClaimResult` | 200 / 404 |
| GET | `/claims/{id}/trace` | — | `{claim_id, trace:[TraceEvent]}` | 200 / 404 |
| POST | `/claims/stream` | `ClaimInput` | `text/event-stream` (`progress`/`node`/`result`/`done`) | 200 |
| POST | `/claims/upload` | multipart (fields + files) | `ClaimResult` (live mode) | 200 / 422 |
| POST | `/eval` | — | `{passed,total,cases[]}` | 200 |
| POST | `/review` | `ReviewRequest` `{claim_id,is_correct,criteria[],expected_notes}` | `{saved,dataset,item_id?,host?,reason?}` | 200 / 404 |
