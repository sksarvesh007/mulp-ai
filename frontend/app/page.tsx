"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getMembers,
  getScenarios,
  getUploadSamples,
  seedHistory,
  streamClaim,
  submitClaim,
  toFriendlyMessage,
  uploadClaimStream,
  wakeBackend,
} from "@/lib/api";
import type { ClaimResult, Member, Scenario, UploadSample } from "@/lib/types";
import { Card, CardHeader, Eyebrow, Pill } from "@/components/primitives";
import { Pipeline } from "@/components/Pipeline";
import { DecisionView } from "@/components/DecisionView";
import { DocumentPreview } from "@/components/DocumentPreview";
import { GroundTruth } from "@/components/GroundTruth";
import { HumanReview } from "@/components/HumanReview";

// Eval mode is deterministic - the whole graph runs server-side in ~75ms, so node events
// arrive in one burst. We replay them at this cadence so the pipeline is *visibly* processed
// before the decision + comparison appear (instead of everything popping at once).
const STEP_REVEAL_MS = 260;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// Group the demo scenarios by outcome so the user can pick one bucket at a time.
type ScenarioFilter = "approved" | "rejected" | "hitl";
const SCENARIO_FILTERS: { key: ScenarioFilter; label: string }[] = [
  { key: "approved", label: "Approved" },
  { key: "rejected", label: "Rejected" },
  { key: "hitl", label: "Human review" },
];
function bucketOf(s: Scenario): ScenarioFilter {
  const d = s.expected?.decision;
  if (d === "MANUAL_REVIEW") return "hitl"; // routes to human review → pauses under HITL
  if (d === "APPROVED" || d === "PARTIAL") return "approved"; // pays out (fully or partly)
  return "rejected"; // REJECTED + document-stop (null) cases
}

const CATEGORIES = [
  "CONSULTATION",
  "DIAGNOSTIC",
  "PHARMACY",
  "DENTAL",
  "VISION",
  "ALTERNATIVE_MEDICINE",
];

const DEFAULT_INPUT: Record<string, unknown> = {
  member_id: "EMP001",
  policy_id: "PLUM_GHI_2024",
  claim_category: "CONSULTATION",
  treatment_date: "2024-11-01",
  claimed_amount: 1500,
  hospital_name: "",
  documents: [],
  mode: "eval",
};

type Tab = "scenario" | "upload";

export default function Home() {
  const [members, setMembers] = useState<Member[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [samples, setSamples] = useState<UploadSample[]>([]);
  const [input, setInput] = useState<Record<string, unknown>>(DEFAULT_INPUT);
  const [loaded, setLoaded] = useState<Scenario | null>(null);
  const [loadedSample, setLoadedSample] = useState<UploadSample | null>(null);
  const [loadingSample, setLoadingSample] = useState(false);
  const [uploadFilter, setUploadFilter] = useState<ScenarioFilter>("approved");
  const [tab, setTab] = useState<Tab>("scenario");
  const [files, setFiles] = useState<File[]>([]);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [running, setRunning] = useState(false);
  const [waking, setWaking] = useState(false);
  const [hitl, setHitl] = useState(false);
  const [scenarioFilter, setScenarioFilter] = useState<ScenarioFilter>("approved");
  const [result, setResult] = useState<ClaimResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMembers().then(setMembers).catch(() => {});
    getScenarios().then(setScenarios).catch(() => {});
    getUploadSamples().then(setSamples).catch(() => {});
  }, []);

  const set = (k: string, v: unknown) => setInput((prev) => ({ ...prev, [k]: v }));

  // Switching the outcome filter clears any loaded case and turns HITL on only for the
  // human-review bucket, so running a shown case behaves as that bucket implies.
  const selectFilter = (f: ScenarioFilter) => {
    setScenarioFilter(f);
    setHitl(f === "hitl");
    setLoaded(null);
    setResult(null);
    setError(null);
    setDone(new Set());
  };

  const loadScenario = (s: Scenario) => {
    setLoaded(s);
    setResult(null);
    setDone(new Set());
    setError(null);
    setInput({ policy_id: "PLUM_GHI_2024", ...s.input, mode: "eval" });
  };

  // Upload-tab example: prefill the form, fetch the realistic document images into the picker,
  // and (for the same-day example) seed the prior claims so running it trips the velocity rule.
  const loadSample = useCallback(async (ex: UploadSample) => {
    setLoadedSample(ex);
    setResult(null);
    setDone(new Set());
    setError(null);
    setInput({ policy_id: "PLUM_GHI_2024", ...ex.form, mode: "live" });
    setLoadingSample(true);
    try {
      const fetched = await Promise.all(
        ex.files.map(async (url) => {
          const res = await fetch(url, { cache: "no-store" });
          const blob = await res.blob();
          const name = url.split("/").pop() ?? "document.png";
          return new File([blob], name, { type: blob.type || "image/png" });
        }),
      );
      setFiles(fetched);
      if (ex.seed) await seedHistory(ex.seed);
    } catch {
      setError("Couldn't load the example documents - please try again.");
    } finally {
      setLoadingSample(false);
    }
  }, []);

  // Deterministic eval path - streamed, then the advisory AI agent runs OFF the critical
  // path, exactly like the upload path (same pipeline + agentic node; pre-parsed documents
  // instead of OCR).
  const run = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setError(null);
    setDone(new Set());
    try {
      // Pre-warm a possibly-cold free-tier backend before the request so it doesn't race
      // a cold start. Best-effort - if it can't wake, the call still runs (and retries).
      setWaking(true);
      await wakeBackend();
      setWaking(false);
      if (hitl) {
        // HITL path: run non-streamed so a MANUAL_REVIEW outcome can PAUSE server-side and
        // come back as PENDING_REVIEW (the streaming endpoint always finalises). The review
        // panel then resumes it from the checkpoint.
        const final = await submitClaim({ ...input, mode: "eval", hitl: true });
        setResult(final);
        return;
      }
      // Eval nodes arrive in one burst, so PACE their reveal so the pipeline is *seen*
      // processing. The decision then shows (unblocked by the agent), and the advisory AI
      // assessment lands a few seconds later - identical to the upload flow.
      const seen = new Set<string>();
      let reveal = Promise.resolve();
      const final = await streamClaim({ ...input, mode: "eval" }, (e) => {
        if (e.type === "node" && !seen.has(e.node)) {
          seen.add(e.node);
          reveal = reveal.then(async () => {
            setDone((prev) => new Set(prev).add(e.node));
            await sleep(STEP_REVEAL_MS);
          });
        } else if (e.type === "result") {
          // Show the decision once the paced reveal has finished - not blocked on the agent.
          const r = e.result;
          reveal = reveal.then(() => setResult(r));
        } else if (e.type === "ai_assessment") {
          // The advisory AI assessment lands LATER → attach it so the AI card appears after.
          setResult((prev) =>
            prev ? { ...prev, decision: { ...prev.decision, ai_assessment: e.assessment } } : prev,
          );
        }
      });
      await reveal;
      // Reconcile with the fully-streamed result (AI assessment folded in by the reader);
      // also covers a buffering proxy that delivered no live events.
      if (final) setResult(final);
      else
        setError(
          "The pipeline didn't return a decision - the server may have timed out or restarted under load. Please try again.",
        );
    } catch (err) {
      setError(toFriendlyMessage(err));
    } finally {
      setWaking(false);
      setRunning(false);
    }
  }, [input, hitl]);

  // Live LLM path - uploads real documents (OCR + LLM extraction), STREAMED so the pipeline
  // animates from REAL node timing (no STEP_REVEAL_MS pacing - uploads are genuinely slow).
  const runLive = useCallback(async () => {
    setRunning(true);
    setResult(null);
    setError(null);
    setDone(new Set());
    try {
      // Pre-warm first so the heavy OCR/LLM upload hits a warm backend (avoids a failed
      // first attempt + re-sending the files). Best-effort; uploadClaimStream also retries.
      setWaking(true);
      await wakeBackend();
      setWaking(false);
      const final = await uploadClaimStream(
        {
          member_id: String(input.member_id ?? ""),
          policy_id: "PLUM_GHI_2024",
          claim_category: String(input.claim_category ?? ""),
          treatment_date: String(input.treatment_date ?? ""),
          claimed_amount: Number(input.claimed_amount ?? 0),
          hospital_name: String(input.hospital_name ?? ""),
        },
        files,
        (e) => {
          // Mark each completed step live so the pipeline checklist tracks real progress.
          if (e.type === "node") setDone((prev) => new Set(prev).add(e.node));
          // The decision arrives mid-stream → show it immediately (unblocked by the agent).
          else if (e.type === "result") setResult(e.result);
          // MANUAL_REVIEW → the upload paused for human review; show the review panel.
          else if (e.type === "pending_review") setResult(e.result);
          // The advisory AI assessment lands LATER → attach it so the AI card appears after.
          else if (e.type === "ai_assessment")
            setResult((prev) =>
              prev ? { ...prev, decision: { ...prev.decision, ai_assessment: e.assessment } } : prev,
            );
        },
      );
      // A delivered result/pending_review already rendered via onEvent (and `final` mirrors it).
      // If `final` is null the stream ended WITHOUT a decision - a node stalled or the server
      // restarted under load - so surface a clear, retryable error instead of silently dropping
      // back to the idle pipeline.
      if (final) setResult(final);
      else
        setError(
          "The document pipeline didn't return a decision - the server may have timed out or restarted under load (free-tier limits). Please try again.",
        );
    } catch (err) {
      setError(toFriendlyMessage(err));
    } finally {
      setWaking(false);
      setRunning(false);
    }
  }, [input, files]);

  const reset = useCallback(() => {
    setInput(DEFAULT_INPUT);
    setLoaded(null);
    setLoadedSample(null);
    setFiles([]);
    setResult(null);
    setDone(new Set());
    setError(null);
    setRunning(false);
    setHitl(false);
    setScenarioFilter("approved");
    setUploadFilter("approved");
  }, []);

  // "New claim" in the header fires this when already on the home route.
  useEffect(() => {
    const handler = () => reset();
    window.addEventListener("mulp:new-claim", handler);
    return () => window.removeEventListener("mulp:new-claim", handler);
  }, [reset]);

  const documents = (input.documents as Array<Record<string, unknown>>) ?? [];

  return (
    <div className="space-y-8">
      <section className="max-w-2xl">
        <Eyebrow>Claims adjudication</Eyebrow>
        <h1 className="mt-2 text-4xl leading-[1.05] text-ink">
          Submit a claim. Watch the agents decide - <span className="text-brand">explainably</span>.
        </h1>
        <p className="mt-3 text-sm leading-relaxed text-ink-muted">
          The system checks your documents, reads the details, applies your policy, and returns a
          clear decision with the reasons in plain language. Try one of the example cases, or upload
          your own documents.
        </p>
      </section>

      <div className="grid gap-6 lg:grid-cols-12">
        {/* ── form ── */}
        <div className="space-y-5 lg:col-span-5">
          {/* mode switch */}
          <div className="inline-flex rounded-lg border border-border p-0.5 text-sm">
            <button onClick={() => setTab("scenario")} className={tabBtn(tab === "scenario")}>
              Demo scenarios
            </button>
            <button onClick={() => setTab("upload")} className={tabBtn(tab === "upload")}>
              Upload documents
            </button>
          </div>

          {tab === "scenario" ? (
            <Card>
              <CardHeader title="Try a scenario" hint="pick an outcome" />
              {/* outcome filter - show only the cases that end in this outcome */}
              <div className="flex gap-1 px-4 pt-4">
                {SCENARIO_FILTERS.map((f) => {
                  const count = scenarios.filter((s) => bucketOf(s) === f.key).length;
                  const active = scenarioFilter === f.key;
                  return (
                    <button
                      key={f.key}
                      onClick={() => selectFilter(f.key)}
                      className={`pressable flex-1 rounded-md border px-2 py-1.5 text-xs ${
                        active
                          ? "border-brand/40 bg-brand/10 text-brand"
                          : "border-border text-ink-muted hover:border-border-strong hover:text-ink"
                      }`}
                    >
                      {f.label} <span className="opacity-60">{count}</span>
                    </button>
                  );
                })}
              </div>
              <div className="flex flex-wrap gap-1.5 px-4 py-4">
                {scenarios
                  .filter((s) => bucketOf(s) === scenarioFilter)
                  .map((s) => (
                    <button
                      key={s.case_id}
                      onClick={() => loadScenario(s)}
                      title={`${s.case_name} - ${s.description}`}
                      className={`pressable rounded-md border px-2.5 py-1 text-xs ${
                        loaded?.case_id === s.case_id
                          ? "border-brand/40 bg-brand/10 text-brand"
                          : "border-border text-ink-muted hover:border-border-strong hover:text-ink"
                      }`}
                    >
                      {s.case_id}
                    </button>
                  ))}
              </div>
              {scenarioFilter === "hitl" && (
                <p className="border-t border-border px-4 py-3 text-xs text-ink-faint">
                  These route to <span className="text-ink-muted">human review</span> - running one pauses
                  the pipeline for a person to approve/reject, then resumes from the saved state.
                </p>
              )}
              {loaded && (
                <p className="border-t border-border px-4 py-3 text-xs text-ink-faint">
                  <span className="text-ink-muted">{loaded.case_name}</span> - {loaded.description}
                </p>
              )}
            </Card>
          ) : (
            <Card>
              <CardHeader title="Realistic examples" hint="prefills documents + form" />
              {/* outcome filter - show the examples that end in this outcome */}
              <div className="flex gap-1 px-4 pt-4">
                {SCENARIO_FILTERS.map((f) => {
                  const count = samples.filter((s) => s.bucket === f.key).length;
                  const active = uploadFilter === f.key;
                  return (
                    <button
                      key={f.key}
                      onClick={() => setUploadFilter(f.key)}
                      className={`pressable flex-1 rounded-md border px-2 py-1.5 text-xs ${
                        active
                          ? "border-brand/40 bg-brand/10 text-brand"
                          : "border-border text-ink-muted hover:border-border-strong hover:text-ink"
                      }`}
                    >
                      {f.label} <span className="opacity-60">{count}</span>
                    </button>
                  );
                })}
              </div>
              {/* example cards - click to prefill the realistic documents + the claim form */}
              <div className="flex flex-col gap-1.5 px-4 py-4">
                {samples.length === 0 && <p className="text-xs text-ink-faint">Loading examples…</p>}
                {samples
                  .filter((s) => s.bucket === uploadFilter)
                  .map((s) => (
                    <button
                      key={s.id}
                      onClick={() => loadSample(s)}
                      disabled={loadingSample}
                      className={`pressable rounded-md border px-3 py-2 text-left disabled:opacity-60 ${
                        loadedSample?.id === s.id
                          ? "border-brand/40 bg-brand/10"
                          : "border-border hover:border-border-strong"
                      }`}
                    >
                      <span
                        className={`block text-sm font-medium ${
                          loadedSample?.id === s.id ? "text-brand" : "text-ink"
                        }`}
                      >
                        {s.label}
                      </span>
                      <span className="mt-0.5 block text-xs leading-relaxed text-ink-faint">
                        {s.description}
                      </span>
                    </button>
                  ))}
              </div>
              {/* or upload your own */}
              <div className="space-y-3 border-t border-border px-4 py-4">
                <p className="text-xs text-ink-faint">
                  {loadingSample ? "Loading the example documents…" : "…or upload your own documents:"}
                </p>
                <label className="pressable block cursor-pointer rounded-lg border border-dashed border-border-strong px-4 py-6 text-center hover:border-brand/50">
                  <input
                    type="file"
                    multiple
                    accept="image/*,application/pdf"
                    className="hidden"
                    onChange={(e) => {
                      setFiles(Array.from(e.target.files ?? []));
                      setLoadedSample(null);
                    }}
                  />
                  <span className="block text-sm text-ink-muted">
                    Drop prescription / bill images or PDFs, or click to choose
                  </span>
                  <span className="mt-1 block text-xs text-ink-faint">
                    Each document is read automatically by the AI
                  </span>
                </label>
                {files.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-xs text-ink-faint">
                      {files.length} document{files.length > 1 ? "s" : ""} - tap to preview
                    </p>
                    <DocumentPreview files={files} />
                  </div>
                )}
              </div>
            </Card>
          )}

          <Card>
            <CardHeader title="Claim details" />
            <div className="grid grid-cols-2 gap-4 px-4 py-4">
              <Field label="Member">
                <Select value={String(input.member_id ?? "")} onChange={(v) => set("member_id", v)}>
                  {members.map((m) => (
                    <option key={m.member_id} value={m.member_id}>
                      {m.member_id} · {m.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Category">
                <Select
                  value={String(input.claim_category ?? "")}
                  onChange={(v) => set("claim_category", v)}
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c.replace(/_/g, " ")}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Treatment date">
                <Input
                  type="date"
                  value={String(input.treatment_date ?? "")}
                  onChange={(v) => set("treatment_date", v)}
                />
              </Field>
              <Field label="Claimed amount (₹)">
                <Input
                  type="number"
                  value={String(input.claimed_amount ?? 0)}
                  onChange={(v) => set("claimed_amount", Number(v))}
                />
              </Field>
              <div className="col-span-2">
                <Field label="Hospital (optional)">
                  <Input
                    type="text"
                    placeholder="e.g. Apollo Hospitals"
                    value={String(input.hospital_name ?? "")}
                    onChange={(v) => set("hospital_name", v)}
                  />
                </Field>
              </div>
            </div>

            <div className="border-t border-border px-4 py-3">
              <Eyebrow>Documents</Eyebrow>
              {tab === "upload" ? (
                <p className="mt-1.5 text-xs text-ink-faint">
                  {files.length === 0
                    ? "No files chosen yet."
                    : `${files.length} file(s) will be read by the AI.`}
                </p>
              ) : documents.length === 0 ? (
                <p className="mt-1.5 text-xs text-ink-faint">
                  No documents attached - the gate will ask for the required ones.
                </p>
              ) : (
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {documents.map((doc, i) => (
                    <Pill key={i} tone={doc.quality === "UNREADABLE" ? "rejected" : "neutral"}>
                      {String(doc.actual_type ?? "UNKNOWN").replace(/_/g, " ").toLowerCase()}
                      {doc.quality === "UNREADABLE" ? " · unreadable" : ""}
                    </Pill>
                  ))}
                </ul>
              )}
            </div>

            <div className="border-t border-border px-4 py-4">
              {tab === "scenario" && hitl && (
                <p className="mb-3 rounded-md border border-brand/30 bg-brand/5 px-3 py-2 text-xs leading-relaxed text-ink-muted">
                  <span className="text-ink">Human-in-the-loop is on</span> - running this case pauses at
                  the review step; you decide, and it resumes from the saved state.
                </p>
              )}
              {tab === "upload" ? (
                <button
                  onClick={runLive}
                  disabled={running || files.length === 0}
                  className="pressable w-full rounded-md bg-brand py-2.5 text-sm font-medium text-cream hover:bg-brand-hover disabled:opacity-60"
                >
                  {waking ? "Waking the server…" : running ? "Reading documents with AI…" : "Run with AI"}
                </button>
              ) : (
                <button
                  onClick={run}
                  disabled={running}
                  className="pressable w-full rounded-md bg-brand py-2.5 text-sm font-medium text-cream hover:bg-brand-hover disabled:opacity-60"
                >
                  {waking ? "Waking the server…" : running ? "Processing…" : "Run claim"}
                </button>
              )}
              {error && (
                <p
                  role="alert"
                  className="mt-2 max-h-24 overflow-y-auto break-words rounded-md border border-rejected/30 bg-rejected/5 px-3 py-2 text-xs text-rejected"
                >
                  {error}
                </p>
              )}
            </div>
          </Card>
        </div>

        {/* ── results ── */}
        <div className="lg:col-span-7">
          {!result && (
            <Card className={running ? "" : "opacity-90"}>
              <CardHeader
                title="Pipeline"
                hint={
                  waking
                    ? "waking the server…"
                    : running
                      ? tab === "upload"
                        ? "AI extraction…"
                        : "running…"
                      : "idle"
                }
              />
              <div className="px-3 py-4">
                <Pipeline done={done} running={running} />
              </div>
            </Card>
          )}
          {result && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-ink-faint">
                  {result.decision.status === "PENDING_REVIEW" ? "Awaiting human review" : "Decision"}
                </span>
                <button
                  onClick={reset}
                  className="pressable rounded-md border border-border px-3 py-1.5 text-sm text-ink-muted hover:border-border-strong hover:text-ink"
                >
                  + New claim
                </button>
              </div>
              {result.decision.status === "PENDING_REVIEW" && result.review_request ? (
                <HumanReview
                  claimId={result.claim_id}
                  request={result.review_request}
                  onResolved={setResult}
                />
              ) : (
                <>
                  {tab === "scenario" && loaded?.expected && (
                    <GroundTruth expected={loaded.expected} result={result} caseId={loaded.case_id} />
                  )}
                  <DecisionView result={result} />
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function tabBtn(active: boolean): string {
  return `pressable rounded-md px-3 py-1.5 ${
    active ? "bg-brand/15 text-brand" : "text-ink-muted hover:text-ink"
  }`;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs text-ink-faint">{label}</span>
      {children}
    </label>
  );
}

function Input({
  type,
  value,
  onChange,
  placeholder,
}: {
  type: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-md border border-border bg-bg/60 px-3 py-2 text-sm text-ink outline-none transition focus:border-brand/50"
    />
  );
}

function Select({
  value,
  onChange,
  children,
}: {
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-md border border-border bg-bg/60 px-3 py-2 text-sm text-ink outline-none transition focus:border-brand/50"
    >
      {children}
    </select>
  );
}
