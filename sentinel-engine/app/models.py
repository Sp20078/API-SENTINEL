"""Pydantic models for the API Sentinel scanner engine.

Shapes mirror the hackathon spec: scan requests, findings with full evidence
(two baseline probes + one cross-user probe), scan summaries, and pass/fail
checks. Token values are never stored on models; callers pass redacted strings.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "pass"]
CheckStatus = Literal["fail", "pass"]


class Identity(BaseModel):
    name: str
    id: str
    role: Literal["customer", "admin"]
    token: str  # request-side only; never echoed back by the engine


class ScanRequest(BaseModel):
    target_base_url: str = "http://127.0.0.1:8001"
    openapi_url: str = "http://127.0.0.1:8001/openapi.json"
    identities: list[Identity] = Field(min_length=2)


class EvidenceRequest(BaseModel):
    """A captured HTTP request. `authorization` is already redacted by the scanner."""

    url: str
    method: str = "GET"
    authorization: str | None = None  # e.g. "Bearer alic...oken"


class EvidenceResponse(BaseModel):
    status_code: int
    body: dict[str, Any] | list[Any] | None


class Probe(BaseModel):
    """One request/response exchange recorded as evidence."""

    label: str  # e.g. "own_resource", "cross_user"
    url: str
    authorization_redacted: str | None
    status_code: int
    body: dict[str, Any] | list[Any] | None


class Verification(BaseModel):
    """Fresh re-probe evidence recorded by POST /scan/{scan_id}/verify."""

    verified_at: str
    observed_status: int  # fresh cross-user status
    blocked: bool  # True when the fresh cross-user probe returned 401/403
    probes: list[Probe]


class Finding(BaseModel):
    id: str
    type: str = "Broken Object-Level Authorization"
    title: str
    severity: Severity
    confidence: str = "high"
    endpoint: str  # "METHOD /path/{param}"
    method: str
    authenticated_user: str
    authenticated_role: str
    resource_owner: str
    expected_status: int
    observed_status: int
    request: EvidenceRequest
    response: EvidenceResponse
    probes: list[Probe]
    sensitive_fields_exposed: list[str]
    impact: str
    recommendation: str
    status: CheckStatus
    verification: Verification | None = None


class ScanSummary(BaseModel):
    target_base_url: str
    demo_mode: str | None  # None if the target does not expose /health with a mode
    discovered_endpoints: int
    tested_endpoints: int
    checks_run: int
    findings: int
    passed: int
    failed: int
    security_score: int
    started_at: str
    finished_at: str
    duration_ms: int


class Scan(BaseModel):
    id: str
    state: Literal["running", "completed", "failed"]
    error: str | None = None
    summary: ScanSummary | None = None
    finding_ids: list[str] = []


class CheckResult(BaseModel):
    """A pass/fail authorization check (a 'passed security check' record)."""

    id: str
    endpoint: str
    method: str
    authenticated_user: str
    authenticated_role: str
    resource_owner: str
    expected_status: int
    observed_status: int
    status: CheckStatus
    probes: list[Probe]
    sensitive_fields_exposed: list[str]
    impact: str
    recommendation: str
    regression_test: str


class WasNow(BaseModel):
    """Before/after snapshot for one finding during verification."""

    observed_status: int
    status: CheckStatus


class FindingVerification(BaseModel):
    finding_id: str
    endpoint: str
    resource_owner: str
    was: WasNow
    now: WasNow
    verified: bool
    probes: list[Probe]  # fresh probe evidence (redacted)
    note: str | None = None


class VerifyResponse(BaseModel):
    scan_id: str
    verified_at: str
    demo_mode: str | None
    results: list[FindingVerification]
    verified_count: int
    all_verified: bool
