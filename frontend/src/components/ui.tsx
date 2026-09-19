import type { ReactNode } from "react";
import type { Severity } from "../api/types";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-line bg-surface-900 p-5 shadow-lg shadow-black/30 ${className}`}>
      {children}
    </div>
  );
}

const SEVERITY_STYLES: Record<Severity, string> = {
  critical: "bg-red-500/15 text-red-300 border-red-500/40",
  high: "bg-orange-500/15 text-orange-300 border-orange-500/40",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  pass: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
};

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "CRITICAL",
  high: "HIGH",
  medium: "MEDIUM",
  pass: "PASS",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-bold tracking-wider ${SEVERITY_STYLES[severity]}`}
    >
      {SEVERITY_LABEL[severity]}
    </span>
  );
}

export function ModeBadge({ mode }: { mode: "vulnerable" | "secure" | null }) {
  if (!mode) {
    return (
      <span className="inline-flex items-center rounded-md border border-line bg-surface-800 px-2.5 py-1 text-[11px] font-bold tracking-wider text-slate-400">
        MODE —
      </span>
    );
  }
  const secure = mode === "secure";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-bold tracking-wider ${
        secure
          ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
          : "border-red-500/40 bg-red-500/15 text-red-300"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${secure ? "bg-emerald-400" : "bg-red-400"}`} />
      {secure ? "SECURE" : "VULNERABLE"}
    </span>
  );
}

export function StatusDot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? "bg-slate-500" : ok ? "bg-emerald-400" : "bg-red-400";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-slate-500 border-t-accent ${className}`}
    />
  );
}
