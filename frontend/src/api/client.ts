/**
 * API client for the scanner engine (:8000) and the demo target API (:8001).
 * The engine redacts tokens before anything is returned; this client adds no
 * credentials of its own.
 */
import type { CheckResult, Finding, Scan, ScanSummary, VerifyResponse } from "./types";

export const ENGINE_BASE =
  typeof import.meta !== "undefined" && import.meta.env?.VITE_ENGINE_URL
    ? String(import.meta.env.VITE_ENGINE_URL)
    : "http://127.0.0.1:8000";
export const DEMO_BASE =
  typeof import.meta !== "undefined" && import.meta.env?.VITE_DEMO_URL
    ? String(import.meta.env.VITE_DEMO_URL)
    : "http://127.0.0.1:8001";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(url: string): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url);
  } catch {
    throw new ApiError(`Cannot reach ${url} — is the service running?`);
  }
  if (!resp.ok) {
    const detail = await safeDetail(resp);
    throw new ApiError(detail ?? `${resp.status} ${resp.statusText}`, resp.status);
  }
  return (await resp.json()) as T;
}

async function postJson<T>(url: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(`Cannot reach ${url} — is the service running?`);
  }
  if (!resp.ok) {
    const detail = await safeDetail(resp);
    throw new ApiError(detail ?? `${resp.status} ${resp.statusText}`, resp.status);
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

export interface DemoHealth {
  status: string;
  service: string;
  mode: "vulnerable" | "secure";
}

export const api = {
  engineHealth: () => getJson<{ status: string; service: string }>(`${ENGINE_BASE}/health`),

  demoHealth: () => getJson<DemoHealth>(`${DEMO_BASE}/health`),

  setDemoMode: (mode: "vulnerable" | "secure") =>
    postJson<{ mode: string }>(`${DEMO_BASE}/admin/mode`, { mode }),

  runScan: (identities: Array<{ name: string; id: string; role: string; token: string }>) =>
    postJson<Scan>(`${ENGINE_BASE}/scan`, {
      target_base_url: DEMO_BASE,
      openapi_url: `${DEMO_BASE}/openapi.json`,
      identities,
    }),

  getFindings: (scanId: string) =>
    getJson<Finding[]>(`${ENGINE_BASE}/scan/${scanId}/findings`),

  getFinding: (scanId: string, findingId: string) =>
    getJson<Finding>(`${ENGINE_BASE}/scan/${scanId}/findings/${findingId}`),

  getFindingTest: async (scanId: string, findingId: string): Promise<string> => {
    let resp: Response;
    try {
      resp = await fetch(`${ENGINE_BASE}/scan/${scanId}/findings/${findingId}/test`);
    } catch {
      throw new ApiError(`Cannot reach regression-test endpoint`);
    }
    if (!resp.ok) throw new ApiError(`Test endpoint returned ${resp.status}`, resp.status);
    return resp.text();
  },

  getChecks: (scanId: string) => getJson<CheckResult[]>(`${ENGINE_BASE}/scan/${scanId}/checks`),

  getSummary: (scanId: string) => getJson<ScanSummary>(`${ENGINE_BASE}/scan/${scanId}/summary`),

  verifyFix: (scanId: string) => postJson<VerifyResponse>(`${ENGINE_BASE}/scan/${scanId}/verify`),
};
