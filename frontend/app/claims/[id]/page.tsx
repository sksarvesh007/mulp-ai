"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getClaim, toFriendlyMessage } from "@/lib/api";
import type { ClaimResult } from "@/lib/types";
import { DecisionView } from "@/components/DecisionView";

export default function ClaimDetail() {
  const params = useParams<{ id: string }>();
  const [result, setResult] = useState<ClaimResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!params?.id) return;
    getClaim(params.id)
      .then(setResult)
      .catch((e) => setError(toFriendlyMessage(e)));
  }, [params?.id]);

  return (
    <div className="space-y-6">
      <Link href="/claims" className="pressable inline-block text-sm text-ink-muted hover:text-ink">
        ← All claims
      </Link>
      {error && <p className="text-sm text-rejected">{error}</p>}
      {result ? (
        <DecisionView result={result} />
      ) : (
        !error && <p className="text-sm text-ink-faint">Loading…</p>
      )}
    </div>
  );
}
