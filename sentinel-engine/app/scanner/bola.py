"""Deterministic Broken Object-Level Authorization (BOLA/IDOR) detector.

Per supported object endpoint:
  1. Probe A — attacker's own resource with the attacker's token (baseline).
  2. Probe B — another customer's resource, same token (ID mutated).
  3. Decision:
       - A == 200 and B in {401, 403}  -> PASS  (authorization works)
       - A == 200 and B == 200         -> FAIL  -> BOLA finding
         (severity: critical if deterministic sensitive fields leaked, else medium)
       - anything else                 -> SKIPPED (inconclusive, no claim made)
Private-data exposure is decided by the deterministic sensitive-field list.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..models import CheckResult, EvidenceRequest, EvidenceResponse, Finding, Probe
from .redact import redact_authorization
from .regression import TestInputs, render_test
from .sensitive import find_sensitive_fields

BLOCKED_STATUSES = {401, 403}


def build_object_endpoints(
    endpoints: list,  # list[openapi_client.EndpointInfo]
    resource_ownership: dict[str, dict[str, str]],
) -> list[ObjectEndpoint]:
    """Map discovered GET endpoints with a single owner-ish path param to testable
    ObjectEndpoints, pairing each with its resource-ownership map from the MVP
    mutation mappings."""
    kind_by_param = {"order_id": "order", "user_id": "user"}
    out: list[ObjectEndpoint] = []
    for ep in endpoints:
        if len(ep.path_params) != 1:
            continue  # MVP: single-object endpoints only
        param = ep.path_params[0]
        kind = kind_by_param.get(param)
        if kind is None or kind not in resource_ownership:
            continue
        out.append(
            ObjectEndpoint(
                endpoint=f"GET {ep.path}",
                method=ep.method,
                path_template=ep.path,
                owner_param=param,
                owner_kind=kind,
                owner_list=resource_ownership[kind],
            )
        )
    return out

_IMPACT = {
    "order": "A customer can retrieve another customer's private order data.",
    "user": "A customer can retrieve another customer's private profile data.",
}
_RECOMMEND = {
    "order": (
        "Verify ownership of the requested resource before returning it. Allow access only "
        "when order.user_id equals current_user.id, unless the user has an authorized admin role."
    ),
    "user": (
        "Verify ownership of the requested resource before returning it. Allow access only "
        "when user.id equals current_user.id, unless the user has an authorized admin role."
    ),
}
_TITLES = {
    "order": "Customer accessed another customer's private order",
    "user": "Customer accessed another customer's private profile",
}


@dataclass(frozen=True)
class IdentityView:
    """The fields the detector needs from an identity (token is request-side only)."""

    name: str
    id: str
    role: str
    token: str


@dataclass(frozen=True)
class ObjectEndpoint:
    """A discovered object endpoint plus the ownership map needed to probe it."""

    endpoint: str  # "GET /api/orders/{order_id}"
    method: str  # "GET"
    path_template: str  # "/api/orders/{order_id}"
    owner_param: str  # "order_id"
    owner_kind: str  # "order" | "user"
    owner_list: dict[str, str]  # resource_id -> owner user id

    def resource_for(self, user_id: str) -> str:
        for resource_id, owner_id in self.owner_list.items():
            if owner_id == user_id:
                return resource_id
        raise KeyError(f"no known resource owned by {user_id!r} for {self.endpoint}")


@dataclass(frozen=True)
class Verdict:
    status: str  # "fail" | "pass" | "skipped"
    observed_status: int
    expected_status: int
    sensitive_fields: list[str]
    probes: list[Probe]
    regression_test: str
    test_inputs: TestInputs | None


def _probe(
    client: httpx.Client, base_url: str, url_path: str, token: str, label: str
) -> Probe:
    resp = client.get(
        f"{base_url}{url_path}", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        body = resp.json()
    except ValueError:
        body = None
    return Probe(
        label=label,
        url=f"{base_url}{url_path}",
        authorization_redacted=redact_authorization(f"Bearer {token}"),
        status_code=resp.status_code,
        body=body if isinstance(body, (dict, list)) else None,
    )


def _verdict_inputs(ep: ObjectEndpoint, attacker: IdentityView, cross: Probe) -> TestInputs:
    return TestInputs(
        authenticated_user=attacker.name,
        authenticated_role=attacker.role,
        resource_param=ep.owner_param,
        request_url=cross.url,
        authorization=cross.authorization_redacted,
    )


def check_endpoint(
    client: httpx.Client,
    base_url: str,
    ep: ObjectEndpoint,
    attacker: IdentityView,
    victim: IdentityView,
) -> Verdict:
    """Run the two-probe deterministic BOLA check for one endpoint."""
    try:
        own_id = (
            attacker.id
            if ep.owner_kind == "user"
            else ep.resource_for(attacker.id)
        )
        cross_id = (
            victim.id
            if ep.owner_kind == "user"
            else ep.resource_for(victim.id)
        )
    except KeyError:
        # No known resource for one of the identities: cannot test meaningfully.
        return Verdict(
            status="skipped",
            observed_status=0,
            expected_status=403,
            sensitive_fields=[],
            probes=[],
            regression_test="",
            test_inputs=None,
        )

    own_probe = _probe(
        client, base_url, _fill(ep.path_template, ep.owner_param, own_id),
        attacker.token, "own_resource",
    )
    cross_probe = _probe(
        client, base_url, _fill(ep.path_template, ep.owner_param, cross_id),
        attacker.token, "cross_user",
    )
    probes = [own_probe, cross_probe]
    test_inputs = _verdict_inputs(ep, attacker, cross_probe)

    if own_probe.status_code == 200 and cross_probe.status_code in BLOCKED_STATUSES:
        return Verdict(
            status="pass",
            observed_status=cross_probe.status_code,
            expected_status=403,
            sensitive_fields=[],
            probes=probes,
            regression_test=render_test(test_inputs),
            test_inputs=test_inputs,
        )
    if own_probe.status_code == 200 and cross_probe.status_code == 200:
        sensitive = find_sensitive_fields(cross_probe.body)
        return Verdict(
            status="fail",
            observed_status=cross_probe.status_code,
            expected_status=403,
            sensitive_fields=sensitive,
            probes=probes,
            regression_test=render_test(test_inputs),
            test_inputs=test_inputs,
        )
    return Verdict(
        status="skipped",
        observed_status=cross_probe.status_code,
        expected_status=403,
        sensitive_fields=[],
        probes=probes,
        regression_test="",
        test_inputs=None,
    )


def _fill(template: str, param: str, value: str) -> str:
    return template.replace("{" + param + "}", value)


def make_finding(
    finding_id: str,
    ep: ObjectEndpoint,
    attacker: IdentityView,
    victim: IdentityView,
    verdict: Verdict,
) -> Finding:
    cross = verdict.probes[-1]
    return Finding(
        id=finding_id,
        type="Broken Object-Level Authorization",
        title=_TITLES.get(ep.owner_kind, "Customer accessed another customer's private resource"),
        severity="critical" if verdict.sensitive_fields else "medium",
        confidence="high",
        endpoint=ep.endpoint,
        method=ep.method,
        authenticated_user=attacker.name,
        authenticated_role=attacker.role,
        resource_owner=victim.name,
        expected_status=verdict.expected_status,
        observed_status=cross.status_code,
        request=EvidenceRequest(
            url=cross.url, method=ep.method, authorization=cross.authorization_redacted
        ),
        response=EvidenceResponse(status_code=cross.status_code, body=cross.body),
        probes=list(verdict.probes),
        sensitive_fields_exposed=list(verdict.sensitive_fields),
        impact=_IMPACT.get(ep.owner_kind, _IMPACT["order"]),
        recommendation=_RECOMMEND.get(ep.owner_kind, _RECOMMEND["order"]),
        status="fail",
    )


def make_check(
    check_id: str,
    ep: ObjectEndpoint,
    attacker: IdentityView,
    victim: IdentityView,
    verdict: Verdict,
) -> CheckResult:
    return CheckResult(
        id=check_id,
        endpoint=ep.endpoint,
        method=ep.method,
        authenticated_user=attacker.name,
        authenticated_role=attacker.role,
        resource_owner=victim.name,
        expected_status=verdict.expected_status,
        observed_status=verdict.observed_status,
        status="pass",
        probes=list(verdict.probes),
        sensitive_fields_exposed=list(verdict.sensitive_fields),
        impact=_IMPACT.get(ep.owner_kind, _IMPACT["order"]),
        recommendation=_RECOMMEND.get(ep.owner_kind, _RECOMMEND["order"]),
        regression_test=verdict.regression_test,
    )
