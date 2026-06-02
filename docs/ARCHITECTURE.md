# Architecture — Plum Claims Processing

## 1. Problem & approach

Automate the manual review of health-insurance claims: accept a claim + documents,
catch document problems early, extract structured data, adjudicate against the policy,
and return an explainable `APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW` decision that
degrades gracefully under failure.

The governing design decision is a **hard perception/decision boundary**:

- **LLMs perceive only** — classify documents and extract fields from messy images.
- **Deterministic Python decides** — every policy rule and every rupee is computed in
  tested code that reads `policy_terms.json` at runtime. No policy value is hardcoded.

Consequences: the eval is reproducible (12/12 with zero LLM calls), the financial math
is unit-testable to the rupee and can never hallucinate, and the traces are trustworthy.

## 2. Component architecture

```
┌─────────────┐     ┌──────────────────────── Backend (FastAPI + LangGraph) ───────────────────────┐
│  Next.js UI │ ──► │  api/routes  ──►  graph/runner  ──►  LangGraph graph (graph/build, nodes)      │
│  (submit,   │ SSE │      │                                   │                                      │
│  live trace,│ ◄── │      │            ┌──────────────────────┴───────────────────────────────┐    │
│  decision)  │     │      │            │ PERCEPTION (LLM)            DECISION (deterministic)   │    │
└─────────────┘     │      │            │  extraction/                engine/                    │    │
                    │      │            │   EvalExtractor              gate · eligibility ·       │    │
                    │      ▼            │   LiveExtractor (DeepSeek/   fraud · adjudication ·     │    │
                    │   api/store      │   Gemini, behind Protocol)   confidence · decide        │    │
                    │  (in-memory)     │            │                          │                  │    │
                    │                  │            └────────► policy/PolicyRepository ◄──────────┘    │
                    │                  │                         (reads docs/policy_terms.json)        │
                    │   observability/ (domain trace · Langfuse · OpenTelemetry)                         │
                    └───────────────────────────────────────────────────────────────────────────────┘
```

- **`schemas/`** — the canonical Pydantic v2 data contracts every layer imports (one
  source of truth: money is integer rupees; a blocked claim is `decision=None` +
  `status=NEEDS_MEMBER_ACTION`).
- **`policy/PolicyRepository`** — loads and queries the policy JSON; the *only* place
  policy values enter the system.
- **`engine/`** — pure, deterministic rule functions. Each returns a structured result
  plus a list of `TraceEvent`s describing what it checked and why.
- **`extraction/`** — an `Extractor` Protocol with two interchangeable backends, so every
  downstream node is identical in eval and live mode.
- **`graph/`** — LangGraph wiring: typed state, nodes (thin wrappers over the engine), the
  compiled graph, and the runner (`run_claim` for request/response, `stream_claim` for SSE).
- **`api/`** — FastAPI surface + a small claim store.
- **`observability/`** — the three observability layers (§6).

## 3. The multi-agent graph

```
START → intake → (Send fan-out) classify_doc × N → collect → doc-verification gate
   gate FAILED → format_blocker ─────────────────────────────────► finalize → END
   gate PASSED → (Send fan-out) extract_doc × N → merge_extractions
              → eligibility → fraud → adjudicate → score_route → finalize → END
```

- Two **`Send` fan-out/fan-in stages** (classify, then extract) process documents in
  parallel; concurrent writes merge through `operator.add`-reduced state keys.
- The **gate short-circuit** is a structural guarantee that no claim with a document
  problem ever reaches the financial engine.
- **LLM nodes:** `classify_doc`, `extract_doc` (and name-normalization inside the gate).
  **Everything else is deterministic.**

## 4. Decision precedence (derived from the 12 cases)

A strictly ordered ladder; the first failing gate terminates:

1. **Intake** — validate, normalize (never short-circuits; may degrade).
2. **Document gate** — presence → readability → patient-identity. Failure ⇒ `decision=None`
   + a *specific* member message (TC001/002/003).
3. **Member / policy validity**, then **submission compliance** (deadline, min amount).
4. **Eligibility hard-rejects** — category cover, **exclusion (before waiting)**, waiting
   period, pre-authorization. These beat financial limits (TC005/007/012).
5. **Fraud / anomaly** ⇒ `MANUAL_REVIEW` (never auto-reject) (TC009).
6. **Financial** — line-item classification (⇒ PARTIAL), per-claim limit (⇒ full REJECT),
   network-discount-**then**-co-pay, sub-limit / annual-OPD caps (TC004/006/008/010).
7. **Confidence** — one deterministic, itemized model.

Six interpretations are pinned in [`PLAN.md`](PLAN.md) §4.1 (e.g. OPD `sub_limit` is an
annual aggregate, not a per-claim cap; exclusion beats waiting for obesity). Without them
TC006 and TC008 cannot both pass.

## 5. Failure handling & graceful degradation

Every node is wrapped by `@resilient_node`: an exception is captured as a
`ComponentFailure`, sets `degraded=True`, appends a fail `TraceEvent`, and returns a valid
partial-state delta so the graph continues. Degradation lowers confidence and adds a
"manual review recommended" note; it only forces `MANUAL_REVIEW` when a *financially
relevant* component fails — so TC011 (its fraud component fails) still ends `APPROVED` with
reduced confidence. `simulate_component_failure` is a first-class state knob.

## 6. Observability — three layers

1. **Domain decision-trace** *(primary; the 20%-weighted requirement).* Every node records
   a `TraceEvent` — what it checked, the `policy_ref` it dereferenced, pass/fail/skip, the
   numbers, the resulting change. An ops person reconstructs any decision from this alone,
   with zero code reading. It is rendered as a timeline in the UI and returned by
   `GET /claims/{id}/trace`.
2. **Langfuse** — the 12-case eval logged as a run (accuracy, per-case pass/fail, confidence,
   the report artifact); an optional `@observe` exporter captures LLM calls in live mode.
3. **OpenTelemetry** — FastAPI auto-instrumentation + (optional) per-node spans → OTLP
   collector → Jaeger, for latency/distributed debugging.

The domain trace is the source of truth for *why*; Langfuse/OTel are engineering telemetry.

## 7. Testing strategy

134 tests, **100% statement + branch coverage** (enforced via `--cov-fail-under=100`):

- **Unit** — each rule in isolation, including the network-discount-then-co-pay *order*
  proof (co-pay is 10% of ₹3,600 = ₹360, not of ₹4,500) and the late-submission rule that
  the 12 cases don't exercise.
- **Node** — engine wrappers with the live path mocked.
- **Integration** — the full graph via `ainvoke`, asserting TC011 → APPROVED + degraded +
  confidence < clean + manual-review note.
- **Eval regression** — all 12 `test_cases.json` through the graph (the CI gate).
- **API** — every route via FastAPI `TestClient`, including the SSE stream.

## 8. Trade-offs considered & rejected

- **LLM-driven adjudication → rejected.** Letting the model decide amounts is
  unreproducible and unauditable. Determinism is the whole point.
- **One monolithic node → rejected** in favour of a multi-agent graph: cleaner
  responsibilities, the multi-agent bonus, and parallel per-document work.
- **Pydantic models on graph state → avoided** in favour of `TypedDict` + reducers, which
  serialize cleanly through checkpointers and make concurrent fan-in writes safe.
- **Real OCR for the eval → rejected.** Test cases ship structured `content`; trusting it in
  eval mode keeps the 12 cases deterministic while the same nodes run real extraction live.
- **DeepSeek for vision → not possible** (text-only); kept behind the `Extractor` Protocol
  so Gemini (multimodal) drops in with a key, with Tesseract→DeepSeek as a stopgap.

## 9. Limitations & scaling to 10×

- **State store is in-memory.** At scale: Postgres (claims + decisions) and a LangGraph
  `PostgresSaver` checkpointer (already abstracted) for crash recovery and HITL on
  `MANUAL_REVIEW` via `interrupt()`.
- **Synchronous request path.** Extraction (vision) is the slow, bursty step. At 10× move
  to a queue (the fan-out already isolates per-document work): API enqueues → workers run
  the graph → results pushed over SSE/websocket. Vercel Queues / Celery / Arq all fit.
- **Single LLM provider, no batching.** Add the AI-gateway pattern (provider fallback, rate
  limiting, caching of identical documents by hash) and batch vision calls.
- **Policy is a single JSON.** Multi-policy / multi-tenant: load policies by `policy_id`
  from a versioned store; the `PolicyRepository` interface already isolates this.
- **Fraud is rule + heuristic.** At scale, add a learned anomaly model behind the same
  `FraudResult` contract; the decision router is unaffected.
- **Confidence constants are hand-tuned.** With labelled outcomes they can be calibrated;
  the itemized breakdown keeps it explainable either way.
