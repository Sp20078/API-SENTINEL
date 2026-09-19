"""Tests for the local weather provider simulators.

Unit tests run the app in-process (no port, no venv needed).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_primary_mode() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "weather-providers"
    assert body["primary_mode"] == "healthy"


def test_primary_mode_switch_roundtrip() -> None:
    r = client.post("/primary/mode", json={"mode": "stale_data"})
    assert r.status_code == 200
    assert r.json()["mode"] == "stale_data"
    assert client.get("/primary/mode").json()["mode"] == "stale_data"

    client.post("/primary/mode", json={"mode": "healthy"})
    assert client.get("/primary/mode").json()["mode"] == "healthy"


def test_primary_mode_rejects_unknown() -> None:
    r = client.post("/primary/mode", json={"mode": "chaos"})
    assert r.status_code == 422


def test_primary_healthy_shape() -> None:
    body = client.get("/primary/weather", params={"city": "Bengaluru"}).json()
    for field in ("city", "temp_c", "humidity", "condition", "observed_at", "provider"):
        assert field in body
    assert isinstance(body["temp_c"], (int, float))
    assert body["provider"] == "local-weather-primary-v1"


def test_backup_shape_is_nested_and_different() -> None:
    body = client.get("/backup/weather", params={"city": "Bengaluru"}).json()
    assert set(body["meta"]) == {"city_name", "provider"}
    assert set(body["current"]) == {"tempC", "relHumidity", "sky", "ts_iso"}
    assert "extra_field_ignored" in body


def test_unknown_city_gets_deterministic_synthetic_weather() -> None:
    a = client.get("/backup/weather", params={"city": "Nowhereland"}).json()
    b = client.get("/backup/weather", params={"city": "Nowhereland"}).json()
    assert a["current"]["tempC"] == b["current"]["tempC"]  # deterministic
