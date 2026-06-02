"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

/**
 * A header "Devlog" tab with a bouncing "click here" hint that opens a floating window.
 * The content sections are scaffolding for now and get filled in incrementally.
 */
export function Devlog() {
  const [open, setOpen] = useState(false);
  const [hintSeen, setHintSeen] = useState(false);
  const [zoomed, setZoomed] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (zoomed) setZoomed(null);
      else setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomed]);

  const openDevlog = () => {
    setOpen(true);
    setHintSeen(true);
  };

  return (
    <>
      <div className="relative">
        <button
          onClick={openDevlog}
          className="pressable rounded-md border border-brand/40 bg-brand/10 px-3 py-1.5 text-sm font-medium text-brand hover:bg-brand/20"
        >
          Devlog
        </button>
        {!hintSeen && (
          <span className="pointer-events-none absolute right-0 top-full z-40 mt-1.5 flex animate-bounce items-center gap-1 whitespace-nowrap rounded-full bg-brand px-2 py-0.5 text-[11px] font-medium text-cream shadow">
            <span aria-hidden>↑</span> click here
          </span>
        )}
      </div>

      {open &&
        createPortal(
          // Portaled into <body>: the header's backdrop-blur makes it a containing block for
          // fixed descendants, which would otherwise trap this overlay inside the 64px header.
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Devlog"
            onClick={() => setOpen(false)}
            className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-black/75 p-4 py-16 backdrop-blur-sm"
          >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ backgroundColor: "var(--color-surface)" }}
            className="animate-fade-up w-full max-w-2xl overflow-hidden rounded-xl border border-border-strong shadow-2xl"
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
              <div>
                <p className="text-[11px] uppercase tracking-wider text-ink-faint">Build notes</p>
                <h2 className="font-display text-xl text-ink">Devlog</h2>
              </div>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close devlog"
                className="pressable rounded-md px-2 py-1 text-ink-muted hover:bg-surface-2 hover:text-ink"
              >
                ✕
              </button>
            </div>

            <div className="max-h-[72vh] space-y-7 overflow-y-auto px-5 py-5 text-sm leading-relaxed text-ink-muted">
              <section className="space-y-3">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-brand">
                  A few things worth mentioning
                </h3>
                <ol className="space-y-3">
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">01</span>
                    <p>
                      <span className="text-ink">The LLM provider can be a bit unreliable.</span> Not the
                      extraction itself, which is solid - it is the provider&apos;s platform (availability
                      and rate limits) that is not the most stable. I tried the free tiers from Groq and
                      Gemini, but the limits ran out fast, so I am currently on a provider I happened to
                      find in a year-old GitHub repo. It does the job, but it is the least stable piece of
                      the stack.
                    </p>
                  </li>
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">02</span>
                    <div className="space-y-2">
                      <p>
                        <span className="text-ink">All the human-review feedback is captured as
                        dataset items in Langfuse.</span> I would have self-hosted Langfuse and shared
                        direct access, but free-tier compute made that impractical, so it lives on
                        Langfuse Cloud for now.
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        {["/image.png", "/image_2.png"].map((src) => (
                          <button
                            key={src}
                            onClick={() => setZoomed(src)}
                            className="pressable overflow-hidden rounded-md border border-border hover:border-brand/50"
                          >
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img src={src} alt="Langfuse dataset" className="h-28 w-full object-cover" />
                          </button>
                        ))}
                      </div>
                      <p className="text-[11px] text-ink-faint">Click an image to enlarge.</p>
                    </div>
                  </li>
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">03</span>
                    <p>
                      <span className="text-ink">The intake + document-upload pipeline can be slow,</span>{" "}
                      and once in a while it stalls mid-run. If that happens, do a hard refresh and try
                      again. Same root cause: that flaky LLM provider.
                    </p>
                  </li>
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">04</span>
                    <p>
                      <span className="text-ink">OCR is a plain (Tesseract) model for now,</span> purely
                      because of hardware limits. With better compute I would swap in a vision-language
                      model (VLM) for much stronger reading of messy, real-world documents.
                    </p>
                  </li>
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">05</span>
                    <p>
                      <span className="text-ink">
                        There might be one or two minor differences in the pipeline run to run
                      </span>{" "}
                      (atleast not a deterministic pipeline though).
                    </p>
                  </li>
                </ol>
              </section>

              <section className="space-y-3">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-brand">
                  What I would build next to improve the pipeline
                </h3>
                <ol className="space-y-3">
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">01</span>
                    <p>
                      <span className="text-ink">Integrate a VLM</span> for document understanding,
                      replacing the OCR + text-LLM extraction path.
                    </p>
                  </li>
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">02</span>
                    <p>
                      <span className="text-ink">A hill-climbing loop</span> that uses the human-in-the-loop
                      verdicts together with the Langfuse feedback dataset to iteratively improve the AI
                      system (run evals over the collected data, then refine prompts and matching).
                    </p>
                  </li>
                  <li className="flex gap-2.5">
                    <span className="mt-px shrink-0 text-xs font-medium text-brand">03</span>
                    <p>
                      <span className="text-ink">Drive down latency</span> across the pipeline.
                    </p>
                  </li>
                </ol>
              </section>
            </div>
          </div>
          </div>,
          document.body,
        )}

      {zoomed &&
        createPortal(
          <div
            onClick={() => setZoomed(null)}
            className="fixed inset-0 z-[110] flex items-center justify-center bg-black/85 p-6"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={zoomed}
              alt="Langfuse (enlarged)"
              className="max-h-[92vh] max-w-[94vw] rounded-lg shadow-2xl"
            />
          </div>,
          document.body,
        )}
    </>
  );
}
