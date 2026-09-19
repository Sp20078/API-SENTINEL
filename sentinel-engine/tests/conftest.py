"""Shared fixtures for scanner-engine tests.

Integration tests spawn the real demo API (uvicorn subprocess on :8001) and scan
it over actual HTTP, so every acceptance claim is backed by real requests.
"""

from __future__ import annotations

import httpx
import pytest
import uvicorn

from app.main import app as engine_app
from fastapi.testclient import TestClient

DEMO_PORT = 8001
DEMO_BASE = f"http://127.0.0.1:{DEMO_PORT}"


def _port_in_use(port: int) -> bool:
    try:
        httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
        return True
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def demo_server():
    """Start the demo API in a uvicorn subprocess; yield the Popen; terminate.

    Skips (rather than cross-talks) when port 8001 is already serving — the
    integration tests must never run against a foreign service, flip its mode,
    or 'kill' someone else's server in the 502 test.
    """
    import subprocess
    import time
    from pathlib import Path

    if _port_in_use(DEMO_PORT):
        pytest.skip(
            f"port {DEMO_PORT} already in use — stop the running demo API first "
            "(scripts/dev_daemon.sh stop)"
        )

    demo_dir = Path(__file__).resolve().parents[2] / "vulnerable-demo-api"
    proc = subprocess.Popen(
        [
            str(demo_dir / "venv" / "bin" / "python"),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(DEMO_PORT),
            "--log-level",
            "warning",
        ],
        cwd=demo_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            if proc.poll() is not None:
                raise RuntimeError("demo subprocess exited during startup (port conflict?)")
            try:
                httpx.get(f"{DEMO_BASE}/health", timeout=1.0)
                break
            except httpx.HTTPError:
                time.sleep(0.25)
        else:
            raise RuntimeError("demo API did not become healthy")
        if proc.poll() is not None:
            raise RuntimeError("demo subprocess died after startup")
        yield proc  # the Popen handle (tests may terminate it; base URL is DEMO_BASE)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(engine_app)


def set_demo_mode(mode: str) -> None:
    r = httpx.post(f"{DEMO_BASE}/admin/mode", json={"mode": mode}, timeout=5.0)
    r.raise_for_status()


@pytest.fixture()
def vulnerable_mode(demo_server):
    set_demo_mode("vulnerable")
    yield DEMO_BASE
    try:
        set_demo_mode("vulnerable")  # restore default on teardown
    except httpx.HTTPError:
        pass  # server may already be down (e.g. killed by the 502 test)


@pytest.fixture()
def secure_mode(demo_server):
    set_demo_mode("secure")
    yield DEMO_BASE
    try:
        set_demo_mode("vulnerable")
    except httpx.HTTPError:
        pass  # server may already be down (e.g. killed by the 502 test)
