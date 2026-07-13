import { useEffect, useState } from "react";
import { AlertCircle } from "lucide-react";
import { Sidebar, type View } from "./components/Sidebar";
import { AnalyzePanel, type RunInput } from "./components/AnalyzePanel";
import { ProgressView } from "./components/ProgressView";
import { ResultsView } from "./components/ResultsView";
import { IntegrationsView, SettingsView } from "./components/Placeholders";
import { analyzeStream, analyzePathStream, analyzeS3Stream, getHealth } from "./lib/api";
import type { AnalysisResult, HealthStatus, ProgressEvent } from "./lib/types";

type Phase = "idle" | "running" | "done";

export default function App() {
  const [view, setView] = useState<View>("analyze");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  async function run(input: RunInput) {
    setPhase("running");
    setEvents([]);
    setResult(null);
    setError(null);
    const onEvt = (e: typeof events[number]) => setEvents((prev) => [...prev, e]);
    try {
      let res;
      if (input.source === "path") {
        res = await analyzePathStream({ ...input, location: input.location || "" }, onEvt);
      } else if (input.source === "s3") {
        res = await analyzeS3Stream({ ...input, location: input.location || "", uri: input.uri || "" }, onEvt);
      } else {
        res = await analyzeStream(input, onEvt);
      }
      setResult(res);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
      setPhase("idle");
    }
  }

  function reset() {
    setPhase("idle");
    setResult(null);
    setEvents([]);
    setError(null);
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--color-canvas)]">
      <Sidebar view={view} onView={setView} health={health} />

      <div className="flex flex-1 flex-col overflow-hidden">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-surface)]/60 px-6 backdrop-blur">
          <div>
            <h1 className="text-sm font-semibold text-[var(--color-ink)]">
              {view === "analyze" && "Root-Cause Analysis"}
              {view === "integrations" && "Integrations"}
              {view === "settings" && "Settings"}
            </h1>
            <p className="text-xs text-[var(--color-faint)]">
              {view === "analyze" && "Upload enterprise diagnostics and get an NDA-safe, agent-driven RCA"}
              {view === "integrations" && "Connect Confluence & Jira for retrieval-augmented reasoning"}
              {view === "settings" && "Privacy, redaction, and pipeline controls"}
            </p>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto max-w-6xl">
            {error && (
              <div className="mb-4 flex items-center gap-2 rounded-lg border border-rose-500/25 bg-rose-500/10 px-4 py-3 text-sm text-[var(--color-sev-error)]">
                <AlertCircle size={16} /> {error}
              </div>
            )}

            {view === "analyze" && (
              <>
                {phase === "idle" && <AnalyzePanel onRun={run} running={false} />}
                {phase === "running" && <ProgressView events={events} />}
                {phase === "done" && result && <ResultsView result={result} onReset={reset} />}
              </>
            )}
            {view === "integrations" && <IntegrationsView />}
            {view === "settings" && <SettingsView />}
          </div>
        </main>
      </div>
    </div>
  );
}
