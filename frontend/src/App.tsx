import { useState } from "react";
import ScannerTab from "./components/ScannerTab";
import TrustRouterTab from "./components/TrustRouterTab";

type TabId = "scanner" | "trust-router";

const TABS: Array<{ id: TabId; label: string; icon: string }> = [
  { id: "scanner", label: "Authorization Sentinel", icon: "🛡️" },
  { id: "trust-router", label: "Trust Router", icon: "🧭" },
];

export default function App() {
  const [tab, setTab] = useState<TabId>("scanner");

  return (
    <div className="min-h-full">
      <header className="border-b border-line bg-surface-900/70 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-accent/40 bg-accent/10">
              <span className="text-lg">🛡️</span>
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight text-slate-100">API Sentinel</h1>
              <p className="text-xs text-slate-400">Evidence-Based API Security · Local-First</p>
            </div>
          </div>
          <nav className="ml-6 flex items-center gap-1 rounded-lg border border-line bg-surface-850 p-1">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition ${
                  tab === t.id
                    ? "bg-accent/15 text-accent"
                    : "text-slate-400 hover:bg-surface-800 hover:text-slate-200"
                }`}
              >
                <span>{t.icon}</span>
                {t.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-800 px-2.5 py-1 text-[11px] font-semibold tracking-wide text-slate-400">
              🌐 live-by-default · keyless upstreams · synthetic fallback
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        {tab === "scanner" ? <ScannerTab /> : <TrustRouterTab />}
      </main>

      <footer className="pb-4 text-center text-[11px] text-slate-600">
        API Sentinel Mesh · educational tool · 100% local services · live provider data (Open-Meteo,
        Frankfurter) with synthetic fallback
      </footer>
    </div>
  );
}
