"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getClaims } from "@/lib/api";
import type { ClaimSummary } from "@/lib/types";
import { Card, CardHeader, Eyebrow, Pill } from "@/components/primitives";
import { decisionMeta, fmtDate, fmtINR } from "@/lib/format";

export default function ClaimsPage() {
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getClaims()
      .then(setClaims)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <Eyebrow>Operations</Eyebrow>
        <h1 className="mt-2 text-3xl text-ink">Processed claims</h1>
      </div>

      <Card>
        <CardHeader title="All claims" hint={`${claims.length} total`} />
        {loading ? (
          <p className="px-5 py-6 text-sm text-ink-faint">Loading…</p>
        ) : claims.length === 0 ? (
          <p className="px-5 py-6 text-sm text-ink-faint">
            No claims yet. <Link href="/" className="text-brand">Submit one</Link>.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {claims.map((c) => {
              const meta = decisionMeta(c.decision);
              return (
                <li key={c.claim_id}>
                  <Link
                    href={`/claims/${c.claim_id}`}
                    className="pressable flex items-center justify-between gap-4 px-5 py-3.5 hover:bg-surface-2/50"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <span className={`size-2 shrink-0 rounded-full ${meta.dot}`} />
                      <code className="text-sm text-ink">{c.claim_id}</code>
                      <span className="hidden text-xs text-ink-faint sm:inline">
                        {c.member_id} · {c.category?.toLowerCase()} · {fmtDate(c.created_at)}
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      {c.degraded && <Pill tone="review">degraded</Pill>}
                      {c.confidence != null && (
                        <span className="text-xs text-ink-faint">
                          {(c.confidence * 100).toFixed(0)}%
                        </span>
                      )}
                      <span className="text-sm text-ink-muted">{fmtINR(c.approved_amount)}</span>
                      <Pill tone={pillTone(c.decision)}>{meta.label}</Pill>
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}

function pillTone(
  decision: ClaimSummary["decision"],
): "approved" | "rejected" | "partial" | "review" | "neutral" {
  switch (decision) {
    case "APPROVED":
      return "approved";
    case "REJECTED":
      return "rejected";
    case "PARTIAL":
      return "partial";
    case "MANUAL_REVIEW":
      return "review";
    default:
      return "neutral";
  }
}
