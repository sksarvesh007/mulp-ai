import type { TraceEvent } from "@/lib/types";
import { friendlyStep, TRACE_STATUS } from "@/lib/format";

export function TraceTimeline({ trace }: { trace: TraceEvent[] }) {
  if (!trace.length) {
    return <p className="px-5 py-4 text-sm text-ink-faint">No trace events.</p>;
  }
  return (
    <ol className="scroll-thin max-h-[28rem] space-y-0 overflow-y-auto px-3 py-2">
      {trace.map((e, i) => {
        const meta = TRACE_STATUS[e.status] ?? TRACE_STATUS.info;
        return (
          <li key={i} className="relative flex gap-3 pl-1">
            {/* rail */}
            <div className="relative flex flex-col items-center">
              <span className={`mt-1.5 size-2.5 shrink-0 rounded-full ${meta.dot}`} />
              {i < trace.length - 1 && <span className="w-px flex-1 bg-border" />}
            </div>
            <div className="min-w-0 flex-1 pb-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`text-[13px] font-medium ${meta.text}`}>{meta.glyph}</span>
                <span className="text-[13px] font-medium text-ink">{friendlyStep(e.step)}</span>
              </div>
              <p className="mt-0.5 text-[13px] leading-relaxed text-ink-muted">{e.detail}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
