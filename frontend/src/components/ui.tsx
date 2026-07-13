import clsx from "clsx";
import type { ReactNode } from "react";
import type { Severity } from "../lib/types";
import { severityStyles } from "../lib/format";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={clsx(
        "rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)]",
        className
      )}
    >
      {children}
    </div>
  );
}

export function CardHeader({ title, subtitle, icon, action }: { title: string; subtitle?: string; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-[var(--color-border)] px-5 py-3.5">
      <div className="flex items-start gap-3">
        {icon && <div className="mt-0.5 text-[var(--color-brand)]">{icon}</div>}
        <div>
          <h3 className="text-sm font-semibold text-[var(--color-ink)]">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-[var(--color-faint)]">{subtitle}</p>}
        </div>
      </div>
      {action}
    </div>
  );
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = severityStyles[severity] ?? severityStyles.INFO;
  return (
    <span className={clsx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium", s.bg, s.text)}>
      <span className={clsx("h-1.5 w-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  className,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "outline";
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50";
  const variants = {
    primary: "bg-[var(--color-brand)] text-white hover:bg-indigo-500",
    outline: "border border-[var(--color-border-strong)] text-[var(--color-ink)] hover:bg-[var(--color-elevated)]",
    ghost: "text-[var(--color-muted)] hover:bg-[var(--color-elevated)] hover:text-[var(--color-ink)]",
  };
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={clsx(base, variants[variant], className)}>
      {children}
    </button>
  );
}

export function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-2)] px-4 py-3">
      <div className="text-xs uppercase tracking-wide text-[var(--color-faint)]">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-[var(--color-ink)]">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-[var(--color-faint)]">{hint}</div>}
    </div>
  );
}

export function Pill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-elevated)] px-2 py-0.5 text-xs text-[var(--color-muted)]",
        className
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({ icon, title, hint }: { icon?: ReactNode; title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
      {icon && <div className="text-[var(--color-faint)]">{icon}</div>}
      <p className="text-sm font-medium text-[var(--color-muted)]">{title}</p>
      {hint && <p className="max-w-sm text-xs text-[var(--color-faint)]">{hint}</p>}
    </div>
  );
}
