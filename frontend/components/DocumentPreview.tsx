"use client";

import { useEffect, useState } from "react";

type Item = { name: string; type: string; url: string };

/**
 * Client-side previews of the documents a user has attached: image thumbnails and a
 * PDF tile, each opening a click-to-enlarge lightbox. Uses object URLs (no upload needed).
 *
 * The URLs are created INSIDE the effect (not useMemo) so React Strict Mode's
 * mount→cleanup→remount cycle recreates them - otherwise the cleanup would revoke URLs
 * that useMemo wouldn't rebuild, leaving broken thumbnails.
 */
export function DocumentPreview({ files }: { files: File[] }) {
  const [active, setActive] = useState<number | null>(null);
  const [items, setItems] = useState<Item[]>([]);

  useEffect(() => {
    const made = files.map((f) => ({ name: f.name, type: f.type, url: URL.createObjectURL(f) }));
    // eslint-disable-next-line react-hooks/set-state-in-effect -- deriving object URLs needs an effect (cleanup)
    setItems(made);
    return () => made.forEach((m) => URL.revokeObjectURL(m.url));
  }, [files]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setActive(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (items.length === 0) return null;

  const isImage = (t: string) => t.startsWith("image/");
  const open = active != null ? items[active] : null;

  return (
    <>
      <div className="grid grid-cols-3 gap-2">
        {items.map((it, i) => (
          <button
            key={i}
            type="button"
            onClick={() => setActive(i)}
            title={`Preview ${it.name}`}
            className="pressable group relative aspect-[4/3] overflow-hidden rounded-md border border-border bg-surface-2/40 hover:border-brand/50"
          >
            {isImage(it.type) ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={it.url} alt={it.name} className="size-full object-cover" />
            ) : (
              <span className="flex size-full flex-col items-center justify-center gap-1 text-ink-faint">
                <span className="text-2xl">📄</span>
                <span className="text-[10px]">PDF</span>
              </span>
            )}
            <span className="absolute inset-x-0 bottom-0 truncate bg-bg/70 px-1.5 py-0.5 text-[10px] text-ink-muted">
              {it.name}
            </span>
          </button>
        ))}
      </div>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={`Preview of ${open.name}`}
          onClick={() => setActive(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-bg/80 p-6 backdrop-blur-sm animate-fade-up"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-border bg-surface"
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <span className="truncate text-sm text-ink">{open.name}</span>
              <button
                type="button"
                onClick={() => setActive(null)}
                aria-label="Close preview"
                className="pressable rounded-md px-2 py-1 text-sm text-ink-muted hover:bg-surface-2 hover:text-ink"
              >
                ✕
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-auto bg-surface-2/30 p-2">
              {isImage(open.type) ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={open.url} alt={open.name} className="mx-auto max-h-[78vh] object-contain" />
              ) : (
                <iframe src={open.url} title={open.name} className="h-[78vh] w-full rounded bg-white" />
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
