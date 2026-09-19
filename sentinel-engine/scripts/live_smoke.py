"""Live smoke test: real demo API (subprocess) + real engine (in-process server).

Run from sentinel-engine/:

    venv/bin/python scripts/live_smoke.py

Drives the full demo story over real HTTP:
  vulnerable mode  -> BOLA finding with evidence + generated regression test
  secure mode      -> same probe becomes a passed check, security score 100
  non-local target -> 422 rejection

Aborts safely if either port is already serving (never disturbs running services).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

ENGINE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_DIR.parent
DEMO_DIR = REPO_ROOT / "vulnerable-demo-api"

DEMO_PORT, ENGINE_PORT = 8001, 8000
DEMO_BASE = f"http://127.0.0.1:{DEMO_PORT}"
ENGINE_BASE = f"http://127.0.0.1:{ENGINE_PORT}"

sys.path.insert(0, str(ENGINE_DIR))
from app.main import app as engine_app  # noqa: E402  (engine only; demo runs in a subprocess)

SCAN_IDENTITIES = [
    {"name": "Alice", "id": "user-101", "role": "customer", "token": "alice-token"},
    {"name": "Bob", "id": "user-102", "role": "customer", "token": "bob-token"},
    {"name": "Priya", "id": "admin-001", "role": "admin", "token": "admin-token"},
]


def _wait_http(url: str, attempts: int = 60) -> None:
    for _ in range(attempts):
        try:
            httpx.get(url, timeout=1.0)
            return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise RuntimeError(f"service at {url} did not become healthy")


def start_demo() -> subprocess.Popen:
    cmd = [
        str(DEMO_DIR / "venv" / "bin" / "python"), "-m", "uvicorn",
        "app.main:app", "--host", "127.0.0.1", "--port", str(DEMO_PORT),
        "--log-level", "warning",
    ]
    proc = subprocess.Popen(cmd, cwd=DEMO_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_http(f"{DEMO_BASE}/health")
    except RuntimeError:
        proc.kill()
        raise
    return proc


def start_engine() -> uvicorn.Server:
    config = uvicorn.Config(engine_app, host="127.0.0.1", port=ENGINE_PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    _wait_http(f"{ENGINE_BASE}/health")
    return server


def set_demo_mode(mode: str) -> None:
    r = httpx.post(f"{DEMO_BASE}/admin/mode", json={"mode": mode}, timeout=5.0)
    r.raise_for_status()


def run_scan(engine: httpx.Client) -> dict:
    r = engine.post(
        "/scan",
        json={
            "target_base_url": DEMO_BASE,
            "openapi_url": f"{DEMO_BASE}/openapi.json",
            "identities": SCAN_IDENTITIES,
        },
    )
    assert r.status_code == 201, f"POST /scan failed: {r.status_code} {r.text}"
    return r.json()


def main() -> int:
    # Safety: never disturb services that are already running.
    for name, url in (("demo API", f"{DEMO_BASE}/health"), ("engine", f"{ENGINE_BASE}/health")):
        try:
            httpx.get(url, timeout=1.0)
            print(f"ABORT: {name} already running at {url} — stop it first (see run_all.sh)")
            return 2
        except httpx.HTTPError:
            pass

    passed = 0
    demo_proc = start_demo()
    engine_server = start_engine()
    engine = httpx.Client(base_url=ENGINE_BASE, timeout=20.0)
    try:
        print("engine /health:", engine.get("/health").json())

        # --- 1) vulnerable mode: hero finding ---------------------------------
        set_demo_mode("vulnerable")
        scan = run_scan(engine)
        summary = scan["summary"]
        print(
            f"[vulnerable] findings={summary['findings']} passed={summary['passed']} "
            f"score={summary['security_score']} mode={summary['demo_mode']} "
            f"tested={summary['tested_endpoints']} endpoints"
        )
        assert summary["demo_mode"] == "vulnerable"
        assert summary["findings"] >= 1, "expected at least one BOLA finding"
        assert summary["security_score"] <= 40
        passed += 1

        finding_id = scan["finding_ids"][0]
        finding = engine.get(f"/scan/{scan['id']}/findings/{finding_id}").json()
        print(
            f"  {finding['id']} [{finding['severity']}] {finding['endpoint']} "
            f"expected {finding['expected_status']} observed {finding['observed_status']}"
        )
        print(f"  exposed: {finding['sensitive_fields_exposed']}")
        print(f"  evidence Authorization header: {finding['request']['authorization']}")
        assert finding["observed_status"] == 200 and finding["expected_status"] == 403
        assert "shipping_address" in finding["sensitive_fields_exposed"]
        assert finding["request"]["authorization"] == "Bearer alic...oken"
        passed += 1

        # --- 2) no raw tokens anywhere in API output ---------------------------
        blob = json.dumps(engine.get(f"/scan/{scan['id']}/findings").json())
        blob += json.dumps(engine.get(f"/scan/{scan['id']}/checks").json())
        for raw in ("alice-token", "bob-token", "admin-token"):
            assert raw not in blob, f"raw token {raw!r} leaked"
        print("redaction: no raw tokens in findings or checks")
        passed += 1

        # --- 3) generated regression test --------------------------------------
        test_code = engine.get(f"/scan/{scan['id']}/findings/{finding_id}/test").text
        print("generated regression test:")
        print("   " + test_code.replace("\n", "\n   "))
        compile(test_code, "<generated>", "exec")
        assert '"Bearer alic...oken"' in test_code
        passed += 1

        # --- 3b) verify while still vulnerable: re-probe must NOT flip ----------
        v = engine.post(f"/scan/{scan['id']}/verify").json()
        print(
            f"verify (still vulnerable): verified={v['verified_count']}/{len(v['results'])} "
            f"all_verified={v['all_verified']}"
        )
        assert v["verified_count"] == 0 and v["all_verified"] is False
        assert all(r["now"]["observed_status"] == 200 for r in v["results"])
        passed += 1

        # --- 4) secure mode: the fix verifies ----------------------------------
        set_demo_mode("secure")
        scan2 = run_scan(engine)
        summary2 = scan2["summary"]
        print(
            f"[secure] findings={summary2['findings']} passed={summary2['passed']} "
            f"score={summary2['security_score']} mode={summary2['demo_mode']}"
        )
        assert summary2["findings"] == 0 and summary2["security_score"] == 100
        passed += 1

        checks = engine.get(f"/scan/{scan2['id']}/checks").json()
        order_check = next(c for c in checks if c["endpoint"] == "GET /api/orders/{order_id}")
        print(f"  verify-fix check: {order_check['endpoint']} observed {order_check['observed_status']} -> {order_check['status']}")
        assert order_check["observed_status"] == 403 and order_check["status"] == "pass"
        passed += 1

        # --- 4b) one-click Verify Fix on the original vulnerable-mode scan ------
        r = engine.post(f"/scan/{scan['id']}/verify")
        assert r.status_code == 200, r.text
        v = r.json()
        first = v["results"][0]
        print(
            f"[verify-fix] demo_mode={v['demo_mode']} "
            f"verified={v['verified_count']}/{len(v['results'])}"
        )
        print(
            f"  before/after: HTTP {first['was']['observed_status']} ({first['was']['status']}) "
            f"-> HTTP {first['now']['observed_status']} ({first['now']['status']})"
        )
        assert v["demo_mode"] == "secure" and v["all_verified"] is True
        assert first["was"]["observed_status"] == 200 and first["was"]["status"] == "fail"
        assert first["now"]["observed_status"] in (401, 403) and first["now"]["status"] == "pass"
        updated = engine.get(f"/scan/{scan['id']}/findings/{finding_id}").json()
        assert updated["status"] == "pass"  # finding persisted the flip
        passed += 1

        # --- 5) non-local target rejected ---------------------------------------
        bad = engine.post(
            "/scan",
            json={
                "target_base_url": "http://example.com",
                "openapi_url": "http://example.com/openapi.json",
                "identities": SCAN_IDENTITIES,
            },
        )
        print(f"non-local target: HTTP {bad.status_code} — {bad.json()['detail'][:80]}...")
        assert bad.status_code == 422
        passed += 1

        print(f"\nALL {passed} SMOKE CHECKS PASSED")
        return 0
    finally:
        engine_server.should_exit = True
        demo_proc.terminate()
        try:
            demo_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            demo_proc.kill()
        engine_client_closed = engine
        engine_client_closed.close()


if __name__ == "__main__":
    sys.exit(main())
