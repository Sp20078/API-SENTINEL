/**
 * API client + types for the Trust Router (API Sentinel Mesh).
 * Mirrors sentinel-engine/app/trust_router/models.py.
 */

import { ENGINE_BASE } from "./client";

export type Outcome = "primary" | "fallback" | "degraded";
export type ScoreBand = "trusted" | "acceptable" | "untrusted";

export interface PolicyCheck {
  id: string;
  label: string;
  status: "pass" | "fail";
  detail: string;
}

export interface TrustScoreComponent {
  id: string;
  earned: number;
  max: number;
  detail: string;
}

export interface TrustScore {
  total: number;
  band: ScoreBand;
  hard_gates_passed: boolean;
  failed_gates: string[];
  components: TrustScoreComponent[];
}

export interface DecisionStep {
  t_ms: number;
  step: string;
  status: "info" | "ok" | "fail";
  detail: string;
  at: string;
}

export interface ProviderAttempt {
  role: "primary" | "backup";
  provider: string;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
  schema_valid: boolean | null;
  schema_errors: string[];
  raw_fields: string[];
  raw_fields_redacted: string[];
  trust_score: TrustScore | null;
}

export interface WeatherResponse {
  category?: string;
  location: string | null;
  temperature_c: number | null;
  humidity_percent: number | null;
  condition: string | null;
  observed_at: string | null;
  source: string;
  fallback_used: boolean;
  trust_score: number;
  decision_reason: string;
  metrics?: Record<string, number | string>;
}

export type WeatherResponseOrCanonical = WeatherResponse & {
  category: string;
};

export interface TrustRouterResult {
  request_id: string;
  created_at: string;
  category: string;
  city: string;
  primary_mode: string | null;
  outcome: Outcome;
  fallback_used: boolean;
  decision_reason: string;
  policy_checks: PolicyCheck[];
  trust_score: TrustScore;
  attempts: ProviderAttempt[];
  decision_timeline: DecisionStep[];
  response: WeatherResponse;
}

export interface CategoryCatalogEntry {
  category: string;
  label: string;
  input_hint: string;
  default_location: string;
  primary: ProviderInfo;
  backup: ProviderInfo;
}

export interface ProviderInfo {
  role: "primary" | "backup";
  id: string;
  url: string;
  description: string;
  modes: string[] | null;
}

export interface ProvidersCatalog {
  categories: CategoryCatalogEntry[];
}

export type TrustCategory = "weather" | "fx";

export const TRUST_CITIES = [
  "Bengaluru",
  "London",
  "New York",
  "Singapore",
  "Tokyo",
  "Sydney",
];

export const TRUST_PAIRS = ["USD/INR", "USD/EUR", "USD/GBP", "USD/JPY", "EUR/USD", "GBP/USD"];

export const DEFAULT_MODES = [
  "healthy",
  "slow_response",
  "http_503",
  "malformed_schema",
  "stale_data",
];

async function postJson<T>(url: string, body: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error(`Cannot reach ${url} — is the scanner engine running?`);
  }
  if (!resp.ok) {
    const detail = await safeDetail(resp);
    throw new Error(detail ?? `${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as T;
}

async function getJson<T>(url: string): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url);
  } catch {
    throw new Error(`Cannot reach ${url} — is the scanner engine running?`);
  }
  if (!resp.ok) {
    const detail = await safeDetail(resp);
    throw new Error(detail ?? `${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as T;
}

async function safeDetail(resp: Response): Promise<string | null> {
  try {
    const data = (await resp.json()) as { detail?: unknown };
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    /* non-JSON error body */
  }
  return null;
}

export const trustApi = {
  getProviders: () => getJson<ProvidersCatalog>(`${ENGINE_BASE}/trust-router/providers`),

  request: (location: string, category: TrustCategory) =>
    postJson<TrustRouterResult>(`${ENGINE_BASE}/trust-router/request`, {
      location,
      category,
    }),

  setPrimaryMode: (mode: string, category: TrustCategory) =>
    postJson<{ mode: string; category: string; message: string | null }>(
      `${ENGINE_BASE}/trust-router/primary-mode`,
      { mode, category },
    ),
};
