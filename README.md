# Plum · Claims Intelligence

An automated **health-insurance claims adjudicator**. A member submits a claim with
documents; a **multi-agent LangGraph pipeline** verifies the documents, extracts the
details, applies the policy, and returns an `APPROVED / PARTIAL / REJECTED /
MANUAL_REVIEW` decision with an approved amount, reasons, a confidence score, and a
**complete, reconstructable trace** — degrading gracefully when a component fails.

> **Status:** backend 100% test coverage · `mypy --strict` clean · ruff clean ·
> **12/12** eval cases pass · frontend builds & dogfooded in-browser.

| | |
|---|---|
| **AI orchestration** | LangGraph 1.2 (multi-agent, two parallel `Send` fan-out stages) |
| **Backend** | FastAPI (async) + Pydantic v2, deterministic rule engine |
| **Frontend** | Next.js 16 (App Router) + Tailwind v4 + Motion, Plum-themed |
| **Observability** | Domain decision-trace + Langfuse (eval) + OpenTelemetry → Jaeger |
| **LLM** | Provider-abstracted: DeepSeek (text) now, Gemini (vision) when keyed |

---

## Auth

The UI is gated by **BetterAuth** (email + password, SQLite-backed). The login page has a
**Prefill admin** button that drops in the demo credentials (`admin@plum.local` /
`plumadmin123`); open sign-up is disabled. Auth lives at `/auth/*` (separate from the
`/api/*` backend proxy); a middleware redirects unauthenticated requests to `/login`.

## Demo scenarios — pipeline vs ground truth

Running a scenario shows **two things side by side**: our pipeline's live decision *and* the
scenario's **ground truth** (from `docs/test_cases.json`, served via `/scenarios`), with a
per-field match check. Nothing is hardcoded in the UI — the expectation comes from the
dataset, the result is computed by the pipeline on every run.

## The core idea

**A hard boundary between perception and decision.** LLMs only *perceive* — classify
and extract from messy documents. **Every rupee and every policy rule is computed in
deterministic Python read from `docs/policy_terms.json`.** Nothing about the policy is
hardcoded. This is what makes the system reproducible, testable, and trustworthy: the
12 eval cases pass with **zero LLM calls**, and the financial math can never hallucinate.

```
START → intake → (fan-out) classify_doc* → doc-verification gate
   ├── gate FAILED → format_blocker → END        (specific member message; no decision)
   └── gate PASSED → (fan-out) extract_doc* → merge → eligibility → fraud
                     → adjudicate → score+route → finalize → END
```

Each node is wrapped so a failure becomes *degraded state*, never a crash (TC011).

---

## Quickstart

### Option A — Docker (everything: app + Langfuse + OTel + Jaeger)
```bash
cp backend/.env.example backend/.env   # add DEEPSEEK_API_KEY (optional for eval)
docker compose -f infra/docker-compose.yml up --build
# Frontend  http://localhost:3001   API      http://localhost:8000/docs
# Langfuse  http://localhost:3766   Jaeger   http://localhost:16686
# Langfuse login: admin@plum.local / plumadmin123 (project keys auto-provisioned)
```

### Option B — Local dev
```bash
# backend
cd backend && uv sync && cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000

# frontend (new terminal)
cd frontend && npm install && npm run dev      # http://localhost:3000
```

The 12 eval scenarios are one click away in the UI (the `TC0xx` chips).

---

## Eval (the 12 test cases)

```bash
cd backend && uv run python -m eval.harness          # → 12/12 (deterministic), writes docs/EVAL_REPORT.md
uv run python -m eval.harness --langfuse               # also logs the run to Langfuse
uv run python -m eval.live_harness                     # 12/12 through the LIVE LLM path → EVAL_REPORT_LIVE.md
```
See [`docs/EVAL_REPORT.md`](docs/EVAL_REPORT.md) for every case's decision + full trace.

### LLM-as-judge over the upload folders

```bash
uv run python -m eval.make_upload_docs                 # writes ~/Downloads/upload_docs/<docN>/ (images + flow.txt + claim.json)
LANGFUSE_PUBLIC_KEY=… LANGFUSE_SECRET_KEY=… LANGFUSE_HOST=http://localhost:3766 \
  uv run python -m eval.judge_eval                     # live pipeline per folder, scored by an LLM judge → EVAL_REPORT_JUDGE.md
```
Each folder is run through the **live** pipeline (OCR → DeepSeek → adjudication); an **LLM judge**
(not hard-coded assertions) decides whether the output matches the folder's documented expectation,
and every case logs a Langfuse trace + `judge_match` score + a `plum-claims-judge` dataset item.

### Human review → eval dataset

Every decision in the UI carries a **review panel**: mark it correct (a golden example) or wrong
(pick the failing criteria + describe the right outcome). On submit, `POST /review` upserts a
`plum-claims-reviewed` Langfuse **dataset item** (input = the original claim, expected_output = the
verdict/correction) — the dataset you then run evals against. Open it at the Langfuse URL above.

---

## Tests, types, lint (the quality gate)

```bash
cd backend
uv run pytest                       # 100% statement + branch coverage (enforced)
uv run mypy app eval                # strict
uv run ruff check app eval tests    # lint
```

---

## Repository layout

```
backend/
  app/
    schemas/        canonical Pydantic contracts (single source of truth)
    policy/         PolicyRepository — loads policy_terms.json at runtime
    engine/         DETERMINISTIC rules: gate · eligibility · fraud · adjudication · confidence · invariants
    extraction/     Extractor protocol + EvalExtractor + LiveExtractor (DeepSeek/Gemini)
    llm/            shared DeepSeek JSON client (used by the live extractor + the judge)
    graph/          LangGraph state · nodes · build · runner (run + SSE stream)
    db/             SQLModel ClaimRepository (persisted claims, additive migration)
    api/            FastAPI routes (incl. POST /review → Langfuse dataset)
    observability/  logging · Langfuse tracing + datasets (human review) · OTel setup
  eval/             harness (deterministic) · live_harness (live LLM) · judge_eval (LLM-as-judge) · make_upload_docs
  tests/            168 tests (unit · node · integration · API · eval regression)
frontend/           Next.js App Router UI (submit · live pipeline · decision + trace · review panel · ops list)
infra/              docker-compose + otel-collector config
docs/               assignment + PLAN + ARCHITECTURE + CONTRACTS + EVAL_REPORT
```

---

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, data flow, trade-offs, 10× scaling.
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md) — every component's input / output / errors.
- [`docs/PLAN.md`](docs/PLAN.md) — the reconciled design + the 6 pinned decision-logic interpretations.
- [`docs/EVAL_REPORT.md`](docs/EVAL_REPORT.md) — generated eval results with full traces.

## Deployment (Render — both services, Docker)

The whole stack deploys from the [`render.yaml`](render.yaml) Blueprint as two Docker web services.

1. In the [Render dashboard](https://dashboard.render.com): **New → Blueprint**, pick this repo, **Apply**.
   It creates `mulp-claims-backend` and `mulp-claims-frontend`.
2. On the **backend** service, set the one secret: `DEEPSEEK_API_KEY` (the only required value).
3. Done. The frontend's `BACKEND_ORIGIN` is auto-wired from the backend service, and
   `BETTER_AUTH_SECRET` is auto-generated. Open the frontend URL → **Prefill admin** → Sign in.

Notes:
- Login works out of the box — the demo admin (`admin@plum.local` / `plumadmin123`) is migrated
  and seeded into the image at build time.
- The frontend proxies `/api/*` to the backend at **runtime** (`app/api/[...path]/route.ts`), so the
  backend stays off the public origin and no rebuild is needed when the URL changes.
- `free` plan = cold starts after idle; bump to `starter` for an always-on demo. Both Dockerfiles
  also run locally via [`infra/docker-compose.yml`](infra/docker-compose.yml).
- To showcase the agentic reviewer, set `ENABLE_AGENTIC_REVIEW=true` on the backend (adds ~15-25s/claim).
