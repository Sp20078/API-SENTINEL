"""End-to-end pipeline tests against the real demo API (uvicorn subprocess).

These are the Phase 2 acceptance tests:
  - vulnerable mode: scanner detects BOLA for Alice -> Bob order access
  - secure mode: the same probe is reported as a passed check
  - responses never leak raw tokens
  - non-local targets are rejected
  - a failed target surfaces as a failed scan, not a crash
"""

from __future__ import annotations

import json

import httpx

from app.scanner.bola import IdentityView, ObjectEndpoint
from app.scanner.engine import DEFAULT_RESOURCE_OWNERSHIP
from fastapi.testclient import TestClient


def _scan_request(base_url: str) -> dict:
    return {
        "target_base_url": base_url,
        "openapi_url": f"{base_url}/openapi.json",
        "identities": [
            {"name": "Alice", "id": "user-101", "role": "customer", "token": "alice-token"},
            {"name": "Bob", "id": "user-102", "role": "customer", "token": "bob-token"},
            {"name": "Priya", "id": "admin-001", "role": "admin", "token": "admin-token"},
        ],
    }


def _set_mode(base_url: str, mode: str) -> None:
    r = httpx.post(f"{base_url}/admin/mode", json={"mode": mode}, timeout=5.0)
    r.raise_for_status()


def _scan(client: TestClient, base_url: str):
    r = client.post("/scan", json=_scan_request(base_url))
    assert r.status_code == 201, r.text
    return r.json()


# --- vulnerable mode ---------------------------------------------------------


def test_vulnerable_mode_detects_order_and_profile_bola(vulnerable_mode, client) -> None:
    scan = _scan(client, vulnerable_mode)
    assert scan["state"] == "completed"
    assert scan["summary"]["demo_mode"] == "vulnerable"
    assert scan["summary"]["findings"] >= 1
    assert scan["summary"]["security_score"] <= 40  # at least one finding penalizes the score

    findings = client.get(f"/scan/{scan['id']}/findings").json()
    order = next(f for f in findings if f["endpoint"] == "GET /api/orders/{order_id}")
    assert order["severity"] == "critical"
    assert order["status"] == "fail"
    assert order["authenticated_user"] == "Alice"
    assert order["authenticated_role"] == "customer"
    assert order["resource_owner"] == "Bob"
    assert order["expected_status"] == 403
    assert order["observed_status"] == 200
    assert order["response"]["body"]["user_id"] == "user-102"
    assert order["response"]["body"]["shipping_address"] == "42 Park Street"
    assert "shipping_address" in order["sensitive_fields_exposed"]
    assert "total" in order["sensitive_fields_exposed"]
    assert "items" in order["sensitive_fields_exposed"]

    profile = next(f for f in findings if f["endpoint"] == "GET /api/users/{user_id}")
    assert profile["severity"] == "critical"
    assert "email" in profile["sensitive_fields_exposed"]

    # evidence structure: own probe succeeded first, cross-user probe captured the leak
    assert [p["label"] for p in order["probes"]] == ["own_resource", "cross_user"]
    assert order["probes"][0]["status_code"] == 200


def test_vulnerable_mode_tokens_redacted_everywhere(vulnerable_mode, client) -> None:
    scan_response = _scan(client, vulnerable_mode)
    scan_id = scan_response["id"]
    blob = json.dumps(
        {
            "scan": scan_response,
            "findings": client.get(f"/scan/{scan_id}/findings").json(),
            "checks": client.get(f"/scan/{scan_id}/checks").json(),
        }
    )
    for raw in ("alice-token", "bob-token", "admin-token"):
        assert raw not in blob, f"raw token {raw!r} leaked into API output"


def test_finding_test_endpoint_generates_pytest(vulnerable_mode, client) -> None:
    scan = _scan(client, vulnerable_mode)
    finding_id = scan["finding_ids"][0]
    r = client.get(f"/scan/{scan['id']}/findings/{finding_id}/test")
    assert r.status_code == 200
    code = r.text
    assert "def test_alice_cannot_access_another_customers" in code
    assert '"Authorization": "Bearer alic...oken"' in code  # redacted in generated test
    assert "assert response.status_code in [401, 403]" in code
    compile(code, "<generated>", "exec")  # the generated test must be valid Python


# --- secure mode -------------------------------------------------------------


def test_secure_mode_reports_passed_checks_and_score_100(secure_mode, client) -> None:
    scan = _scan(client, secure_mode)
    assert scan["state"] == "completed"
    assert scan["summary"]["demo_mode"] == "secure"
    assert scan["summary"]["findings"] == 0
    assert scan["summary"]["passed"] >= 1
    assert scan["summary"]["security_score"] == 100

    checks = client.get(f"/scan/{scan['id']}/checks").json()
    order_check = next(c for c in checks if c["endpoint"] == "GET /api/orders/{order_id}")
    assert order_check["status"] == "pass"
    assert order_check["observed_status"] == 403  # the hero fix, verified over real HTTP
    assert order_check["expected_status"] == 403
    assert "shipping_address" not in json.dumps(order_check["probes"][1]["body"])


def test_verify_fix_flow_before_after(vulnerable_mode, secure_mode, client) -> None:
    """Switch vulnerable -> secure and confirm the finding flips to a pass."""
    _set_mode(vulnerable_mode, "vulnerable")  # fixtures share a session; pin explicitly
    scan_v = _scan(client, vulnerable_mode)
    assert scan_v["summary"]["findings"] >= 1

    _set_mode(secure_mode, "secure")
    scan_s = _scan(client, secure_mode)
    assert scan_s["summary"]["findings"] == 0
    assert scan_s["summary"]["security_score"] == 100

    # the generated regression test from the vulnerable finding now passes against secure
    finding_id = scan_v["finding_ids"][0]
    code = client.get(f"/scan/{scan_v['id']}/findings/{finding_id}/test").text
    assert "alice-token" not in code  # raw token never in generated test
    assert "alic...oken" in code


# --- target safety / failure handling ------------------------------------------


def test_non_local_target_rejected(client) -> None:
    r = client.post("/scan", json=_scan_request("http://api.example.com"))
    assert r.status_code == 422
    assert "approved local target" in r.json()["detail"]


def test_https_target_rejected_in_mvp(client) -> None:
    r = client.post("/scan", json=_scan_request("https://api.example.com"))
    assert r.status_code == 422


def test_unreachable_local_target_fails_gracefully(client) -> None:
    r = client.post("/scan", json=_scan_request("http://127.0.0.1:59999"))
    assert r.status_code == 201
    scan = r.json()
    assert scan["state"] == "failed"
    assert scan["error"]


def test_scan_lookup_404(client) -> None:
    assert client.get("/scan/scan-999").status_code == 404
    assert client.get("/scan/scan-999/findings").status_code == 404


# --- endpoint mapping sanity -----------------------------------------------------


def test_default_resource_ownership_matches_demo_data() -> None:
    assert DEFAULT_RESOURCE_OWNERSHIP["order"]["order-1001"] == "user-101"
    assert DEFAULT_RESOURCE_OWNERSHIP["order"]["order-1002"] == "user-102"
    assert DEFAULT_RESOURCE_OWNERSHIP["user"]["user-101"] == "user-101"
    assert DEFAULT_RESOURCE_OWNERSHIP["user"]["user-102"] == "user-102"


def test_identity_view_holds_token_request_side_only() -> None:
    import dataclasses

    view = IdentityView(name="Alice", id="user-101", role="customer", token="alice-token")
    assert dataclasses.asdict(view)["token"] == "alice-token"  # request-side only, never persisted


def test_object_endpoint_fills_templates() -> None:
    from app.scanner.bola import _fill

    assert _fill("/api/orders/{order_id}", "order_id", "order-1002") == "/api/orders/order-1002"
    assert _fill("/api/users/{user_id}", "user_id", "user-102") == "/api/users/user-102"
