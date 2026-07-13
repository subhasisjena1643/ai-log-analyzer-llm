import { useRef, useState } from "react";
import clsx from "clsx";
import { UploadCloud, FileText, X, Sparkles, ShieldAlert, Paperclip, BookOpen, HardDrive, Cloud, Gauge } from "lucide-react";
import { Button, Card, CardHeader, Pill } from "./ui";
import { scanPath, type AnalyzeInput, type IngestionProfile } from "../lib/api";

export type SourceKind = "upload" | "path" | "s3";
export type RunInput = AnalyzeInput & { source: SourceKind; location?: string; uri?: string };

const ACCEPTED = [
  ".log", ".txt", ".error", ".info", ".debug", ".out", ".trace",
  ".zip", ".tar", ".tgz", ".gz",
  ".sql", ".pdf", ".pcap", ".pcapng", ".wav", ".mp3", ".ogg", ".flac",
  ".properties", ".conf", ".cfg", ".ini", ".xml", ".yaml", ".yml", ".hprof",
].join(",");

const QUICK_QUERIES = [
  "Why are we seeing timeout errors?",
  "Diagnose database connection issues",
  "Analyze HTTP 500 errors and their cause",
  "Check for configuration mismatches",
];

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function ToggleRow({ label, on, onToggle, disabled }: { label: string; on: boolean; onToggle: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      className="flex w-full items-center justify-between gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2.5 text-left disabled:opacity-40"
    >
      <span className="text-sm text-[var(--color-ink)]">{label}</span>
      <span className={`flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors ${on ? "bg-[var(--color-ok)]/70" : "bg-[var(--color-elevated)]"}`}>
        <span className={`h-4 w-4 rounded-full bg-white transition-transform ${on ? "translate-x-4" : ""}`} />
      </span>
    </button>
  );
}

export function AnalyzePanel({ onRun, running }: { onRun: (input: RunInput) => void; running: boolean }) {
  const [source, setSource] = useState<SourceKind>("upload");
  const [location, setLocation] = useState("");
  const [uri, setUri] = useState("");
  const [scan, setScan] = useState<(IngestionProfile & { resolved: string }) | null>(null);
  const [scanErr, setScanErr] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [query, setQuery] = useState(QUICK_QUERIES[0]);
  const [terms, setTerms] = useState("");
  const [extraContext, setExtraContext] = useState("");
  const [appLabel, setAppLabel] = useState("");
  const [demoMode, setDemoMode] = useState(true);
  const [useKnowledge, setUseKnowledge] = useState(true);
  const [highAssurance, setHighAssurance] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function addFiles(list: FileList | null) {
    if (!list) return;
    const incoming = Array.from(list);
    setFiles((prev) => {
      const seen = new Set(prev.map((f) => f.name + f.size));
      return [...prev, ...incoming.filter((f) => !seen.has(f.name + f.size))];
    });
  }

  function removeFile(idx: number) {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  const sourceReady =
    (source === "upload" && files.length > 0) ||
    (source === "path" && location.trim().length > 0) ||
    (source === "s3" && uri.trim().startsWith("s3://"));
  const canRun = sourceReady && query.trim().length > 0 && !running;

  async function runScan() {
    setScanErr("");
    setScan(null);
    try {
      setScan(await scanPath(location.trim()));
    } catch (e) {
      setScanErr(e instanceof Error ? e.message : "Scan failed");
    }
  }

  function submit() {
    if (!canRun) return;
    onRun({
      source,
      files,
      location: location.trim(),
      uri: uri.trim(),
      query: query.trim(),
      confidentialTerms: terms.split(/[,\n]/).map((t) => t.trim()).filter(Boolean),
      extraContext: extraContext.trim(),
      appLabel: appLabel.trim() || "APP",
      demoMode,
      useKnowledge,
      highAssurance,
    });
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
      {/* Left: bundle upload */}
      <Card className="overflow-hidden">
        <CardHeader
          title="Diagnostic bundle"
          subtitle="Logs, archives, SQL, PDFs, JVM dumps, PCAP/SIP captures, audio CDRs, config"
          icon={<UploadCloud size={18} />}
        />
        <div className="p-5">
          {/* Source selector — browser upload, local/share path, or cloud (S3) */}
          <div className="mb-4 grid grid-cols-3 gap-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] p-1">
            {([
              { id: "upload", label: "Upload", icon: UploadCloud },
              { id: "path", label: "Local / share", icon: HardDrive },
              { id: "s3", label: "Cloud (S3)", icon: Cloud },
            ] as const).map((s) => {
              const Icon = s.icon;
              return (
                <button
                  key={s.id}
                  onClick={() => setSource(s.id)}
                  className={clsx(
                    "flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors",
                    source === s.id
                      ? "bg-[var(--color-brand)]/15 font-medium text-[var(--color-brand-fg)]"
                      : "text-[var(--color-muted)] hover:bg-[var(--color-elevated)]"
                  )}
                >
                  <Icon size={14} /> {s.label}
                </button>
              );
            })}
          </div>

          {source === "path" && (
            <div className="space-y-2">
              <input
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="D:\\logs\\incident-2026-07  or  \\\\share\\bundles\\case123"
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 font-mono text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)] focus:border-[var(--color-brand)]"
              />
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={runScan} disabled={!location.trim()}>
                  <Gauge size={14} /> Scan &amp; plan
                </Button>
                {scanErr && <span className="text-xs text-[var(--color-sev-error)]">{scanErr}</span>}
              </div>
              {scan && (
                <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2 text-xs text-[var(--color-muted)]">
                  <span className="text-[var(--color-ink)]">{scan.total_human}</span> · {scan.file_count} files ·
                  tier <span className="text-[var(--color-brand-fg)]">{scan.tier}</span> · {scan.max_workers} workers ·
                  cap {scan.max_structured_entries ?? "none"}
                  <div className="mt-0.5 text-[var(--color-faint)]">{scan.note}</div>
                </div>
              )}
              <p className="text-xs text-[var(--color-faint)]">Analyzed in place — no copy. Ideal for very large bundles the backend can reach.</p>
            </div>
          )}

          {source === "s3" && (
            <div className="space-y-2">
              <input
                value={uri}
                onChange={(e) => setUri(e.target.value)}
                placeholder="s3://my-bucket/incidents/case123/"
                className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 font-mono text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)] focus:border-[var(--color-brand)]"
              />
              <p className="text-xs text-[var(--color-faint)]">Objects under the prefix are streamed to the server, analyzed, then removed. Uses your AWS credentials.</p>
            </div>
          )}

          {source === "upload" && (
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
            onClick={() => inputRef.current?.click()}
            className={clsx(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
              dragging
                ? "border-[var(--color-brand)] bg-[var(--color-brand)]/5"
                : "border-[var(--color-border-strong)] hover:border-[var(--color-brand)]/60 hover:bg-[var(--color-elevated)]/40"
            )}
          >
            <UploadCloud size={26} className="text-[var(--color-brand)]" />
            <div className="text-sm font-medium text-[var(--color-ink)]">Drop files or click to browse</div>
            <div className="text-xs text-[var(--color-faint)]">Nested archives are extracted automatically · streamed for large bundles</div>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept={ACCEPTED}
              className="hidden"
              onChange={(e) => addFiles(e.target.files)}
            />
          </div>
          )}

          {source === "upload" && files.length > 0 && (
            <div className="mt-4 space-y-1.5">
              <div className="flex items-center justify-between px-1 text-xs text-[var(--color-faint)]">
                <span>{files.length} file{files.length > 1 ? "s" : ""} staged</span>
                <button className="hover:text-[var(--color-ink)]" onClick={() => setFiles([])}>
                  Clear all
                </button>
              </div>
              <div className="max-h-52 space-y-1.5 overflow-y-auto pr-1">
                {files.map((f, i) => (
                  <div
                    key={f.name + i}
                    className="flex items-center justify-between gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <FileText size={15} className="shrink-0 text-[var(--color-muted)]" />
                      <span className="truncate text-sm text-[var(--color-ink)]">{f.name}</span>
                      <Pill>{humanSize(f.size)}</Pill>
                    </div>
                    <button onClick={() => removeFile(i)} className="text-[var(--color-faint)] hover:text-[var(--color-sev-error)]">
                      <X size={15} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Right: query + NDA + additional context */}
      <div className="space-y-4">
        <Card>
          <CardHeader title="Investigation query" icon={<Sparkles size={18} />} />
          <div className="space-y-3 p-5">
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={3}
              placeholder="Describe the incident or ask a question…"
              className="w-full resize-none rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)] focus:border-[var(--color-brand)]"
            />
            <div className="flex flex-wrap gap-1.5">
              {QUICK_QUERIES.map((q) => (
                <button
                  key={q}
                  onClick={() => setQuery(q)}
                  className="rounded-md border border-[var(--color-border)] bg-[var(--color-elevated)] px-2 py-1 text-xs text-[var(--color-muted)] hover:border-[var(--color-brand)]/50 hover:text-[var(--color-ink)]"
                >
                  {q}
                </button>
              ))}
            </div>
            <input
              value={appLabel}
              onChange={(e) => setAppLabel(e.target.value)}
              placeholder="Environment label (optional, e.g. APP)"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)] focus:border-[var(--color-brand)]"
            />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Confidential terms"
            subtitle="Client / site names to neutralize before any processing"
            icon={<ShieldAlert size={18} />}
          />
          <div className="p-5">
            <input
              value={terms}
              onChange={(e) => setTerms(e.target.value)}
              placeholder="Acme Bank, Project Falcon, site-lon-01"
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)] focus:border-[var(--color-brand)]"
            />
            <p className="mt-2 text-xs text-[var(--color-faint)]">
              PII, secrets, emails, IPs and keys are always redacted automatically. These extra terms cover client-specific names.
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Additional context"
            subtitle="Incident report, PLE, chat/message logs — redacted before use"
            icon={<Paperclip size={18} />}
          />
          <div className="p-5">
            <textarea
              value={extraContext}
              onChange={(e) => setExtraContext(e.target.value)}
              rows={3}
              placeholder="Paste the first-incident email, ticket notes, or message excerpts…"
              className="w-full resize-none rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)] focus:border-[var(--color-brand)]"
            />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Knowledge reasoning"
            subtitle="Match against past runbooks & incidents (Confluence / Jira)"
            icon={<BookOpen size={18} />}
          />
          <div className="space-y-2.5 p-5">
            <ToggleRow
              label="Augment RCA with similar past incidents"
              on={useKnowledge}
              onToggle={() => setUseKnowledge((v) => !v)}
            />
            <ToggleRow
              label="Demo Mode (synthetic knowledge, no connection needed)"
              on={demoMode}
              onToggle={() => setDemoMode((v) => !v)}
              disabled={!useKnowledge}
            />
            {!demoMode && (
              <p className="text-xs text-[var(--color-faint)]">
                Live mode queries any Confluence/Jira connections you set up in <span className="text-[var(--color-muted)]">Integrations</span>. Falls back to demo if none are connected.
              </p>
            )}
            <ToggleRow
              label="High-assurance mode — cross-check 3 independent analyses (slower)"
              on={highAssurance}
              onToggle={() => setHighAssurance((v) => !v)}
            />
            {highAssurance && (
              <p className="text-xs text-[var(--color-faint)]">
                Runs the RCA 3× and keeps only claims multiple runs agree on, flagging single-run outliers as possible hallucinations. Uses more Bedrock calls.
              </p>
            )}
          </div>
        </Card>

        <Button onClick={submit} disabled={!canRun} className="w-full py-2.5">
          {running ? "Analyzing…" : "Run root-cause analysis"}
        </Button>
      </div>
    </div>
  );
}
