import type { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-lg border border-border bg-surface/70 backdrop-blur-sm ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between border-b border-border px-5 py-3.5">
      <h3 className="text-base text-ink">{title}</h3>
      {hint && <span className="text-xs text-ink-faint">{hint}</span>}
    </div>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">
      {children}
    </span>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "brand" | "approved" | "rejected" | "partial" | "review";
}) {
  const tones: Record<string, string> = {
    neutral: "border-border text-ink-muted",
    brand: "border-brand/30 text-brand bg-brand/10",
    approved: "border-approved/30 text-approved bg-approved/10",
    rejected: "border-rejected/30 text-rejected bg-rejected/10",
    partial: "border-partial/30 text-partial bg-partial/10",
    review: "border-review/30 text-review bg-review/10",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs ${tones[tone]}`}
    >
      {children}
    </span>
  );
}
