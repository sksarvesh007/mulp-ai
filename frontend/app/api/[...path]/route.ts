import type { NextRequest } from "next/server";

// Runtime reverse-proxy for the FastAPI backend. Reading BACKEND_ORIGIN here (not in a
// next.config rewrite) means the backend URL is resolved on each request at RUNTIME - so
// it works when the URL is only known after deploy (e.g. Render's service URL), without a
// rebuild. Keeps the backend off the public origin; the browser only talks to /api/*.
export const dynamic = "force-dynamic";

function backendOrigin(): string {
  const raw = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";
  return /^https?:\/\//.test(raw) ? raw : `https://${raw}`;
}

// hop-by-hop / encoding headers must not be forwarded (fetch already decodes the body).
const DROP = new Set([
  "host",
  "connection",
  "content-length",
  "content-encoding",
  "transfer-encoding",
  "accept-encoding",
]);

async function handler(req: NextRequest, ctx: { params: Promise<{ path?: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${backendOrigin()}/${(path ?? []).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((v, k) => {
    if (!DROP.has(k.toLowerCase())) headers.set(k, v);
  });

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const init: RequestInit & { duplex?: "half" } = { method: req.method, headers, redirect: "manual" };
  if (hasBody) {
    init.body = req.body;
    init.duplex = "half"; // required to stream a request body (multipart uploads, SSE POST)
  }

  // Cap how long we wait for the upstream to start responding. 120s comfortably covers a
  // warm heavy upload (OCR + LLM) and a free-tier cold start; the timer is cleared the
  // moment headers arrive, so a long-lived SSE response body is never cut off.
  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), 120_000);
  init.signal = ctrl.signal;

  let res: Response;
  try {
    res = await fetch(target, init);
  } catch (err) {
    // Distinguish a timeout (504) from an unreachable backend (502); either way return
    // clean JSON so the client shows a friendly message, not Next.js's HTML error page.
    const timedOut = err instanceof Error && err.name === "AbortError";
    return Response.json(
      {
        detail: timedOut
          ? "The server took too long to respond. Please try again."
          : "The server is temporarily unavailable. Please try again in a moment.",
      },
      { status: timedOut ? 504 : 502 },
    );
  } finally {
    clearTimeout(timeout);
  }
  const out = new Headers();
  res.headers.forEach((v, k) => {
    if (!DROP.has(k.toLowerCase())) out.set(k, v);
  });
  return new Response(res.body, { status: res.status, headers: out });
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
