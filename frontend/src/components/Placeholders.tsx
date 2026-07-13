import { useEffect, useState } from "react";
import { BookText, Ticket, ShieldCheck, Info, Plug, Search, CheckCircle2, XCircle } from "lucide-react";
import { Button, Card, CardHeader, Pill } from "./ui";
import { connectProvider, disconnectProvider, getIntegrationsStatus, knowledgeSearch } from "../lib/api";
import type { ConnectionState, KnowledgeMatch } from "../lib/types";

/**
 * Integrations surface. Runtime, in-app connections — credentials are sent to the
 * backend session only and never persisted. Demo Mode always works with no connection.
 */
export function IntegrationsView() {
  const [states, setStates] = useState<ConnectionState[]>([]);

  async function refresh() {
    setStates(await getIntegrationsStatus(false));
  }
  useEffect(() => {
    refresh();
  }, []);

  const stateOf = (p: string) => states.find((s) => s.provider === p);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-start gap-2 rounded-lg border border-[var(--color-brand)]/25 bg-[var(--color-brand)]/8 px-4 py-3 text-sm text-[var(--color-brand-fg)]">
        <Info size={16} className="mt-0.5 shrink-0" />
        <span>
          Connect on the fly — credentials are held in the server session only, never written to code or disk.
          No connection? <strong>Demo Mode</strong> gives the full retrieval experience with synthetic data.
        </span>
      </div>

      <Card>
        <CardHeader
          title="Demo knowledge base"
          subtitle="Synthetic runbooks & incidents — always available"
          icon={<Plug size={18} />}
          action={<Pill className="border-emerald-500/30 text-[var(--color-ok)]">Active</Pill>}
        />
        <div className="p-5">
          <DemoSearch />
        </div>
      </Card>

      <ConnectCard
        provider="confluence"
        title="Atlassian Confluence"
        subtitle="Search runbooks & KB spaces for similar problems"
        icon={<BookText size={18} />}
        state={stateOf("confluence")}
        fields={[
          { key: "base_url", label: "Base URL", placeholder: "https://your-org.atlassian.net/wiki" },
          { key: "email", label: "Account email", placeholder: "sre@your-org.com" },
          { key: "token", label: "API token", placeholder: "••••••••", type: "password" },
          { key: "spaces", label: "Spaces (comma-sep)", placeholder: "SRE, RUNBOOK" },
        ]}
        onChanged={refresh}
      />

      <ConnectCard
        provider="jira"
        title="Atlassian Jira"
        subtitle="Correlate with prior incidents & tickets"
        icon={<Ticket size={18} />}
        state={stateOf("jira")}
        fields={[
          { key: "base_url", label: "Base URL", placeholder: "https://your-org.atlassian.net" },
          { key: "email", label: "Account email", placeholder: "sre@your-org.com" },
          { key: "token", label: "API token", placeholder: "••••••••", type: "password" },
          { key: "jql", label: "Scope (JQL, optional)", placeholder: "project = INC" },
        ]}
        onChanged={refresh}
      />
    </div>
  );
}

function DemoSearch() {
  const [q, setQ] = useState("database connection pool timeout");
  const [rows, setRows] = useState<KnowledgeMatch[]>([]);
  const [busy, setBusy] = useState(false);
  async function go() {
    setBusy(true);
    try {
      setRows(await knowledgeSearch(q, true));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div>
      <div className="flex gap-2">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && go()}
          className="flex-1 rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] outline-none focus:border-[var(--color-brand)]"
        />
        <Button onClick={go} disabled={busy}>
          <Search size={15} /> {busy ? "…" : "Search"}
        </Button>
      </div>
      <div className="mt-3 space-y-1.5">
        {rows.map((m) => (
          <div key={m.source + m.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2">
            <div className="min-w-0">
              <span className="font-mono text-xs font-semibold text-[var(--color-brand-fg)]">{m.id}</span>
              <span className="ml-2 text-sm text-[var(--color-ink)]">{m.title}</span>
            </div>
            <span className="shrink-0 text-xs tabular-nums text-[var(--color-faint)]">{Math.round(m.score * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

interface FieldDef {
  key: string;
  label: string;
  placeholder: string;
  type?: string;
}

function ConnectCard({
  provider,
  title,
  subtitle,
  icon,
  state,
  fields,
  onChanged,
}: {
  provider: "confluence" | "jira";
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  state?: ConnectionState;
  fields: FieldDef[];
  onChanged: () => void;
}) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");
  const connected = state?.connected;

  async function connect() {
    setBusy(true);
    setMsg("");
    try {
      const body: Record<string, unknown> = { ...vals };
      if (provider === "confluence" && vals.spaces) body.spaces = vals.spaces.split(",").map((s) => s.trim());
      const res = await connectProvider(provider, body);
      setMsg(res.connected ? "Connected" : `Failed: ${res.detail}`);
      onChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Connection failed");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    await disconnectProvider(provider);
    setMsg("");
    onChanged();
  }

  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={subtitle}
        icon={icon}
        action={
          connected ? (
            <Pill className="border-emerald-500/30 text-[var(--color-ok)]"><CheckCircle2 size={11} /> {state?.account || "Connected"}</Pill>
          ) : (
            <Pill>Not connected</Pill>
          )
        }
      />
      <div className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-2">
        {fields.map((f) => (
          <label key={f.key} className="block">
            <span className="mb-1 block text-xs text-[var(--color-faint)]">{f.label}</span>
            <input
              type={f.type || "text"}
              placeholder={f.placeholder}
              value={vals[f.key] || ""}
              onChange={(e) => setVals((v) => ({ ...v, [f.key]: e.target.value }))}
              className="w-full rounded-lg border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2 text-sm text-[var(--color-ink)] outline-none placeholder:text-[var(--color-faint)] focus:border-[var(--color-brand)]"
            />
          </label>
        ))}
      </div>
      <div className="flex items-center gap-3 border-t border-[var(--color-border)] px-5 py-3">
        {connected ? (
          <Button variant="outline" onClick={disconnect}>Disconnect</Button>
        ) : (
          <Button onClick={connect} disabled={busy}>{busy ? "Connecting…" : "Connect"}</Button>
        )}
        {msg && (
          <span className={`flex items-center gap-1 text-xs ${msg === "Connected" ? "text-[var(--color-ok)]" : "text-[var(--color-sev-error)]"}`}>
            {msg === "Connected" ? <CheckCircle2 size={13} /> : <XCircle size={13} />} {msg}
          </span>
        )}
      </div>
    </Card>
  );
}

export function SettingsView() {
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <Card>
        <CardHeader title="Privacy & redaction" subtitle="Applied before any storage, LLM call, or external lookup" icon={<ShieldCheck size={18} />} />
        <div className="space-y-3 p-5 text-sm text-[var(--color-muted)]">
          <Toggle label="Redact PII, secrets, emails, IPs and keys" on />
          <Toggle label="Neutralize client/site names (per-run confidential terms)" on />
          <Toggle label="Strip client & zone identifiers from parsed logs" on />
          <p className="text-xs text-[var(--color-faint)]">
            Redaction is enforced server-side and cannot be bypassed from the UI. Add your own client resources
            (e.g. an internal portal export) to a bundle manually before running — they are redacted like everything else.
          </p>
        </div>
      </Card>
    </div>
  );
}

function Toggle({ label, on }: { label: string; on?: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-3 py-2.5">
      <span className="text-[var(--color-ink)]">{label}</span>
      <span className={`flex h-5 w-9 items-center rounded-full px-0.5 ${on ? "bg-[var(--color-ok)]/70" : "bg-[var(--color-elevated)]"}`}>
        <span className={`h-4 w-4 rounded-full bg-white transition-transform ${on ? "translate-x-4" : ""}`} />
      </span>
    </div>
  );
}
