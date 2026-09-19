"""One-click fix verification: re-probe stored findings against the live target.

POST /scan/{scan_id}/verify uses the plan captured at scan time (base URL,
attacker/victim identities, endpoint templates + ownership maps) to replay each
finding's cross-user probe. Original ("was") evidence is captured BEFORE any
mutation; fresh ("now") probes are attached. A finding flips to `pass` only
when the fresh cross-user probe returns 401 or 403.
"""

from __future__ import annotations

import datetime as dt

import httpx

from ..models import Finding, FindingVerification, Probe, Verification, VerifyResponse, WasNow
from .bola import BLOCKED_STATUSES, ObjectEndpoint, VerifyPlan, _probe


def _unverifiable(finding: Finding, note: str) -> FindingVerification:
    return FindingVerification(
        finding_id=finding.id,
        endpoint=finding.endpoint,
        resource_owner=finding.resource_owner,
        was=WasNow(observed_status=finding.observed_status, status=finding.status),
        now=WasNow(observed_status=finding.observed_status, status=finding.status),
        verified=False,
        probes=[],
        note=note,
    )


def verify_findings(
    client: httpx.Client,
    scan_id: str,
    record_findings: dict[str, Finding],
    plan: VerifyPlan,
) -> VerifyResponse:
    """Re-probe every stored finding once; return before/after results."""
    verified_at = dt.datetime.now(dt.UTC).isoformat()
    attacker = plan.attacker
    victim = plan.victim
    by_endpoint = {ep.endpoint: ep for ep in plan.endpoints}

    results: list[FindingVerification] = []
    verified_count = 0

    for finding in record_findings.values():
        ep: ObjectEndpoint | None = by_endpoint.get(finding.endpoint)
        if ep is None:
            results.append(
                _unverifiable(finding, "endpoint no longer known; re-run a full scan")
            )
            continue

        try:
            cross_id = victim.id if ep.owner_kind == "user" else ep.resource_for(victim.id)
        except KeyError:
            results.append(
                _unverifiable(finding, "victim resource mapping missing; re-run a full scan")
            )
            continue

        # Capture the BEFORE snapshot strictly before mutating the finding.
        was = WasNow(observed_status=finding.observed_status, status=finding.status)

        url_path = ep.path_template.replace("{" + ep.owner_param + "}", cross_id)
        fresh_cross: Probe = _probe(
            client, plan.base_url, url_path, attacker.token, "cross_user"
        )
        blocked = fresh_cross.status_code in BLOCKED_STATUSES

        finding.verification = Verification(
            verified_at=verified_at,
            observed_status=fresh_cross.status_code,
            blocked=blocked,
            probes=[fresh_cross],
        )
        if blocked:
            finding.status = "pass"
            finding.observed_status = fresh_cross.status_code
            verified_count += 1

        results.append(
            FindingVerification(
                finding_id=finding.id,
                endpoint=finding.endpoint,
                resource_owner=finding.resource_owner,
                was=was,
                now=WasNow(
                    observed_status=fresh_cross.status_code,
                    status="pass" if blocked else "fail",
                ),
                verified=blocked,
                probes=[fresh_cross],
                note=None if blocked else "still returns a 200 body for another customer's resource",
            )
        )

    return VerifyResponse(
        scan_id=scan_id,
        verified_at=verified_at,
        demo_mode=None,  # filled in by the API layer (target /health)
        results=results,
        verified_count=verified_count,
        all_verified=bool(results) and verified_count == len(results),
    )
