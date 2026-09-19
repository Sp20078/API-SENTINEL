"""FastAPI app for the API Sentinel scanner engine.

Endpoints (MVP spec):
  GET  /health
  POST /scan
  GET  /scan/{scan_id}
  GET  /scan/{scan_id}/findings
  GET  /scan/{scan_id}/findings/{finding_id}
  GET  /scan/{scan_id}/findings/{finding_id}/test   (generated pytest text)
  GET  /scan/{scan_id}/checks                       (passed security checks)
  GET  /scan/{scan_id}/summary

Non-local targets are rejected with 422 before any request is made.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .models import CheckResult, Finding, Scan, ScanRequest, ScanSummary, VerifyResponse
from .scanner.engine import EngineConfig, run_scan
from .scanner.regression import generate_regression_test
from .scanner.verify import verify_findings
from .store import store
from .target_guard import UnsafeTargetError

app = FastAPI(
    title="API Sentinel Engine",
    description=(
        "Deterministic, evidence-based BOLA/IDOR scanning for local demo APIs. "
        "Only local targets (localhost/127.0.0.1/private LAN/project Docker hosts) are accepted."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api-sentinel-engine", "scanner": "ready"}


@app.post("/scan", response_model=Scan, status_code=status.HTTP_201_CREATED, tags=["scan"])
def create_scan(body: ScanRequest) -> Scan:
    try:
        _, scan = run_scan(body.identities, body.target_base_url, body.openapi_url)
    except UnsafeTargetError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return scan


def _record_or_404(scan_id: str):
    record = store.get(scan_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found")
    return record


@app.get("/scan/{scan_id}", response_model=Scan, tags=["scan"])
def get_scan(scan_id: str) -> Scan:
    return _record_or_404(scan_id).scan


@app.get("/scan/{scan_id}/findings", response_model=list[Finding], tags=["findings"])
def list_findings(scan_id: str) -> list[Finding]:
    record = _record_or_404(scan_id)
    return [record.findings[fid] for fid in record.scan.finding_ids]


@app.get("/scan/{scan_id}/findings/{finding_id}", response_model=Finding, tags=["findings"])
def get_finding(scan_id: str, finding_id: str) -> Finding:
    record = _record_or_404(scan_id)
    finding = record.findings.get(finding_id)
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding {finding_id} not found in scan {scan_id}",
        )
    return finding


@app.get(
    "/scan/{scan_id}/findings/{finding_id}/test",
    response_class=PlainTextResponse,
    tags=["findings"],
)
def get_finding_test(scan_id: str, finding_id: str) -> str:
    record = _record_or_404(scan_id)
    finding = record.findings.get(finding_id)
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Finding {finding_id} not found in scan {scan_id}",
        )
    return generate_regression_test(finding)


@app.get("/scan/{scan_id}/checks", response_model=list[CheckResult], tags=["scan"])
def list_checks(scan_id: str) -> list[CheckResult]:
    """Passed security checks (used by the dashboard's Verify Fix flow)."""
    record = _record_or_404(scan_id)
    return list(record.checks.values())


@app.get("/scan/{scan_id}/summary", response_model=ScanSummary, tags=["scan"])
def get_summary(scan_id: str) -> ScanSummary:
    scan = _record_or_404(scan_id).scan
    if scan.summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan {scan_id} has no summary (state={scan.state})",
        )
    return scan.summary


@app.post("/scan/{scan_id}/verify", response_model=VerifyResponse, tags=["scan"])
def verify_scan(scan_id: str) -> VerifyResponse:
    """One-click Verify Fix: re-probe each stored finding against the live target.

    409 if the scan never completed, 404 for unknown scans/findings-mappings,
    502 if the target is unreachable this time around.
    """
    record = _record_or_404(scan_id)
    if record.scan.state != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Scan {scan_id} is not completed (state={record.scan.state})",
        )
    if not record.findings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scan {scan_id} has no findings to verify",
        )
    if record.verify_plan is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Scan {scan_id} has no verify plan",
        )

    config = EngineConfig()
    try:
        with httpx.Client(timeout=config.request_timeout) as client:
            response = verify_findings(client, scan_id, record.findings, record.verify_plan)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Target unreachable during verification: {exc}",
        )

    # Best-effort: capture the target's current demo mode for the UI badge.
    try:
        with httpx.Client(timeout=config.request_timeout) as client:
            health = client.get(f"{record.verify_plan.base_url}/health")
            if health.status_code == 200:
                mode = health.json().get("mode")
                response.demo_mode = mode if isinstance(mode, str) else None
    except (httpx.HTTPError, ValueError):
        response.demo_mode = None
    return response
