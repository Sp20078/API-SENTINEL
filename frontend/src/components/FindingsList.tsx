import type { CheckResult, Finding } from "../api/types";
import { SeverityBadge } from "./ui";

export function FindingsList({
  findings,
  checks,
  selectedId,
  onSelect,
}: {
  findings: Finding[];
  checks: CheckResult[];
  selectedId: string | null;
  onSelect: (finding: Finding) => void;
}) {
  const hasContent = findings.length > 0 || checks.length > 0;

  return (
    <div className="rounded-xl border border-line bg-surface-900">
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <h3 className="text-sm font-semibold text-slate-300">Findings</h3>
        {hasContent && (
          <span className="text-xs text-slate-500">
            {findings.length} finding{findings.length === 1 ? "" : "s"} · {checks.length} passed
            check{checks.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {!hasContent && (
        <div className="px-5 py-10 text-center text-sm text-slate-500">
          No findings yet — run your first authorization scan.
        </div>
      )}

      <ul className="divide-y divide-line">
        {findings.map((f) => (
          <li key={f.id}>
            <button
              onClick={() => onSelect(f)}
              className={`flex w-full items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-surface-800 ${
                selectedId === f.id ? "bg-surface-800" : ""
              }`}
            >
              <SeverityBadge severity={f.severity} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[13px] font-semibold text-slate-200">
                    {f.endpoint}
                  </span>
                  <span className="rounded bg-surface-800 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400">
                    {f.id}
                  </span>
                  {f.status === "pass" && (
                    <span className="text-[10px] font-bold uppercase tracking-wide text-emerald-300">
                      fixed
                    </span>
                  )}
                </div>
                <p className="mt-0.5 truncate text-[13px] text-slate-400">{f.title}</p>
              </div>
              <span className="hidden shrink-0 items-center gap-1 text-xs font-semibold tabular-nums sm:flex">
                <span className="text-emerald-300/70">{f.expected_status}</span>
                <span className="text-slate-600">→</span>
                <span className={f.observed_status === 200 ? "text-red-300" : "text-emerald-300"}>
                  {f.observed_status}
                </span>
              </span>
              <span className="text-slate-600">›</span>
            </button>
          </li>
        ))}
        {checks.map((c) => (
          <li key={c.id} className="flex items-center gap-4 px-5 py-4">
            <SeverityBadge severity="pass" />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[13px] font-semibold text-slate-200">
                  {c.endpoint}
                </span>
                <span className="rounded bg-surface-800 px-1.5 py-0.5 text-[10px] font-semibold text-slate-400">
                  {c.id}
                </span>
              </div>
              <p className="mt-0.5 truncate text-[13px] text-slate-400">
                {c.resource_owner}'s resource blocked for {c.authenticated_role}{" "}
                {c.authenticated_user}
              </p>
            </div>
            <span className="hidden shrink-0 items-center gap-1 text-xs font-semibold tabular-nums sm:flex">
              <span className="text-emerald-300/70">{c.expected_status}</span>
              <span className="text-slate-600">→</span>
              <span className="text-emerald-300">{c.observed_status}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
