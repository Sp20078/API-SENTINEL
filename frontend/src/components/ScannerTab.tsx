import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, DEMO_BASE, api } from "../api/client";
import type { CheckResult, DemoMode, Finding, Scan } from "../api/types";
import { FindingsList } from "./FindingsList";
import { SCAN_STEPS, ScanProgress } from "./ScanProgress";
import { SummaryCards } from "./SummaryCards";
import { Card, ModeBadge, Spinner, StatusDot } from "./ui";

// Relocated verbatim from the original App.tsx: the Authorization Sentinel
// (BOLA scanner) dashboard is now tab 1 of the two-module UI.

export const DEMO_IDENTITIES = [
  { name: "Alice", id: "user-101", role: "customer", token: "alice-token" },
  { name: "Bob", id: "user-102", role: "customer", token: "bob-token" },
  { name: "Priya", id: "admin-001", role: "admin", token: "admin-token" },
];

export default function ScannerTab() {
  const [engineUp, setEngineUp] = useState<boolean | null>(null);
  const [demoUp, setDemoUp] = useState<boolean | null>(null);
  const [mode, setMode] = useState<DemoMode | null>(null);
  const [scanning, setScanning] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [steps, setSteps] = useState<string[]>([]);
  const [scan, setScan] = useState<Scan | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [checks, setChecks] = useState<CheckResult[]>([]);
  const [selected, setSelected] = useState<Finding | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const stepTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const lastScanAt = scan?.summary
    ? new Date(scan.summary.finished_at).toLocaleTimeString()
    : null;

  const clearStepTimers = useCallback(() => {
    stepTimers.current.forEach(clearTimeout);
    stepTimers.current = [];
  }, []);

  const refreshHealth = useCallback(async () => {
    const [e, d] = await Promise.allSettled([api.engineHealth(), api.demoHealth()]);
    setEngineUp(e.status === "fulfilled");
    setDemoUp(d.status === "fulfilled");
    if (d.status === "fulfilled") setMode(d.value.mode);
  }, []);

  useEffect(() => {
    refreshHealth();
    const t = setInterval(refreshHealth, 5000);
    return () => clearInterval(t);
  }, [refreshHealth]);

  useEffect(() => () => clearStepTimers(), [clearStepTimers]);

  const runScan = useCallback(async () => {
    setError(null);
    setNotice(null);
    setSelected(null);
    setScanning(true);
    setSteps([]);
    clearStepTimers();
    SCAN_STEPS.forEach((step, i) => {
      stepTimers.current.push(setTimeout(() => setSteps((prev) => [...prev, step]), 150 + i * 130));
    });

    try {
      const result = await api.runScan(DEMO_IDENTITIES);
      await new Promise((r) => setTimeout(r, Math.max(0, 150 + SCAN_STEPS.length * 130 - 100)));
      if (result.state === "failed") {
        throw new ApiError(result.error ?? "Scan failed", null);
      }
      const [fs, cs] = await Promise.all([api.getFindings(result.id), api.getChecks(result.id)]);
      setScan(result);
      setFindings(fs);
      setChecks(cs);
      if (fs.length === 0) {
        setNotice("Scan complete — no authorization failures found. Nice.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unexpected error");
    } finally {
      clearStepTimers();
      setScanning(false);
    }
  }, [clearStepTimers]);

  const switchMode = useCallback(
    async (next: DemoMode) => {
      setError(null);
      setSwitching(true);
      try {
        await api.setDemoMode(next);
        setMode(next);
        setNotice(
          next === "secure"
            ? "Demo API switched to SECURE — run Verify Fix on an earlier scan to see the fix."
            : "Demo API switched to VULNERABLE — run a scan to reproduce the BOLA leak.",
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : "Unexpected error");
      } finally {
        setSwitching(false);
      }
    },
    [],
  );

  const engineReady = engineUp === true;
  const targetReady = demoUp === true;
  const canScan = engineReady && targetReady && !scanning;

  return (
    <div className="space-y-5">
        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            <span>⚠</span>
            <div>
              <span className="font-semibold">Error: </span>
              {error}
            </div>
          </div>
        )}
        {notice && (
          <div className="rounded-lg border border-accent/30 bg-accent/10 px-4 py-3 text-sm text-sky-200">
            {notice}
          </div>
        )}

        {/* Scan configuration */}
        <Card>
          <div className="grid gap-5 lg:grid-cols-[1fr_auto]">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-300">Scan configuration</h2>
                <ModeBadge mode={mode} />
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  <span className="flex items-center gap-1.5">
                    <StatusDot ok={engineUp} /> scanner :8000
                  </span>
                  <span className="flex items-center gap-1.5">
                    <StatusDot ok={demoUp} /> target :8001
                  </span>
                </div>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-[11px] uppercase tracking-wider text-slate-500">
                    Target URL (local only)
                  </span>
                  <input
                    readOnly
                    value={DEMO_BASE}
                    className="w-full cursor-not-allowed rounded-lg border border-line bg-surface-950 px-3 py-2 font-mono text-[13px] text-slate-400"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-[11px] uppercase tracking-wider text-slate-500">
                    OpenAPI URL (local only)
                  </span>
                  <input
                    readOnly
                    value={`${DEMO_BASE}/openapi.json`}
                    className="w-full cursor-not-allowed rounded-lg border border-line bg-surface-950 px-3 py-2 font-mono text-[13px] text-slate-400"
                  />
                </label>
              </div>
              <div>
                <span className="mb-1.5 block text-[11px] uppercase tracking-wider text-slate-500">
                  Identities
                </span>
                <div className="flex flex-wrap gap-2">
                  {DEMO_IDENTITIES.map((i) => (
                    <span
                      key={i.id}
                      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
                        i.role === "admin"
                          ? "border-violet-500/40 bg-violet-500/10 text-violet-300"
                          : "border-sky-500/40 bg-sky-500/10 text-sky-300"
                      }`}
                    >
                      {i.name}
                      <span className="text-slate-500">·</span>
                      <span className="text-slate-400">{i.role}</span>
                    </span>
                  ))}
                  <span className="self-center text-[11px] text-slate-600">
                    tokens redacted everywhere
                  </span>
                </div>
              </div>
            </div>
            <div className="flex flex-col justify-center gap-2 lg:w-56">
              <button
                onClick={runScan}
                disabled={!canScan}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-bold text-surface-950 transition hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-40"
              >
                {scanning ? (
                  <>
                    <Spinner /> Scanning…
                  </>
                ) : (
                  <>▶ Run Authorization Scan</>
                )}
              </button>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => switchMode("vulnerable")}
                  disabled={!targetReady || switching || mode === "vulnerable"}
                  className="rounded-lg border border-red-500/40 bg-red-500/10 px-2 py-2 text-xs font-semibold text-red-300 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Vulnerable
                </button>
                <button
                  onClick={() => switchMode("secure")}
                  disabled={!targetReady || switching || mode === "secure"}
                  className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-2 py-2 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Secure
                </button>
              </div>
              <p className="text-center text-[11px] text-slate-600">
                Switch demo API mode, then re-scan
              </p>
            </div>
          </div>
        </Card>

        {/* Progress + Summary */}
        <div className="grid gap-5 lg:grid-cols-[340px_1fr]">
          <ScanProgress steps={steps} scanning={scanning} hasScan={!!scan} />
          <div className="space-y-4">
            {scan?.summary ? (
              <SummaryCards
                summary={scan.summary}
                findings={findings}
                lastScanAt={lastScanAt}
              />
            ) : (
              <Card className="flex h-full items-center justify-center py-10 text-sm text-slate-500">
                Run a scan to see the security summary.
              </Card>
            )}
          </div>
        </div>

        {/* Findings */}
        <FindingsList
          findings={findings}
          checks={checks}
          selectedId={selected?.id ?? null}
          onSelect={setSelected}
        />

    </div>
  );
}
