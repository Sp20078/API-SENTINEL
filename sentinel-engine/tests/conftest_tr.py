"""Trust Router fixtures, importable as a plugin via conftest import.

Kept out of the main conftest.py so the BOLA scanner suite (and its
demo-subprocess fixtures) stays completely untouched. test_trust_router.py
imports * from this module to register the fixtures.
"""

from __future__ import annotations

import threading
import time

import pytest
import uvicorn

from tests.trust_mock import STATE, build_mock_app


@pytest.fixture(scope="module")
def mock_providers():
    server = uvicorn.Server(
        uvicorn.Config(build_mock_app(), host="127.0.0.1", port=0, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "mock provider server did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def tr_client(mock_providers, monkeypatch):
    """Fresh Trust Router app per test, pointed at the mock providers via env.

    Fully isolated from :8002 and from the scanner's session app; mock state
    resets after each test.
    """
    base = mock_providers
    monkeypatch.setenv("TRUST_ROUTER_PRIMARY_URL", f"{base}/primary/weather")
    monkeypatch.setenv("TRUST_ROUTER_BACKUP_URL", f"{base}/backup/weather")
    monkeypatch.setenv("TRUST_ROUTER_PRIMARY_MODE_URL", f"{base}/primary/mode")
    monkeypatch.setenv("TRUST_ROUTER_FX_PRIMARY_URL", f"{base}/primary/fx")
    monkeypatch.setenv("TRUST_ROUTER_FX_BACKUP_URL", f"{base}/backup/fx")
    monkeypatch.setenv("TRUST_ROUTER_FX_PRIMARY_MODE_URL", f"{base}/primary/mode")
    STATE.update(
        primary_mode="healthy",
        primary_up=True,
        backup_up=True,
        leak_fields=[],
        fx_mode="healthy",
        fx_up=True,
        fx_backup_up=True,
        fx_leak_fields=[],
    )
    from fastapi.testclient import TestClient

    from app.trust_router.api import build_trust_router_app

    with TestClient(build_trust_router_app()) as client:
        yield client
    STATE.update(
        primary_mode="healthy",
        primary_up=True,
        backup_up=True,
        leak_fields=[],
        fx_mode="healthy",
        fx_up=True,
        fx_backup_up=True,
        fx_leak_fields=[],
    )
