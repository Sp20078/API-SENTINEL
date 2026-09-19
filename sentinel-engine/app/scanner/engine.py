"""Scan orchestration: the full deterministic pipeline.

validate target -> fetch OpenAPI -> discover GET endpoints -> map object
endpoints -> probe (own baseline + cross-user) -> findings / passed checks ->
summary with security score. Token values exist only inside this module and
are redacted before anything is stored.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import httpx

from ..models import Identity, Scan, ScanSummary
from ..openapi_client import EndpointInfo, discover_get_endpoints, fetch_openapi
from ..store import ScanRecord, next_id
from ..target_guard import validate_scan_target
from .bola import IdentityView, ObjectEndpoint, build_object_endpoints, check_endpoint, make_check, make_finding

# MVP mutation mappings (spec): resource kind -> {resource_id: owner user_id}
DEFAULT_RESOURCE_OWNERSHIP: dict[str, dict[str, str]] = {
    "order": {
        "order-1001": "user-101",
        "order-1002": "user-102",
    },
    "user": {
        "user-101": "user-101",
        "user-102": "user-102",
    },
}


@dataclass(frozen=True)
class EngineConfig:
    request_timeout: float = 10.0


def _identity_view(identity: Identity) -> IdentityView:
    return IdentityView(name=identity.name, id=identity.id, role=identity.role, token=identity.token)


def _fetch_demo_mode(client: httpx.Client, base_url: str) -> str | None:
    """Best-effort read of the target's demo mode from /health; None if absent."""
    try:
        resp = client.get(f"{base_url}/health")
        if resp.status_code == 200:
            mode = resp.json().get("mode")
            return mode if isinstance(mode, str) else None
    except (httpx.HTTPError, ValueError):
        pass
    return None


def _score(findings_count: int, failed_checks: int, checks: int) -> int:
    """100 = nothing exposed; each failing check costs 30, floor 0."""
    if checks == 0:
        return 100
    penalties = 30 * findings_count + 30 * failed_checks
    return max(0, 100 - penalties)


def run_scan(request_identities: list[Identity], target_base_url: str, openapi_url: str,
             config: EngineConfig | None = None) -> tuple[ScanRecord, Scan]:
    """Execute a full scan synchronously; returns the populated record and final Scan."""
    config = config or EngineConfig()
    base_url, contract_url = validate_scan_target(target_base_url, openapi_url)

    started = dt.datetime.now(dt.UTC)
    scan_id = next_id("scan")
    record = store_create(scan_id)

    attacker_view = _identity_view(request_identities[0])
    victim_view = _identity_view(request_identities[1])

    scan = record.scan
    try:
        with httpx.Client(timeout=config.request_timeout) as client:
            demo_mode = _fetch_demo_mode(client, base_url)
            contract = fetch_openapi(client, contract_url)
            endpoints: list[EndpointInfo] = discover_get_endpoints(contract)
            object_endpoints = build_object_endpoints(endpoints, DEFAULT_RESOURCE_OWNERSHIP)

            findings_count = 0
            passed_count = 0
            for ep in object_endpoints:
                verdict = check_endpoint(client, base_url, ep, attacker_view, victim_view)
                if verdict.status == "fail":
                    finding = make_finding(
                        next_id("BOLA"), ep, attacker_view, victim_view, verdict
                    )
                    record.findings[finding.id] = finding
                    scan.finding_ids.append(finding.id)
                    findings_count += 1
                elif verdict.status == "pass":
                    check = make_check(
                        next_id("CHK"), ep, attacker_view, victim_view, verdict
                    )
                    record.checks[check.id] = check
                    passed_count += 1
                # "skipped" verdicts make no claim and are not stored as findings.

        finished = dt.datetime.now(dt.UTC)
        scan.summary = ScanSummary(
            target_base_url=base_url,
            demo_mode=demo_mode,
            discovered_endpoints=len(endpoints),
            tested_endpoints=len(object_endpoints),
            checks_run=findings_count + passed_count,
            findings=findings_count,
            passed=passed_count,
            failed=findings_count,
            security_score=_score(findings_count, 0, findings_count + passed_count),
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_ms=int((finished - started).total_seconds() * 1000),
        )
        scan.state = "completed"
    except Exception as exc:  # noqa: BLE001 — scan failures are surfaced via API, not crashed
        scan.state = "failed"
        scan.error = f"{type(exc).__name__}: {exc}"
    return record, scan


def store_create(scan_id: str) -> ScanRecord:
    from ..store import store

    return store.create(scan_id)
