import { Spinner } from "./ui";

const STEP_HINT = "Initializing scan…";

export function ScanProgress({
  steps,
  scanning,
  hasScan,
}: {
  steps: string[];
  scanning: boolean;
  hasScan: boolean;
}) {
  return (
    <div className="rounded-xl border border-line bg-surface-900 p-5">
      <div className="mb-3 flex items-center gap-2">
        <h3 className="text-sm font-semibold text-slate-300">Scan progress</h3>
        {scanning && <Spinner />}
      </div>
      {steps.length === 0 && !scanning && (
        <p className="text-sm text-slate-500">
          {hasScan ? "Previous scan complete." : STEP_HINT + " Press “Run Authorization Scan”."}
        </p>
      )}
      <ol className="space-y-2">
        {steps.map((step, i) => {
          const isLast = i === steps.length - 1;
          const active = scanning && isLast;
          return (
            <li key={step} className="flex items-center gap-2.5 text-sm">
              {active ? (
                <Spinner className="h-3.5 w-3.5" />
              ) : (
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-500/15 text-[10px] text-emerald-300">
                  ✓
                </span>
              )}
              <span className={active ? "text-slate-300" : "text-slate-400"}>{step}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export const SCAN_STEPS = [
  "Loaded OpenAPI contract",
  "Discovered endpoints",
  "Authenticated as Alice",
  "Tested Alice's owned resource",
  "Mutated resource identifier",
  "Tested cross-user access",
  "Recorded findings / security checks",
  "Generated regression tests",
];
