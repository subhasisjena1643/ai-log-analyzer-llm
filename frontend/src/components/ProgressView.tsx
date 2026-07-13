import clsx from "clsx";
import { Check, Loader2 } from "lucide-react";
import { Card } from "./ui";
import { prettyStage } from "../lib/format";
import type { ProgressEvent } from "../lib/types";

const STAGE_ORDER = ["ingest", "agents", "analysis", "llm", "done"];

export function ProgressView({ events }: { events: ProgressEvent[] }) {
  const pct = Math.round((events[events.length - 1]?.pct ?? 0) * 100);

  // Determine per-stage status from the event stream
  const stageStatus = (stage: string): "done" | "active" | "pending" => {
    const rel = events.filter((e) => e.stage === stage);
    if (rel.some((e) => e.status === "done")) return "done";
    if (rel.length > 0) return "active";
    // if a later stage started, mark earlier as done
    const idx = STAGE_ORDER.indexOf(stage);
    const laterStarted = events.some((e) => STAGE_ORDER.indexOf(e.stage ?? "") > idx);
    return laterStarted ? "done" : "pending";
  };

  const activeAgents = Array.from(
    new Set(events.filter((e) => (e.stage ?? "").startsWith("agent:")).map((e) => (e.stage ?? "").slice(6)))
  );

  return (
    <Card className="mx-auto max-w-2xl p-8">
      <div className="mb-6 text-center">
        <div className="text-sm font-medium text-[var(--color-ink)]">Analyzing diagnostics</div>
        <div className="mt-1 text-xs text-[var(--color-faint)]">
          Files are extracted, routed to specialized agents, correlated, and reasoned over.
        </div>
      </div>

      <div className="mb-6 h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-elevated)]">
        <div
          className="h-full rounded-full bg-[var(--color-brand)] transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="space-y-2.5">
        {STAGE_ORDER.filter((s) => s !== "done").map((stage) => {
          const status = stageStatus(stage);
          return (
            <div key={stage} className="flex items-center gap-3">
              <div
                className={clsx(
                  "flex h-6 w-6 items-center justify-center rounded-full border",
                  status === "done" && "border-[var(--color-ok)]/40 bg-[var(--color-ok)]/15 text-[var(--color-ok)]",
                  status === "active" && "border-[var(--color-brand)]/40 bg-[var(--color-brand)]/15 text-[var(--color-brand)]",
                  status === "pending" && "border-[var(--color-border)] text-[var(--color-faint)]"
                )}
              >
                {status === "done" ? <Check size={13} /> : status === "active" ? <Loader2 size={13} className="animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
              </div>
              <div className="flex-1">
                <div className={clsx("text-sm", status === "pending" ? "text-[var(--color-faint)]" : "text-[var(--color-ink)]")}>
                  {prettyStage(stage)}
                </div>
                {stage === "agents" && status === "active" && activeAgents.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {activeAgents.map((a) => (
                      <span key={a} className="rounded bg-[var(--color-elevated)] px-1.5 py-0.5 text-[10px] text-[var(--color-muted)]">
                        {a}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
