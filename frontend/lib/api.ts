import type {
  Analytics,
  ClaimResult,
  ClaimSummary,
  HumanReviewVerdict,
  Member,
  ReviewResponse,
  Scenario,
  StreamEvent,
  UploadSample,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// A short, human sentence for the status codes a user can actually hit here. Anything
// else falls back to a generic line - we never echo an upstream body into the UI.
const STATUS_MESSAGE: Record<number, string> = {
  413: "Those files are too large - try smaller scans (a few MB each).",
  502: "The server is temporarily unavailable - it may be waking up. Give it a moment and try again.",
  503: "The server is temporarily unavailable - it may be waking up. Give it a moment and try again.",
  504: "The request timed out. The live document pipeline can be slow on a first run - please try again.",
};

// Turn a failed Response into a short Error. Prefer the backend's JSON `detail`; never
// surface a raw body (e.g. a gateway's full HTML 502 page - the wall of markup users saw).
async function errorFromResponse(res: Response): Promise<Error> {
  let detail = "";
  const ctype = res.headers.get("content-type") ?? "";
  try {
    if (ctype.includes("application/json")) {
      const body = (await res.json()) as { detail?: unknown };
      const d = body?.detail;
      detail = typeof d === "string" ? d : d != null ? JSON.stringify(d) : "";
    } else {
      const text = (await res.text()).trim();
      // Only plain-text bodies are safe to show - skip anything that looks like HTML.
      if (text && !text.startsWith("<")) detail = text;
    }
  } catch {
    /* body unreadable - fall through to a status-based message */
  }
  const fallback =
    STATUS_MESSAGE[res.status] ??
    (res.status >= 500
      ? "The server hit an unexpected error. Please try again."
      : `Request failed (${res.status}).`);
  // Cap length so even an unexpected plain-text body can't flood the UI.
  return new Error((detail || fallback).slice(0, 220));
}

/** Map any thrown value (incl. network/abort failures) to a short, user-facing string. */
export function toFriendlyMessage(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === "AbortError") return "The request was cancelled.";
    if (/failed to fetch|networkerror|load failed|fetch failed/i.test(err.message))
      return "Couldn’t reach the server. Check your connection and try again.";
    return err.message.slice(0, 220);
  }
  return String(err).slice(0, 220);
}

// Transient connectivity failures worth a wake-and-retry - NOT 4xx validation errors.
// Matches the messages errorFromResponse() produces for 502/503/504 plus raw fetch failures.
function isTransient(err: unknown): boolean {
  const m = err instanceof Error ? err.message.toLowerCase() : "";
  return /unavailable|timed out|timeout|abort|failed to fetch|fetch failed|network|load failed/.test(m);
}

/**
 * Wake a possibly-cold free-tier backend with a cheap GET /healthz, retrying with
 * backoff until it returns 200 (or we hit `maxWaitMs`). Render's edge holds a request
 * during spin-up rather than 502-ing it, so this reliably warms the instance BEFORE the
 * heavy OCR/LLM request - turning a first-request cold-start failure into a short wait.
 * Never throws; resolves true if the backend answered 200, false otherwise.
 */
export async function wakeBackend(maxWaitMs = 75_000): Promise<boolean> {
  const deadline = Date.now() + maxWaitMs;
  let delay = 500;
  while (Date.now() < deadline) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 20_000);
    try {
      const res = await fetch(`${API_URL}/healthz`, { cache: "no-store", signal: ctrl.signal });
      if (res.ok) return true;
    } catch {
      /* cold / mid-restart / unreachable - keep waiting */
    } finally {
      clearTimeout(t);
    }
    if (Date.now() + delay >= deadline) break;
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay * 2, 8_000);
  }
  return false;
}

// Run `attempt`; if it fails with a transient connectivity error, wake the backend and
// retry exactly once. `attempt` must be re-runnable (e.g. rebuild any FormData inside it).
async function withWakeRetry<T>(attempt: () => Promise<T>): Promise<T> {
  try {
    return await attempt();
  } catch (err) {
    if (!isTransient(err)) throw err;
    await wakeBackend();
    return attempt();
  }
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw await errorFromResponse(res);
  return res.json() as Promise<T>;
}

// Wake-and-retry the initial page data: on a cold/spun-down free-tier backend the first
// request 502s, and without a retry the members + scenarios silently render empty.
export const getMembers = () => withWakeRetry(() => getJSON<Member[]>("/members"));
export const getScenarios = () => withWakeRetry(() => getJSON<Scenario[]>("/scenarios"));

// The upload-tab example gallery is a static manifest served by the frontend (public/samples),
// alongside the document images it points at - so it loads even if the backend is cold.
export async function getUploadSamples(): Promise<UploadSample[]> {
  try {
    const res = await fetch("/samples/manifest.json", { cache: "no-store" });
    return res.ok ? ((await res.json()) as UploadSample[]) : [];
  } catch {
    return [];
  }
}

// Seed prior same-day claims for the "multiple same-day claims" example (best-effort -
// only takes effect when the backend's Supabase ledger is configured).
export async function seedHistory(seed: {
  member_id: string;
  treatment_date: string;
  count: number;
}): Promise<void> {
  try {
    await fetch(`${API_URL}/samples/seed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(seed),
    });
  } catch {
    /* best-effort: the example still loads, it just won't trip the velocity rule */
  }
}
export const getClaims = () => getJSON<ClaimSummary[]>("/claims");
export const getClaim = (id: string) => getJSON<ClaimResult>(`/claims/${id}`);
// Aggregate dashboard metrics. Wake-and-retry since a cold free-tier backend 502s on first hit.
export const getAnalytics = () => withWakeRetry(() => getJSON<Analytics>("/analytics"));

export async function submitClaim(payload: Record<string, unknown>): Promise<ClaimResult> {
  const res = await fetch(`${API_URL}/claims`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await errorFromResponse(res);
  return res.json() as Promise<ClaimResult>;
}

/**
 * Resume a claim paused at a human-in-the-loop checkpoint by submitting a verdict.
 * Returns the final ClaimResult (status DECIDED) produced from that exact checkpoint.
 */
export async function resumeClaim(
  claimId: string,
  verdict: HumanReviewVerdict,
): Promise<ClaimResult> {
  const res = await fetch(`${API_URL}/claims/${encodeURIComponent(claimId)}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(verdict),
  });
  if (!res.ok) throw await errorFromResponse(res);
  return res.json() as Promise<ClaimResult>;
}

/**
 * Upload real documents and run the LIVE pipeline (OCR + LLM extraction), STREAMING the
 * pipeline progress as SSE so the UI animates from real node events (instead of blocking
 * on one awaited POST). Parses the stream exactly like `streamClaim`, including the late
 * `ai_assessment` event the non-blocking agent emits after the decision. Returns the final
 * ClaimResult (with any late AI assessment attached) or null.
 */
export async function uploadClaimStream(
  fields: Record<string, string | number>,
  files: File[],
  onEvent: (e: StreamEvent) => void,
): Promise<ClaimResult | null> {
  // Rebuilt per attempt: a FormData body is single-use, so the retry needs a fresh one.
  const attempt = async (): Promise<ClaimResult | null> => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(fields)) {
      if (v !== "" && v != null) fd.append(k, String(v));
    }
    for (const f of files) fd.append("files", f);
    const res = await fetch(`${API_URL}/claims/upload`, { method: "POST", body: fd });
    if (!res.ok || !res.body) throw await errorFromResponse(res);
    return consumeSSE(res, onEvent);
  };
  return withWakeRetry(attempt);
}

/**
 * Submit a human review of a decision. The backend turns it into a Langfuse
 * dataset item (input = the original claim, expected_output = the verdict/correction).
 */
export async function submitReview(payload: {
  claim_id: string;
  is_correct: boolean;
  criteria: string[];
  expected_notes: string;
}): Promise<ReviewResponse> {
  const res = await fetch(`${API_URL}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await errorFromResponse(res);
  return res.json() as Promise<ReviewResponse>;
}

/**
 * Stream a claim through the pipeline, invoking `onEvent` for each SSE event.
 * Returns the final ClaimResult.
 */
export async function streamClaim(
  payload: Record<string, unknown>,
  onEvent: (e: StreamEvent) => void,
): Promise<ClaimResult | null> {
  return withWakeRetry(() => _streamClaimImpl(payload, onEvent));
}

async function _streamClaimImpl(
  payload: Record<string, unknown>,
  onEvent: (e: StreamEvent) => void,
): Promise<ClaimResult | null> {
  const res = await fetch(`${API_URL}/claims/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) throw await errorFromResponse(res);
  const final = await consumeSSE(res, onEvent);
  // Some proxies/tunnels (e.g. ngrok) buffer or drop `text/event-stream` bodies, so the
  // stream can complete without ever delivering a result. Fall back to the non-streaming
  // endpoint so the decision still renders (just without the live pipeline animation).
  if (final === null) return submitClaim(payload);
  return final;
}

/**
 * Read an SSE response body, invoking `onEvent` for each event and returning the final
 * ClaimResult. The advisory AI agent runs off the critical path, so its `ai_assessment`
 * arrives AFTER the result; we attach it to the returned result so the decision view's AI
 * card appears once it lands (the decision itself already rendered, unblocked by the agent).
 */
async function consumeSSE(
  res: Response,
  onEvent: (e: StreamEvent) => void,
): Promise<ClaimResult | null> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: ClaimResult | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const evt = JSON.parse(line.slice(6)) as StreamEvent;
      onEvent(evt);
      if (evt.type === "result" || evt.type === "pending_review") {
        final = evt.result;
      } else if (evt.type === "ai_assessment" && final !== null) {
        // Late, non-blocking AI assessment → attach to the already-delivered result.
        const prev: ClaimResult = final;
        final = { ...prev, decision: { ...prev.decision, ai_assessment: evt.assessment } };
      }
    }
  }
  return final;
}
