"""Integration tests for POST /scan/{scan_id}/verify (one-click Verify Fix).

Runs against the real demo API subprocess. The 502 test intentionally kills the
shared demo server, so it must remain the LAST demo-dependent test (this file
sorts last, and the test is last within the file).
"""

from __future__ import annotations

import httpx
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


def _scan(client: TestClient, base_url: str) -> dict:
    r = client.post("/scan", json=_scan_request(base_url))
    assert r.status_code == 201, r.text
    return r.json()


def _set_mode(base_url: str, mode: str) -> None:
    r = httpx.post(f"{base_url}/admin/mode", json={"mode": mode}, timeout=5.0)
    r.raise_for_status()


def test_verify_flips_findings_to_pass_after_fix(vulnerable_mode, secure_mode, client) -> None:
    _set_mode(vulnerable_mode, "vulnerable")  # shared session server; pin explicitly
    scan = _scan(client, vulnerable_mode)
    finding_id = scan["finding_ids"][0]

    finding = client.get(f"/scan/{scan['id']}/findings/{finding_id}").json()
    assert finding["status"] == "fail"
    assert finding["observed_status"] == 200
    assert finding["verification"] is None  # nothing verified yet

    _set_mode(secure_mode, "secure")
    r = client.post(f"/scan/{scan['id']}/verify")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["demo_mode"] == "secure"
    assert len(body["results"]) >= 1
    assert body["verified_count"] == len(body["results"])
    assert body["all_verified"] is True
    for res in body["results"]:
        assert res["was"]["observed_status"] == 200  # before evidence preserved
        assert res["was"]["status"] == "fail"
        assert res["now"]["observed_status"] in (401, 403)  # fresh probe over real HTTP
        assert res["now"]["status"] == "pass"
        assert res["verified"] is True
        assert res["note"] is None
        assert res["probes"][0]["authorization_redacted"] == "Bearer alic...oken"

    # the finding itself is updated and persisted in the store
    updated = client.get(f"/scan/{scan['id']}/findings/{finding_id}").json()
    assert updated["status"] == "pass"
    assert updated["observed_status"] in (401, 403)
    assert updated["verification"]["blocked"] is True
    assert updated["verification"]["observed_status"] in (401, 403)


def test_verify_still_fails_when_target_still_vulnerable(vulnerable_mode, client) -> None:
    scan = _scan(client, vulnerable_mode)
    r = client.post(f"/scan/{scan['id']}/verify")
    assert r.status_code == 200
    body = r.json()

    assert body["demo_mode"] == "vulnerable"
    assert body["verified_count"] == 0
    assert body["all_verified"] is False
    for res in body["results"]:
        assert res["was"]["status"] == "fail"
        assert res["now"]["status"] == "fail"
        assert res["now"]["observed_status"] == 200  # still leaking
        assert res["verified"] is False
        assert res["note"]

    # findings untouched (status stays fail, no flip)
    findings = client.get(f"/scan/{scan['id']}/findings").json()
    assert all(f["status"] == "fail" for f in findings)


def test_verify_unknown_scan_404(client) -> None:
    r = client.post("/scan/scan-999/verify")
    assert r.status_code == 404


def test_verify_scan_without_findings_404(secure_mode, client) -> None:
    scan = _scan(client, secure_mode)  # secure scan produces passes, not findings
    r = client.post(f"/scan/{scan['id']}/verify")
    assert r.status_code == 404
    assert "no findings" in r.json()["detail"]


def test_verify_target_unreachable_502(vulnerable_mode, client, demo_server, request) -> None:
    """Kill the demo target after the scan; verify must 502, not 500."""
    scan = _scan(client, vulnerable_mode)
    assert scan["state"] == "completed"

    demo_server.terminate()
    demo_server.wait(timeout=5)

    r = client.post(f"/scan/{scan['id']}/verify")
    assert r.status_code == 502
    assert "Target unreachable" in r.json()["detail"]
