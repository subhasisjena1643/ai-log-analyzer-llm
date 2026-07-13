import clsx from "clsx";
import { Activity, ShieldCheck, Layers, Plug, Settings, Radar } from "lucide-react";
import type { HealthStatus } from "../lib/types";

export type View = "analyze" | "integrations" | "settings";

const NAV: { id: View; label: string; icon: typeof Activity; enabled: boolean }[] = [
  { id: "analyze", label: "Analyze", icon: Radar, enabled: true },
  { id: "integrations", label: "Integrations", icon: Plug, enabled: true },
  { id: "settings", label: "Settings", icon: Settings, enabled: true },
];

export function Sidebar({
  view,
  onView,
  health,
}: {
  view: View;
  onView: (v: View) => void;
  health: HealthStatus | null;
}) {
  const llmReady = health?.llm.ready;
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]">
      <div className="flex items-center gap-2.5 px-5 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-brand)]/15 text-[var(--color-brand)]">
          <Activity size={18} strokeWidth={2.4} />
        </div>
        <div>
          <div className="text-sm font-semibold leading-tight text-[var(--color-ink)]">LogSentry AI</div>
          <div className="text-[11px] leading-tight text-[var(--color-faint)]">Enterprise RCA</div>
        </div>
      </div>

      <nav className="mt-2 flex flex-col gap-0.5 px-3">
        {NAV.map((item) => {
          const Icon = item.icon;
          const active = view === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onView(item.id)}
              className={clsx(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-[var(--color-brand)]/12 font-medium text-[var(--color-brand-fg)]"
                  : "text-[var(--color-muted)] hover:bg-[var(--color-elevated)] hover:text-[var(--color-ink)]"
              )}
            >
              <Icon size={17} />
              {item.label}
            </button>
          );
        })}
      </nav>

      <div className="mt-auto space-y-2 p-3">
        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] p-3">
          <div className="flex items-center gap-2 text-xs text-[var(--color-muted)]">
            <ShieldCheck size={14} className="text-[var(--color-ok)]" />
            NDA-safe redaction active
          </div>
          <div className="mt-2 flex items-center gap-2 text-xs">
            <span className={clsx("h-2 w-2 rounded-full", llmReady ? "bg-[var(--color-ok)]" : "bg-[var(--color-sev-warn)]")} />
            <span className="text-[var(--color-muted)]">
              {llmReady ? `LLM online · ${health?.llm.model?.split(".").pop() ?? ""}` : "LLM offline (local fallback)"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 px-1 text-[11px] text-[var(--color-faint)]">
          <Layers size={12} /> Phase 3 · 8 diagnostic agents
        </div>
      </div>
    </aside>
  );
}
