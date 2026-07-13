import { useState } from "react";
import clsx from "clsx";
import ReactMarkdown from "react-markdown";
import {
  Download, RotateCcw, Brain, ListChecks, FileSearch, Boxes, ScrollText,
  AlertTriangle, Clock, ShieldCheck, Wrench, BookOpen, ExternalLink, Ticket,
} from "lucide-react";
import { Button, Card, CardHeader, Metric, Pill, SeverityBadge, EmptyState } from "./ui";
import { downloadReport } from "../lib/api";
import { logLevelColor, formatDuration } from "../lib/format";
import type { AnalysisResult } from "../lib/types";

type Tab = "rca" | "knowledge" | "solutions" | "evidence" | "diagnostics" | "agents" | "logs";

export function ResultsView({ result, onReset }: { result: AnalysisResult; onReset: () => void }) {
  const [tab, setTab] = useState<Tab>("rca");
  const { meta, rca, stats, agents, knowledge } = result;
  const hasKnowledge = !!knowledge?.available && knowledge.matches.length > 0;

  const TABS: { id: Tab; label: string; icon: typeof Brain }[] = [
    { id: "rca", label: "Root Cause", icon: Brain },
    ...(hasKnowledge ? [{ id: "knowledge" as Tab, label: "Similar Incidents", icon: BookOpen }] : []),
    { id: "solutions", label: "Fixes", icon: Wrench },
    { id: "evidence", label: "Evidence", icon: FileSearch },
    { id: "diagnostics", label: "Diagnostics", icon: Boxes },
    { id: "agents", label: "Agents", icon: ListChecks },
    { id: "logs", label: "Logs", icon: ScrollText },
  ];
  const redactionTotal = Object.values(meta.redaction_summary || {}).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold text-[var(--color-ink)]">Analysis complete</h2>
              <SeverityBadge severity={meta.overall_severity} />
            </div>
            <p className="mt-1 max-w-xl text-sm text-[var(--color-muted)]">“{meta.query}”</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Pill>{rca.error_type}</Pill>
              <Pill><Clock size={11} /> {formatDuration(meta.duration_ms)}</Pill>
              <Pill><ShieldCheck size={11} className="text-[var(--color-ok)]" /> {redactionTotal} redactions</Pill>
              <Pill>env · {meta.app}</Pill>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => downloadReport(rca.report_markdown, meta.app)}>
              <Download size={15} /> Report
            </Button>
            <Button variant="ghost" onClick={onReset}>
              <RotateCcw size={15} /> New
            </Button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Metric label="Files" value={stats.file_count} />
          <Metric label="Errors" value={stats.total_errors} />
          <Metric label="Components" value={stats.unique_components} />
          <Metric label="Findings" value={agents.total_findings} />
        </div>
      </Card>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-1">
        {TABS.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={clsx(
                "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
                tab === t.id
                  ? "bg-[var(--color-brand)]/15 font-medium text-[var(--color-brand-fg)]"
                  : "text-[var(--color-muted)] hover:bg-[var(--color-elevated)] hover:text-[var(--color-ink)]"
              )}
            >
              <Icon size={15} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "rca" && <RcaTab result={result} />}
      {tab === "knowledge" && <KnowledgeTab result={result} />}
      {tab === "solutions" && <SolutionsTab result={result} />}
      {tab === "evidence" && <EvidenceTab result={result} />}
      {tab === "diagnostics" && <DiagnosticsTab result={result} />}
      {tab === "agents" && <AgentsTab result={result} />}
      {tab === "logs" && <LogsTab result={result} />}
    </div>
  );
}

function ConsensusPanel({ consensus }: { consensus: NonNullable<AnalysisResult["consensus"]> }) {
  const pct = Math.round(consensus.agreement_score * 100);
  const tone = pct >= 70 ? "text-[var(--color-ok)]" : pct >= 40 ? "text-[var(--color-sev-warn)]" : "text-[var(--color-sev-error)]";
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-[var(--color-brand)]" />
          <span className="text-sm font-semibold text-[var(--color-ink)]">High-assurance consensus</span>
          <Pill>{consensus.runs} runs</Pill>
        </div>
        <div className="text-right">
          <div className={clsx("text-xl font-semibold tabular-nums", tone)}>{pct}%</div>
          <div className="text-[10px] uppercase tracking-wide text-[var(--color-faint)]">agreement</div>
        </div>
      </div>
      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-elevated)]">
        <div className={clsx("h-full rounded-full", pct >= 70 ? "bg-[var(--color-ok)]" : pct >= 40 ? "bg-[var(--color-sev-warn)]" : "bg-[var(--color-sev-error)]")} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-[var(--color-faint)]">
        {consensus.consensus_claims.length} claim(s) agreed across runs · {consensus.flagged_claims.length} single-run outlier(s) flagged.
      </p>
      {consensus.flagged_claims.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-500/25 bg-amber-500/10 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-sev-warn)]">
            <AlertTriangle size={13} /> Flagged — appeared in only one run (verify before acting)
          </div>
          <ul className="mt-1.5 space-y-1">
            {consensus.flagged_claims.map((c, i) => (
              <li key={i} className="text-xs text-[var(--color-muted)]">
                • {c.text} <span className="text-[var(--color-faint)]">({c.support}/{consensus.runs})</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function RcaTab({ result }: { result: AnalysisResult }) {
  const { rca, anomaly, time_correlation, consensus } = result;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_1fr]">
      <div className="space-y-4">
        {consensus && consensus.runs > 0 && <ConsensusPanel consensus={consensus} />}
        <Card>
          <CardHeader
            title="AI Root Cause Analysis"
            subtitle={consensus && consensus.runs > 0 ? `Consensus of ${consensus.runs} independent analyses` : "Generated by AWS Bedrock over redacted diagnostics"}
            icon={<Brain size={18} />}
          />
          <div className="p-5">
            <div className="prose-rca">
              <ReactMarkdown>{rca.llm_explanation || "_No AI explanation generated._"}</ReactMarkdown>
            </div>
          </div>
        </Card>
      </div>
      <div className="space-y-4">
        <Card>
          <CardHeader title="Anomaly detection" icon={<AlertTriangle size={18} />} />
          <div className="p-5">
            <div className={clsx("rounded-lg border px-3 py-2 text-sm", anomaly.anomaly_detected ? "border-rose-500/25 bg-rose-500/10 text-[var(--color-sev-error)]" : "border-emerald-500/25 bg-emerald-500/10 text-[var(--color-ok)]")}>
              {anomaly.anomaly_detected ? "Anomaly detected" : "No anomaly detected"}
            </div>
            <p className="mt-3 whitespace-pre-line text-xs text-[var(--color-muted)]">{anomaly.message}</p>
            {anomaly.error_frequency && anomaly.error_frequency.length > 0 && (
              <div className="mt-4 space-y-1.5">
                {anomaly.error_frequency.map((b) => {
                  const max = Math.max(...anomaly.error_frequency!.map((x) => x.count));
                  return (
                    <div key={b.time} className="flex items-center gap-2">
                      <span className="w-16 shrink-0 text-[11px] tabular-nums text-[var(--color-faint)]">{b.time}</span>
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--color-elevated)]">
                        <div className="h-full rounded-full bg-[var(--color-sev-error)]" style={{ width: `${(b.count / max) * 100}%` }} />
                      </div>
                      <span className="w-6 text-right text-[11px] tabular-nums text-[var(--color-muted)]">{b.count}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </Card>
        <Card>
          <CardHeader title="Automated summary" icon={<Clock size={18} />} />
          <div className="space-y-3 p-5">
            <p className="whitespace-pre-line text-xs text-[var(--color-muted)]">{rca.automated_rca}</p>
            <div className={clsx("rounded-lg border px-3 py-2 text-xs", time_correlation.correlated ? "border-amber-500/25 bg-amber-500/10 text-[var(--color-sev-warn)]" : "border-[var(--color-border)] text-[var(--color-muted)]")}>
              {time_correlation.message}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function KnowledgeTab({ result }: { result: AnalysisResult }) {
  const k = result.knowledge;
  if (!k || !k.available) {
    return <Card><EmptyState icon={<BookOpen size={22} />} title="No similar incidents retrieved" hint="Enable knowledge reasoning, or connect Confluence/Jira in Integrations." /></Card>;
  }
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_1fr]">
      <Card>
        <CardHeader
          title="Narrowed analysis"
          subtitle={k.llm_refined ? "LLM-reasoned over retrieved knowledge" : "Grounded in retrieved runbooks & incidents"}
          icon={<Brain size={18} />}
          action={<Pill>{(k.sources || []).join(" + ") || "demo"}</Pill>}
        />
        <div className="p-5">
          <div className="prose-rca">
            <ReactMarkdown>{k.narrowed_analysis || "_No narrowed analysis generated._"}</ReactMarkdown>
          </div>
        </div>
      </Card>
      <Card>
        <CardHeader title="Closest matches" subtitle={`${k.matches.length} retrieved`} icon={<FileSearch size={18} />} />
        <div className="divide-y divide-[var(--color-border)]">
          {k.matches.map((m) => {
            const isIncident = m.kind === "incident" || m.kind === "ticket";
            const pct = Math.round(m.score * 100);
            return (
              <div key={m.source + m.id} className="px-5 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {isIncident ? <Ticket size={14} className="text-[var(--color-sev-warn)]" /> : <BookOpen size={14} className="text-[var(--color-brand)]" />}
                    <span className="font-mono text-xs font-semibold text-[var(--color-brand-fg)]">{m.id}</span>
                    {m.status && <Pill>{m.status}</Pill>}
                  </div>
                  <span className="text-xs tabular-nums text-[var(--color-faint)]">{pct}%</span>
                </div>
                <div className="mt-1 text-sm text-[var(--color-ink)]">{m.title}</div>
                <p className="mt-1 line-clamp-2 text-xs text-[var(--color-faint)]">{m.snippet}</p>
                <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-[var(--color-elevated)]">
                  <div className="h-full rounded-full bg-[var(--color-brand)]" style={{ width: `${pct}%` }} />
                </div>
                {m.url && (
                  <a href={m.url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-xs text-[var(--color-brand)] hover:underline">
                    Open <ExternalLink size={11} />
                  </a>
                )}
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}

function SolutionsTab({ result }: { result: AnalysisResult }) {
  const solutions = result.kb_solutions.length ? result.kb_solutions : result.solutions;
  if (!solutions.length) {
    return <Card><EmptyState icon={<Wrench size={22} />} title="No knowledge-base matches" hint="No similar past fixes were retrieved for this query." /></Card>;
  }
  // De-duplicate identical solutions
  const seen = new Set<string>();
  const unique = solutions.filter((s) => {
    const key = (s.error_type || s.error || "") + (s.solution || (s.solution_steps || []).join(""));
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {unique.map((s, i) => (
        <Card key={i} className="p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="text-sm font-semibold text-[var(--color-ink)]">{s.error_type || s.error || "Known issue"}</div>
            {s.confidence && <Pill>{s.confidence}</Pill>}
          </div>
          {s.root_cause && <p className="mt-1.5 text-xs text-[var(--color-faint)]">Cause: {s.root_cause}</p>}
          <div className="mt-3 space-y-1.5">
            {(s.solution_steps || (s.solution ? [s.solution] : [])).map((step, j) => (
              <div key={j} className="flex items-start gap-2 text-sm text-[var(--color-muted)]">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--color-brand)]/15 text-[10px] font-medium text-[var(--color-brand-fg)]">{j + 1}</span>
                {step}
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}

function EvidenceTab({ result }: { result: AnalysisResult }) {
  const { evidence } = result;
  const groups = [
    { title: "Exact matches", lines: evidence.exact_matches },
    { title: "Similar errors", lines: evidence.similar_errors },
    { title: "Error lines", lines: evidence.error_lines },
  ].filter((g) => g.lines.length);

  if (!groups.length) return <Card><EmptyState icon={<FileSearch size={22} />} title="No error evidence extracted" /></Card>;
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <Card key={g.title}>
          <CardHeader title={g.title} subtitle={`${g.lines.length} line${g.lines.length > 1 ? "s" : ""}`} icon={<FileSearch size={18} />} />
          <div className="max-h-80 overflow-auto p-3">
            <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-[var(--color-sev-error)]">
              {g.lines.slice(0, 60).join("\n")}
            </pre>
          </div>
        </Card>
      ))}
    </div>
  );
}

function DiagnosticsTab({ result }: { result: AnalysisResult }) {
  const { diagnostics } = result;
  const counts = Object.entries(diagnostics.file_counts).filter(([, v]) => v > 0);
  const contexts: { key: string; label: string; data: Record<string, unknown> }[] = [
    { key: "sql_context", label: "SQL / Database", data: diagnostics.sql_context },
    { key: "pdf_context", label: "PDF Healthchecks", data: diagnostics.pdf_context },
    { key: "memory_context", label: "JVM / Heap", data: diagnostics.memory_context },
    { key: "inference_context", label: "SRE Notes", data: diagnostics.inference_context },
    { key: "pcap_context", label: "PCAP / SIP", data: diagnostics.pcap_context },
    { key: "audio_context", label: "Audio / CDR", data: diagnostics.audio_context },
    { key: "config_context", label: "Config", data: diagnostics.config_context },
  ].filter((c) => Object.keys(c.data || {}).length);

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <div className="mb-3 text-sm font-semibold text-[var(--color-ink)]">Files by type</div>
        {counts.length ? (
          <div className="flex flex-wrap gap-2">
            {counts.map(([k, v]) => (
              <div key={k} className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2">
                <div className="text-lg font-semibold tabular-nums text-[var(--color-ink)]">{v}</div>
                <div className="text-[11px] uppercase tracking-wide text-[var(--color-faint)]">{k}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-[var(--color-faint)]">No categorized files.</p>
        )}
      </Card>
      {contexts.map((c) => (
        <Card key={c.key}>
          <CardHeader title={c.label} subtitle={`${Object.keys(c.data).length} file(s)`} icon={<Boxes size={18} />} />
          <div className="max-h-72 overflow-auto p-4">
            <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-[var(--color-muted)]">
              {JSON.stringify(c.data, null, 2)}
            </pre>
          </div>
        </Card>
      ))}
      {!contexts.length && (
        <Card><EmptyState icon={<Boxes size={22} />} title="No specialized diagnostics" hint="Upload SQL, PDF, JVM, PCAP, audio or config files to see richer context here." /></Card>
      )}
    </div>
  );
}

function AgentsTab({ result }: { result: AnalysisResult }) {
  const entries = Object.entries(result.agents.summaries);
  const timings = result.agents.timings;
  if (!entries.length) return <Card><EmptyState icon={<ListChecks size={22} />} title="No agents reported" /></Card>;
  return (
    <Card>
      <CardHeader title="Diagnostic agent timeline" subtitle="Parallel-by-type distributed analysis" icon={<ListChecks size={18} />} />
      <div className="divide-y divide-[var(--color-border)]">
        {entries.map(([name, summary]) => (
          <div key={name} className="flex items-start gap-4 px-5 py-3.5">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--color-brand)]/12 text-xs font-semibold uppercase text-[var(--color-brand-fg)]">
              {name.slice(0, 2)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-[var(--color-ink)]">{name}</span>
                {timings[name] != null && <Pill>{formatDuration(timings[name])}</Pill>}
              </div>
              <p className="mt-0.5 text-xs text-[var(--color-muted)]">{summary}</p>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function LogsTab({ result }: { result: AnalysisResult }) {
  const logs = result.logs_sample;
  if (!logs.length) return <Card><EmptyState icon={<ScrollText size={22} />} title="No parsed log entries" /></Card>;
  return (
    <Card>
      <CardHeader title="Parsed log entries" subtitle={`Showing ${logs.length} redacted entries`} icon={<ScrollText size={18} />} />
      <div className="max-h-[32rem] overflow-auto">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-[var(--color-surface-2)] text-[var(--color-faint)]">
            <tr>
              <th className="px-4 py-2 font-medium">Timestamp</th>
              <th className="px-4 py-2 font-medium">Level</th>
              <th className="px-4 py-2 font-medium">Component</th>
              <th className="px-4 py-2 font-medium">Message</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {logs.map((l, i) => (
              <tr key={i} className="border-t border-[var(--color-border)] hover:bg-[var(--color-elevated)]/40">
                <td className="whitespace-nowrap px-4 py-1.5 text-[var(--color-faint)]">{l.timestamp}</td>
                <td className={clsx("px-4 py-1.5 font-semibold", logLevelColor(l.log_level))}>{l.log_level}</td>
                <td className="px-4 py-1.5 text-[var(--color-muted)]">{l.component || "—"}</td>
                <td className="px-4 py-1.5 text-[var(--color-ink)]">{l.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
