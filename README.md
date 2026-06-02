# Mulp · Claims Intelligence

An automated health-insurance claims adjudicator. A member submits a claim with documents; a
multi-agent LangGraph pipeline verifies the documents, extracts the details, applies the policy,
and returns an `APPROVED` / `PARTIAL` / `REJECTED` / `MANUAL_REVIEW` decision with an approved
amount, the reasons, a confidence score, and a complete, reconstructable trace. Individual
components degrade gracefully instead of crashing the request.

> Status: 210 tests, `mypy --strict` clean, ruff clean, 12/12 eval cases pass, frontend builds and
> is dogfooded in-browser. Deployed on Render (backend + frontend) with a Supabase claims ledger
> and Langfuse tracing.

| Layer | Stack |
|---|---|
| AI orchestration | LangGraph 1.2 (multi-agent graph, parallel `Send` fan-out for classify + extract, checkpointed HITL) |
| Backend | FastAPI (async) + Pydantic v2, deterministic rule engine |
| Frontend | Next.js 16 (App Router) + Tailwind v4, BetterAuth |
| Perception | Tesseract OCR + DeepSeek (text) for live extraction; deterministic fixtures for eval |
| Advisory agent | OpenAI Agents SDK on DeepSeek (explains the decision; off the critical path) |
| Persistence | Supabase (claims ledger for cross-submission fraud velocity) + SQLite (ops history) |
| Observability | Domain decision-trace + Langfuse (generations, agent tool calls, eval datasets) |

---

## The core idea: perception vs decision

A hard boundary between perception and decision. LLMs only perceive: they classify and extract
fields from messy documents (handwriting, rubber stamps, phone photos). Every rupee and every
policy rule is computed in deterministic Python read from `docs/policy_terms.json`; nothing about
the policy is hardcoded. The 12 eval cases pass with zero LLM calls, and the financial math can
never hallucinate.

## The pipeline

```
START -> intake -> (fan-out) classify_doc* -> document-verification gate
   |  gate failed   -> format_blocker -> finalize -> END   (specific member message, no decision)
   |  gate passed   -> (fan-out) extract_doc* -> merge -> consistency
                        |  claim/document mismatch -> format_blocker -> finalize -> END
                        |  consistent              -> eligibility -> fraud -> adjudicate
                                                      -> score + route -> human_review -> finalize -> END
```

Every node is wrapped so a failure becomes degraded state, never a crash. `human_review` pauses the
graph at a saved checkpoint when a claim routes to MANUAL_REVIEW, then resumes from a reviewer's
verdict.

### What each stage does

- Document gate: required documents per category, readability, and patient identity. The patient
  check tells a "wrong member selected" case (the document belongs to a different covered member)
  apart from an "uncovered patient" case, and a claim-vs-document consistency check confirms the
  amount, date, and hospital you entered match what the documents actually say.
- Eligibility: member/policy validity, coverage window, submission deadline and minimum amount,
  category coverage, exclusions, condition waiting periods, and high-value pre-authorization.
- Fraud / velocity: same-day and monthly claim limits (computed across real submissions via the
  Supabase ledger), a high-value auto-review threshold, and a weighted fraud score. Signals route
  to MANUAL_REVIEW, never an auto-reject.
- Adjudication: per-category sub-limits, co-pay, network-hospital discount, per-claim and annual-OPD
  caps, and line-item covered/excluded classification (so a dental claim pays the covered treatment
  and drops the cosmetic line).
- Confidence and invariants: a transparent, itemized confidence score plus hard invariants (never
  approve more than was claimed, and so on).

## Advisory AI reviewer

An optional reviewer (OpenAI Agents SDK on DeepSeek, with policy-lookup tools) runs off the critical
path after the decision has been made. It does not re-decide: it is handed the deterministic
decision and explains it in plain language, then tells the member what to do next. Its generations
and tool calls are captured in Langfuse. Toggle with `ENABLE_AGENTIC_REVIEW`.

## Human-in-the-loop (HITL)

A MANUAL_REVIEW claim pauses at a checkpoint and surfaces a review panel (approve / reject /
partial). Submitting a verdict resumes the graph from that exact saved state and finalizes the
decision. This works both for the demo scenarios and for live document uploads.

## Demo scenarios and document upload

- Demo scenarios: the 12 `test_cases.json` cases as one-click chips, grouped by outcome
  (Approved / Rejected / Human review). Each run shows the pipeline's live decision next to the
  case's ground truth with a per-field match check; nothing is hardcoded in the UI.
- Upload documents: a gallery of realistic sample documents (generated hospital bills,
  prescriptions, and lab reports with letterhead, itemized tables, and a paid stamp), also grouped
  by outcome. Selecting one prefills the claim form and loads the document images; "Run with AI"
  then drives the real OCR -> DeepSeek -> engine path. You can also upload your own files.

## Resilience

- SSE heartbeats keep a streaming upload alive through long OCR/LLM gaps, so a slow node is not cut
  by a proxy idle-timeout mid-pipeline.
- Bounded LLM timeouts, so a stuck model call fails fast and degrades into a clean decision instead
  of hanging the request.
- Cold-start wake-and-retry on the initial data load (the free-tier backend spins down when idle).
- Per-node graceful degradation: a failed component is recorded, confidence drops, and the claim is
  flagged for review rather than crashing.

## Auth

The UI is gated by BetterAuth (email + password, SQLite-backed). The login page prefills the demo
credentials (`admin@mulp.local` / `mulpadmin123`); open sign-up is disabled. The admin is migrated
and seeded into the image at build time, so login works out of the box.

---

## Quickstart

### Local dev

```bash
# backend
cd backend && uv sync && cp .env.example .env   # add DEEPSEEK_API_KEY for the live LLM path
uv run uvicorn app.main:app --reload --port 8000

# frontend (new terminal)
cd frontend && npm install && npm run dev        # http://localhost:3000
```

The 12 eval scenarios are one click away in the UI; the upload tab ships with realistic sample
documents you can run with one click.

### Docker (app + Langfuse + OTel + Jaeger)

```bash
cp backend/.env.example backend/.env
docker compose -f infra/docker-compose.yml up --build
# Frontend http://localhost:3001   API http://localhost:8000/docs   Langfuse http://localhost:3766
```

## Eval

```bash
cd backend
uv run python -m eval.harness         # 12/12 deterministic, writes docs/EVAL_REPORT.md
uv run python -m eval.live_harness    # 12/12 through the live OCR + DeepSeek path
uv run python -m eval.agent_eval      # live engine decision + advisory-agent answer per case
uv run python -m eval.sample_gallery  # regenerate the realistic upload-tab sample documents
```

See [`docs/EVAL_REPORT.md`](docs/EVAL_REPORT.md) for every case's decision and full trace.

## Tests, types, lint

```bash
cd backend
uv run pytest                      # unit + node + integration + API + eval regression
uv run mypy app eval               # strict
uv run ruff check app eval tests   # lint
```

## Supabase claims ledger (fraud velocity)

Each live submission is recorded to Supabase, and a member's prior claims are loaded before the
graph runs so the same-day and monthly velocity rules apply across real submissions (not only when
a history is supplied on the input). It is best-effort: if Supabase is not configured the claim
still processes, just without cross-submission velocity. Set `SUPABASE_URL` and `SUPABASE_KEY` on
the backend and create the `claims` table once:

```sql
create table if not exists public.claims (
  claim_id        text primary key,
  member_id       text not null,
  policy_id       text,
  claim_category  text,
  treatment_date  date,
  claimed_amount  integer,
  decision        text,
  status          text,
  approved_amount integer,
  created_at      timestamptz not null default now()
);
create index if not exists claims_member_treatment_idx on public.claims (member_id, treatment_date);
alter table public.claims enable row level security;
create policy "claims read"  on public.claims for select using (true);
create policy "claims write" on public.claims for insert with check (true);
```

---

## Repository layout

```
backend/
  app/
    schemas/        Pydantic contracts (single source of truth)
    policy/         PolicyRepository - loads policy_terms.json at runtime
    engine/         deterministic rules: gate (incl. claim/document consistency), eligibility,
                    fraud, adjudication, confidence, invariants
    extraction/     Extractor protocol + EvalExtractor + LiveExtractor (Tesseract + DeepSeek)
    agentic/        advisory OpenAI-Agents-SDK reviewer (explains the decision)
    llm/            shared DeepSeek JSON client
    graph/          LangGraph state, nodes, build, runner (run + SSE stream + checkpointed HITL)
    db/             ClaimRepository (SQLite ops history) + ledger (Supabase fraud velocity)
    api/            FastAPI routes (SSE upload/stream, HITL resume, review, sample seed)
    observability/  Langfuse tracing + datasets + OTel setup
  eval/             harness, live_harness, agent_eval, judge_eval, sample_gallery
  tests/            test suite (unit, node, integration, API, eval regression)
frontend/           Next.js App Router UI (demo scenarios, upload gallery, decision + trace, review)
infra/              docker-compose + otel-collector config
docs/               assignment, PLAN, ARCHITECTURE, CONTRACTS, EVAL_REPORT, policy_terms, test_cases
```

---

## Deployment (Render, two Docker services)

The stack deploys from the [`render.yaml`](render.yaml) Blueprint as `mulp-claims-backend` and
`mulp-claims-frontend`.

1. In the Render dashboard: New -> Blueprint, pick this repo, Apply.
2. On the backend service, set `DEEPSEEK_API_KEY` (the live LLM path). For the fraud-velocity
   ledger, also set `SUPABASE_URL` and `SUPABASE_KEY` and create the `claims` table (SQL above).
   Optionally set `ENABLE_AGENTIC_REVIEW=true` to show the advisory reviewer.
3. The frontend proxies `/api/*` to the backend at runtime (`app/api/[...path]/route.ts`), so the
   backend URL is auto-wired and `BETTER_AUTH_SECRET` is auto-generated.

Notes:

- The free plan spins down when idle (cold starts); the UI wakes the backend before heavy requests
  and retries the initial data load. Bump to a paid plan for an always-on demo.
- Login works out of the box: the demo admin (`admin@mulp.local` / `mulpadmin123`) is seeded into
  the image at build time.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - components, data flow, trade-offs, scaling.
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) - each component's input / output / errors.
- [`docs/PLAN.md`](docs/PLAN.md) - the reconciled design and the pinned decision-logic interpretations.
- [`docs/EVAL_REPORT.md`](docs/EVAL_REPORT.md) - generated eval results with full traces.
