"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getAnalytics } from "@/lib/api";
import type { Analytics } from "@/lib/types";
import { Card, CardHeader, Eyebrow } from "@/components/primitives";
import { fmtDay, fmtINR } from "@/lib/format";

// Chart colours pulled from the app's design tokens (globals.css @theme).
const C = {
  approved: "#92bd33",
  partial: "#ffba21",
  rejected: "#ff4052",
  review: "#6db0e0",
  action: "#c7a6ba",
  brand: "#ff4052",
  axis: "#8d6a7e",
  grid: "rgba(255,255,255,0.07)",
};

// Recharts tooltip styled for the dark burgundy surface.
const TOOLTIP = {
  contentStyle: {
    background: "#2b0b21",
    border: "1px solid rgba(255,255,255,0.14)",
    borderRadius: 10,
    fontSize: 12,
    color: "#fff1e5",
  },
  labelStyle: { color: "#c7a6ba" },
  itemStyle: { color: "#fff1e5" },
} as const;

const SEGMENTS: { key: "approved" | "partial" | "rejected" | "review" | "action"; label: string; color: string }[] = [
  { key: "approved", label: "Approved", color: C.approved },
  { key: "partial", label: "Partial", color: C.partial },
  { key: "rejected", label: "Rejected", color: C.rejected },
  { key: "review", label: "In review", color: C.review },
  { key: "action", label: "Action needed", color: C.action },
];

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    getAnalytics()
      .then(setData)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <Eyebrow>Operations</Eyebrow>
        <h1 className="mt-2 text-3xl text-ink">Analytics</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Aggregate view across every processed claim. Times shown in IST.
        </p>
      </div>

      {loading ? (
        <Card>
          <p className="px-5 py-8 text-sm text-ink-faint">Loading analytics…</p>
        </Card>
      ) : error ? (
        <Card>
          <p className="px-5 py-8 text-sm text-ink-faint">Couldn&apos;t load analytics. Try again in a moment.</p>
        </Card>
      ) : !data || data.total_claims === 0 ? (
        <Card>
          <p className="px-5 py-8 text-sm text-ink-faint">
            No claims yet. <Link href="/" className="text-brand">Process one</Link> to populate the dashboard.
          </p>
        </Card>
      ) : (
        <Dashboard a={data} />
      )}
    </div>
  );
}

function Dashboard({ a }: { a: Analytics }) {
  const donut = SEGMENTS.map((s) => ({ name: s.label, value: a[s.key], color: s.color })).filter((d) => d.value > 0);
  const overTime = a.over_time.map((p) => ({ ...p, label: fmtDay(p.date) }));

  return (
    <div className="space-y-6">
      {/* KPI row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <Stat label="Total claims" value={a.total_claims.toLocaleString("en-IN")} />
        <Stat label="Approval rate" value={`${(a.approval_rate * 100).toFixed(0)}%`} sub="of adjudicated" />
        <Stat label="Total approved" value={fmtINR(a.total_approved_amount)} />
        <Stat
          label="Avg confidence"
          value={a.avg_confidence == null ? "–" : `${(a.avg_confidence * 100).toFixed(0)}%`}
        />
        <Stat label="Needs attention" value={(a.review + a.action).toLocaleString("en-IN")} sub="review / action" />
        <Stat label="Degraded" value={a.degraded_count.toLocaleString("en-IN")} sub="reduced checks" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Decision mix donut */}
        <ChartCard title="Decision mix" hint={`${a.total_claims} claims`}>
          <div className="flex h-full items-center gap-4">
            <div className="h-full min-w-0 flex-1">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={donut}
                    dataKey="value"
                    nameKey="name"
                    innerRadius="58%"
                    outerRadius="82%"
                    paddingAngle={2}
                    stroke="none"
                  >
                    {donut.map((d) => (
                      <Cell key={d.name} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip {...TOOLTIP} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <ul className="shrink-0 space-y-1.5 pr-2 text-sm">
              {donut.map((d) => (
                <li key={d.name} className="flex items-center gap-2">
                  <span className="size-2.5 rounded-sm" style={{ background: d.color }} />
                  <span className="text-ink-muted">{d.name}</span>
                  <span className="ml-auto tabular-nums text-ink">{d.value}</span>
                </li>
              ))}
            </ul>
          </div>
        </ChartCard>

        {/* Claims by category (stacked) */}
        <ChartCard title="Claims by category" hint="by outcome">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={a.by_category} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis
                dataKey="category"
                tick={{ fill: C.axis, fontSize: 11 }}
                tickFormatter={(s: string) => s.toLowerCase().replace(/_/g, " ")}
                axisLine={{ stroke: C.grid }}
                tickLine={false}
                interval={0}
                angle={-12}
                textAnchor="end"
                height={48}
              />
              <YAxis tick={{ fill: C.axis, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip {...TOOLTIP} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              {SEGMENTS.map((s, i) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  stackId="x"
                  fill={s.color}
                  radius={i === SEGMENTS.length - 1 ? [3, 3, 0, 0] : undefined}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Claims over time */}
        <ChartCard title="Claims over time" hint="per day (IST)">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={overTime} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <defs>
                <linearGradient id="claimsFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={C.brand} stopOpacity={0.45} />
                  <stop offset="100%" stopColor={C.brand} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="label" tick={{ fill: C.axis, fontSize: 11 }} axisLine={{ stroke: C.grid }} tickLine={false} minTickGap={24} />
              <YAxis tick={{ fill: C.axis, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip {...TOOLTIP} cursor={{ stroke: C.grid }} />
              <Area type="monotone" dataKey="claims" name="Claims" stroke={C.brand} strokeWidth={2} fill="url(#claimsFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        {/* Confidence distribution */}
        <ChartCard title="Confidence distribution" hint="auto-adjudicated claims">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={a.confidence_buckets} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid stroke={C.grid} vertical={false} />
              <XAxis dataKey="bucket" tick={{ fill: C.axis, fontSize: 11 }} axisLine={{ stroke: C.grid }} tickLine={false} />
              <YAxis tick={{ fill: C.axis, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip {...TOOLTIP} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="count" name="Claims" fill={C.review} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className="animate-fade-up px-5 py-4">
      <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-faint">{label}</div>
      <div className="mt-1.5 font-display text-2xl leading-none text-ink">{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-faint">{sub}</div>}
    </Card>
  );
}

function ChartCard({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <Card className="animate-fade-up">
      <CardHeader title={title} hint={hint} />
      <div className="h-[260px] px-3 py-4">{children}</div>
    </Card>
  );
}
