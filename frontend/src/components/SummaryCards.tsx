import type { ScanSummary, Severity } from "../api/types";
import type { Finding } from "../api/types";

function scoreColor(score: number): string {
  if (score >= 80) return "text-emerald-300";
  if (score >= 40) return "text-amber-300";
  return "text-red-300";
}

function Card2({
  label,
  value,
  sub,
  valueClass = "text-slate-100",
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface-900 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-bold tabular-nums ${valueClass}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

export function SummaryCards({
  summary,
  findings,
  lastScanAt,
}: {
  summary: ScanSummary;
  findings: Finding[];
  lastScanAt: string | null;
}) {
  const bySeverity = (s: Severity) => findings.filter((f) => f.severity === s).length;
  const critical = bySeverity("critical");
  const high = bySeverity("high");
  const medium = bySeverity("medium");

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Card2
        label="Security score"
        value={`${summary.security_score}`}
        sub="0–100"
        valueClass={scoreColor(summary.security_score)}
      />
      <Card2
        label="Endpoints tested"
        value={`${summary.tested_endpoints}`}
        sub={`${summary.discovered_endpoints} discovered`}
      />
      <Card2 label="Critical" value={`${critical}`} sub="findings" valueClass="text-red-300" />
      <Card2
        label="High / Medium"
        value={`${high} / ${medium}`}
        sub="findings"
        valueClass={high + medium > 0 ? "text-amber-300" : "text-slate-100"}
      />
      <Card2
        label="Passed checks"
        value={`${summary.passed}`}
        sub={`${summary.failed} failed`}
        valueClass={summary.passed > 0 ? "text-emerald-300" : "text-slate-100"}
      />
      <Card2 label="Last scan" value={lastScanAt ?? "—"} sub={`${summary.duration_ms} ms`} />
    </div>
  );
}
