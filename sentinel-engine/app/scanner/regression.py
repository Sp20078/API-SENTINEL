"""Pytest regression-test generation from BOLA findings and passing checks.

The generated test is derived from the actual evidence: real endpoint, real
cross-user resource id, the attacker identity's (redacted) token, and the
expected 401/403 assertion. Copy-paste runnable in the target API's test suite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from ..models import CheckResult, Finding, Probe

_RESOURCE_PARAM_BY_SEGMENT = {
    "orders": "order_id",
    "users": "user_id",
}


def _snake(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return name or "resource"


@dataclass(frozen=True)
class TestInputs:
    """Everything the generator needs, extracted from evidence."""

    authenticated_user: str
    authenticated_role: str
    resource_param: str  # e.g. "order_id"
    request_url: str  # concrete cross-user URL
    authorization: str | None  # redacted header value


def _resource_param(endpoint_path: str) -> str:
    """Pick the path parameter that carries the object id from the endpoint template."""
    for segment, param in _RESOURCE_PARAM_BY_SEGMENT.items():
        if f"/{segment}/" in endpoint_path:
            return param
    params = re.findall(r"\{([^}]+)\}", endpoint_path)
    return params[0] if params else "id"


def _inputs_from(endpoint_path: str, probe: Probe, user: str, role: str) -> TestInputs:
    return TestInputs(
        authenticated_user=user,
        authenticated_role=role,
        resource_param=_resource_param(endpoint_path),
        request_url=probe.url,
        authorization=probe.authorization_redacted,
    )


def inputs_from_finding(finding: Finding) -> TestInputs:
    template_path = finding.endpoint.removeprefix(f"{finding.method} ").strip()
    return _inputs_from(
        template_path,
        finding.probes[-1],  # cross-user probe
        finding.authenticated_user,
        finding.authenticated_role,
    )


def inputs_from_check(check: CheckResult) -> TestInputs:
    endpoint = check.endpoint
    template_path = endpoint.split(" ", 1)[-1] if " " in endpoint else endpoint
    return _inputs_from(
        template_path,
        check.probes[-1],
        check.authenticated_user,
        check.authenticated_role,
    )


def render_test(inputs: TestInputs) -> str:
    attacker = _snake(inputs.authenticated_user)
    if inputs.authenticated_role == "customer":
        func = f"test_{attacker}_cannot_access_another_customers_{inputs.resource_param}"
    else:
        func = f"test_{attacker}_unauthorized_access_blocked_{inputs.resource_param}"
    token = inputs.authorization or "Bearer redacted"
    # Emit the relative path (like the target's own TestClient tests) rather than
    # the absolute URL, so the test is portable into the target's test suite.
    request_path = urlparse(inputs.request_url).path or inputs.request_url
    return (
        f"def {func}():\n"
        f"    response = client.get(\n"
        f'        "{request_path}",\n'
        f'        headers={{"Authorization": "{token}"}},\n'
        f"    )\n"
        f"    assert response.status_code in [401, 403]\n"
    )


def generate_regression_test(finding: Finding) -> str:
    return render_test(inputs_from_finding(finding))


def generate_check_test(check: CheckResult) -> str:
    return render_test(inputs_from_check(check))
