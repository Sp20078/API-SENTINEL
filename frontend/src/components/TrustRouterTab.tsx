import { useCallback, useEffect, useState } from "react";
import { DEFAULT_MODES, TRUST_CITIES, trustApi } from "../api/trustRouter";
import type {
  DecisionStep,
  PolicyCheck,
  ProviderAttempt,
  TrustRouterResult,
  TrustScore,
} from "../api/trustRouter";
import { Card, Spinner, StatusDot } from "./ui";

const PRIMARY_MODES = DEFAULT_MODES;

function StepDot({ status }: { status: DecisionStep["status"] }) {
  const color =
    status === "ok"
      ? "bg-emerald-400"
      : status === "fail"
        ? "bg-red-400"
        : "bg-slate-500";
  return <span className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${color}`} />;
}

function CheckRow({ check }: { check: PolicyCheck }) {
  const pass = check.status === "pass";
  return (
    <li className="flex items-start gap-2.5 py-1.5">
      <span
        className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
          pass ? "bg-emerald-500/20 text-emerald-300" : "bg-red-500/20 text-red-300"
        }`}
      >
        {pass ? "✓" : "✗"}
      </span>
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-slate-200">{check.label}</p>
        <p className={`text-xs ${pass ? "text-slate-400" : "text-red-300"}`}>{check.detail}</p>
      </div>
    </li>
  );
}

function ScoreBar({ label, earned, max, detail }: { label: string; earned: number; max: number; detail: string }) {
  const pct = max === 0 ? 0 : Math.round((earned / max) * 100);
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-slate-300">{label}</span>
        <span className="font-mono text-slate-400">
          {earned}/{max}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-700">
        <div
          className={`h-full rounded-full ${pct >= 100 ? "bg-emerald-400" : pct > 0 ? "bg-amber-400" : "bg-red-400"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="truncate text-[11px] text-slate-500" title={detail}>
        {detail}
      </p>
    </div>
  );
}

const SCORE_LABELS: Record<string, string> = {
  schema_valid: "schema valid",
  latency: "latency",
  required_fields: "required fields",
  prohibited_fields: "prohibited fields",
  freshness: "freshness",
  availability: "availability",
};

function TrustScorePanel({ score }: { score: TrustScore }) {
  const bandColor =
    score.band === "trusted"
      ? "text-emerald-300 border-emerald-500/40 bg-emerald-500/10"
      : score.band === "acceptable"
        ? "text-amber-300 border-amber-500/40 bg-amber-500/10"
        : "text-red-300 border-red-500/40 bg-red-500/10";
  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300">Trust score</h3>
        <span
          className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-bold tracking-wider ${bandColor}`}
        >
          {score.band.toUpperCase()}
        </span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-4xl font-bold text-slate-100">{score.total}</span>
        <span className="text-sm text-slate-500">/ 100</span>
        {!score.hard_gates_passed && (
          <span className="ml-auto rounded-md border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[11px] font-semibold text-red-300">
            gate failed: {score.failed_gates.join(", ")}
          </span>
        )}
      </div>
      <div className="space-y-2.5">
        {score.components.map((c) => (
          <ScoreBar
            key={c.id}
            label={SCORE_LABELS[c.id] ?? c.id}
            earned={c.earned}
            max={c.max}
            detail={c.detail}
          />
        ))}
      </div>
    </Card>
  );
}

function AttemptCard({ attempt }: { attempt: ProviderAttempt }) {
  const isPrimary = attempt.role === "primary";
  const ok = attempt.status_code === 200 && attempt.schema_valid !== false;
  return (
    <Card className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-300">
          {isPrimary ? "Primary provider" : "Backup provider"}
        </h3>
        <span
          className={`rounded-md border px-2 py-0.5 text-[11px] font-bold tracking-wider ${
            ok
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-red-500/40 bg-red-500/10 text-red-300"
          }`}
        >
          {ok ? "HEALTHY" : "REJECTED"}
        </span>
      </div>
      <p className="font-mono text-xs text-slate-400">{attempt.provider}</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-300">
        <span>
          HTTP <span className="font-mono">{attempt.status_code ?? "—"}</span>
        </span>
        <span>
          latency <span className="font-mono">{attempt.latency_ms ?? "—"} ms</span>
        </span>
        <span>
          schema{" "}
          <span className="font-mono">
            {attempt.schema_valid === null ? "—" : attempt.schema_valid ? "valid" : "invalid"}
          </span>
        </span>
        <span>
          trust{" "}
          <span className="font-mono">
            {attempt.trust_score ? `${attempt.trust_score.total}/100` : "—"}
          </span>
        </span>
      </div>
      {attempt.error && <p className="text-xs text-red-300">{attempt.error}</p>}
      {attempt.schema_errors.length > 0 && (
        <ul className="list-inside list-disc space-y-0.5 text-xs text-red-300">
          {attempt.schema_errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {attempt.raw_fields_redacted.length > 0 && (
        <p className="text-xs text-red-300">
          prohibited fields: {attempt.raw_fields_redacted.join(", ")}
        </p>
      )}
      <details className="text-xs text-slate-500">
        <summary className="cursor-pointer select-none hover:text-slate-400">
          raw field names ({attempt.raw_fields.length})
        </summary>
        <p className="mt-1 font-mono text-[11px] leading-relaxed">
          {attempt.raw_fields.join("  ·  ") || "—"}
        </p>
      </details>
    </Card>
  );
}

export default function TrustRouterTab() {
  const [city, setCity] = useState("Bengaluru");
  const [mode, setMode] = useState("healthy");
  const [busy, setBusy] = useState(false);
  const [settingMode, setSettingMode] = useState(false);
  const [result, setResult] = useState<TrustRouterResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [currentMode, setCurrentMode] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    trustApi
      .getProviders()
      .then((p) => {
        if (!cancelled) {
          const modes = p.primary.modes ?? DEFAULT_MODES;
          if (!modes.includes(mode)) setMode("healthy");
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeMode = useCallback(
    async (next: string) => {
      setError(null);
      setNotice(null);
      setSettingMode(true);
      try {
        const resp = await trustApi.setPrimaryMode(next);
        setMode(resp.mode);
        setCurrentMode(resp.mode);
        setNotice(`Primary provider mode set to ${resp.mode}.`);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unexpected error");
      } finally {
        setSettingMode(false);
      }
    },
    [],
  );

  const run = useCallback(async () => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const r = await trustApi.request(city.trim() || "Bengaluru");
      setResult(r);
      if (r.primary_mode) setCurrentMode(r.primary_mode);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  }, [city]);

  const primary = result?.attempts.find((a) => a.role === "primary") ?? null;
  const backup = result?.attempts.find((a) => a.role === "backup") ?? null;

  return (
    <div className="space-y-5">
      {/* Demo label */}
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-800 px-2.5 py-1 font-semibold tracking-wide text-slate-400">
          🧪 SYNTHETIC · LOCAL DEMO — no real weather data, no external calls
        </span>
        <span className="inline-flex items-center gap-1.5">
          <StatusDot ok={true} /> providers :8002 · router :8000
        </span>
        {currentMode && (
          <span className="text-slate-600">
            primary mode: <span className="font-mono text-slate-400">{currentMode}</span>
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <span className="font-semibold">Error: </span>
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-lg border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-sky-200">
          {notice}
        </div>
      )}

      {/* Controls */}
      <Card>
        <div className="grid gap-4 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wider text-slate-500">
              City
            </span>
            <input
              list="trust-cities"
              value={city}
              onChange={(e) => setCity(e.target.value)}
              placeholder="Bengaluru"
              className="w-full rounded-lg border border-line bg-surface-950 px-3 py-2 text-sm text-slate-200 focus:border-accent focus:outline-none"
            />
            <datalist id="trust-cities">
              {TRUST_CITIES.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] uppercase tracking-wider text-slate-500">
              Primary provider mode
            </span>
            <select
              value={mode}
              onChange={(e) => changeMode(e.target.value)}
              disabled={settingMode}
              className="w-full rounded-lg border border-line bg-surface-950 px-3 py-2 text-sm text-slate-200 focus:border-accent focus:outline-none disabled:opacity-50"
            >
              {PRIMARY_MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={run}
            disabled={busy}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-5 py-2.5 text-sm font-bold text-surface-950 transition hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? (
              <>
                <Spinner /> Routing…
              </>
            ) : (
              <>⚡ Get Trusted Weather</>
            )}
          </button>
        </div>
      </Card>

      {!result ? (
        <Card className="flex items-center justify-center py-12 text-sm text-slate-500">
          Pick a mode and run a trusted request to see policy evaluation and fallback.
        </Card>
      ) : (
        <>
          {/* Fallback banner */}
          <div
            className={`flex flex-wrap items-center gap-3 rounded-xl border px-5 py-3.5 text-sm font-semibold ${
              result.outcome === "primary"
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                : result.outcome === "fallback"
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-300"
                  : "border-red-500/40 bg-red-500/10 text-red-300"
            }`}
          >
            <span className="text-lg">
              {result.outcome === "primary" ? "✅" : result.outcome === "fallback" ? "🔁" : "⛔"}
            </span>
            {result.outcome === "primary"
              ? "PRIMARY USED — no fallback"
              : result.outcome === "fallback"
                ? "FALLBACK USED → backup provider"
                : "UNAVAILABLE — safe degraded response"}
            <span className="ml-auto font-mono text-xs font-normal text-slate-400">
              {result.request_id} · {result.created_at}
            </span>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            {/* Left column: attempts + policy checks */}
            <div className="space-y-5">
              {primary && <AttemptCard attempt={primary} />}
              <Card>
                <h3 className="mb-2 text-sm font-semibold text-slate-300">Policy checks (primary)</h3>
                <ul className="divide-y divide-line/60">
                  {result.policy_checks.map((c) => (
                    <CheckRow key={c.id} check={c} />
                  ))}
                </ul>
              </Card>
            </div>

            {/* Right column: score + timeline */}
            <div className="space-y-5">
              <TrustScorePanel score={result.trust_score} />
              <Card>
                <h3 className="mb-3 text-sm font-semibold text-slate-300">Decision timeline</h3>
                <ol className="space-y-2.5">
                  {result.decision_timeline.map((s, i) => (
                    <li key={`${s.step}-${i}`} className="flex items-start gap-2.5">
                      <StepDot status={s.status} />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="font-mono text-xs font-semibold text-slate-200">
                            {s.step}
                          </span>
                          <span className="font-mono text-[11px] text-slate-500">
                            t+{s.t_ms} ms
                          </span>
                        </div>
                        <p
                          className={`text-xs ${
                            s.status === "fail" ? "text-red-300" : "text-slate-400"
                          }`}
                        >
                          {s.detail}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </Card>
            </div>
          </div>

          {/* Backup card */}
          {backup && <AttemptCard attempt={backup} />}

          {/* Final normalized weather */}
          <Card className={result.outcome === "degraded" ? "border-red-500/40" : ""}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-slate-300">
                Final normalized weather ({result.category})
              </h3>
              <span className="rounded-md border border-line bg-surface-800 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-slate-400">
                🧪 synthetic · local demo
              </span>
            </div>
            {result.outcome === "degraded" ? (
              <p className="mt-3 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-300">
                {result.response.decision_reason}
              </p>
            ) : (
              <div className="mt-3 grid gap-4 sm:grid-cols-4">
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-slate-500">Location</p>
                  <p className="text-lg font-semibold text-slate-100">{result.response.location}</p>
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-slate-500">Temperature</p>
                  <p className="text-lg font-semibold text-slate-100">
                    {result.response.temperature_c} °C
                  </p>
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-slate-500">Humidity</p>
                  <p className="text-lg font-semibold text-slate-100">
                    {result.response.humidity_percent} %
                  </p>
                </div>
                <div>
                  <p className="text-[11px] uppercase tracking-wider text-slate-500">Condition</p>
                  <p className="text-lg font-semibold text-slate-100">{result.response.condition}</p>
                </div>
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-400">
              <span>
                observed_at:{" "}
                <span className="font-mono">{result.response.observed_at ?? "—"}</span>
              </span>
              <span>
                source: <span className="font-mono">{result.response.source}</span>
              </span>
              <span>
                trust: <span className="font-mono">{result.response.trust_score}/100</span>
              </span>
              <span>
                fallback:{" "}
                <span className="font-mono">{String(result.response.fallback_used)}</span>
              </span>
            </div>
            <p className="mt-2 border-t border-line/60 pt-2 text-xs text-slate-500">
              {result.decision_reason}
            </p>
          </Card>
        </>
      )}
    </div>
  );
}
