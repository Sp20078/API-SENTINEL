/**
 * API types mirroring the sentinel-engine response models (Phase 2).
 * Only redacted data ever crosses this boundary.
 */

export type Severity = "critical" | "high" | "medium" | "pass";
export type CheckStatus = "fail" | "pass";
export type DemoMode = "vulnerable" | "secure";

export interface Probe {
  label: string;
  url: string;
  authorization_redacted: string | null;
  status_code: number;
  body: unknown;
}

export interface Verification {
  verified_at: string;
  observed_status: number;
  blocked: boolean;
  probes: Probe[];
}

export interface Finding {
  id: string;
  type: string;
  title: string;
  severity: Severity;
  confidence: string;
  endpoint: string;
  method: string;
  authenticated_user: string;
  authenticated_role: string;
  resource_owner: string;
  expected_status: number;
  observed_status: number;
  request: { url: string; method: string; authorization: string | null };
  response: { status_code: number; body: unknown };
  probes: Probe[];
  sensitive_fields_exposed: string[];
  impact: string;
  recommendation: string;
  status: CheckStatus;
  verification: Verification | null;
}

export interface WasNow {
  observed_status: number;
  status: CheckStatus;
}

export interface FindingVerification {
  finding_id: string;
  endpoint: string;
  resource_owner: string;
  was: WasNow;
  now: WasNow;
  verified: boolean;
  probes: Probe[];
  note: string | null;
}

export interface VerifyResponse {
  scan_id: string;
  verified_at: string;
  demo_mode: string | null;
  results: FindingVerification[];
  verified_count: number;
  all_verified: boolean;
}

export interface CheckResult {
  id: string;
  endpoint: string;
  method: string;
  authenticated_user: string;
  authenticated_role: string;
  resource_owner: string;
  expected_status: number;
  observed_status: number;
  status: CheckStatus;
  probes: Probe[];
  sensitive_fields_exposed: string[];
  impact: string;
  recommendation: string;
  regression_test: string;
}

export interface ScanSummary {
  target_base_url: string;
  demo_mode: string | null;
  discovered_endpoints: number;
  tested_endpoints: number;
  checks_run: number;
  findings: number;
  passed: number;
  failed: number;
  security_score: number;
  started_at: string;
  finished_at: string;
  duration_ms: number;
}

export interface Scan {
  id: string;
  state: "running" | "completed" | "failed";
  error: string | null;
  summary: ScanSummary | null;
  finding_ids: string[];
}

export interface Identity {
  name: string;
  id: string;
  role: "customer" | "admin";
  token: string;
}
