"""Tests for the local provider simulators (weather + FX categories).

Unit tests run the app in-process (no port, no venv needed).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_primary_mode_per_category() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "provider-simulators"
    assert body["primary_mode"] == "healthy"
    assert body["category"] == "weather"


def test_primary_mode_switch_is_per_category() -> None:
    # flip weather only; fx must stay healthy
    r = client.post("/primary/mode", json={"mode": "stale_data", "category": "weather"})
    assert r.status_code == 200
    assert r.json()["mode"] == "stale_data"
    assert r.json()["category"] == "weather"
    assert client.get("/primary/mode", params={"category": "weather"}).json()["mode"] == "stale_data"
    assert client.get("/primary/mode", params={"category": "fx"}).json()["mode"] == "healthy"

    r = client.post("/primary/mode", json={"mode": "http_503", "category": "fx"})
    assert r.status_code == 200
    assert client.get("/primary/mode", params={"category": "fx"}).json()["mode"] == "http_503"
    assert client.get("/primary/mode", params={"category": "weather"}).json()["mode"] == "stale_data"

    # reset both
    client.post("/primary/mode", json={"mode": "healthy", "category": "weather"})
    client.post("/primary/mode", json={"mode": "healthy", "category": "fx"})


def test_primary_mode_rejects_unknown_mode_and_category() -> None:
    assert client.post("/primary/mode", json={"mode": "chaos"}).status_code == 422
    assert (
        client.post("/primary/mode", json={"mode": "healthy", "category": "chaos"}).status_code
        == 422
    )


def test_primary_weather_healthy_shape() -> None:
    body = client.get("/primary/weather", params={"city": "Bengaluru"}).json()
    for field in ("city", "temp_c", "humidity", "condition", "observed_at", "provider"):
        assert field in body
    assert isinstance(body["temp_c"], (int, float))
    assert body["provider"] == "local-weather-primary-v1"


def test_primary_weather_fault_modes() -> None:
    client.post("/primary/mode", json={"mode": "http_503", "category": "weather"})
    assert client.get("/primary/weather", params={"city": "X"}).status_code == 503

    client.post("/primary/mode", json={"mode": "malformed_schema", "category": "weather"})
    body = client.get("/primary/weather", params={"city": "X"}).json()
    assert "condition" not in body  # missing required field
    assert isinstance(body["temp_c"], str)  # wrong type
    assert body["internal_user_id"] == "user-424242"  # prohibited leak

    client.post("/primary/mode", json={"mode": "stale_data", "category": "weather"})
    body = client.get("/primary/weather", params={"city": "X"}).json()
    assert body["observed_at"].endswith("Z")  # valid shape, old timestamp

    client.post("/primary/mode", json={"mode": "healthy", "category": "weather"})


def test_backup_weather_shape_is_nested_and_different() -> None:
    body = client.get("/backup/weather", params={"city": "Bengaluru"}).json()
    assert set(body["meta"]) == {"city_name", "provider"}
    assert set(body["current"]) == {"tempC", "relHumidity", "sky", "ts_iso"}
    assert "extra_field_ignored" in body


def test_primary_fx_healthy_shape() -> None:
    body = client.get("/primary/fx", params={"base": "USD", "quote": "INR"}).json()
    for field in ("base", "quote", "rate", "inverse_rate", "observed_at", "provider"):
        assert field in body
    assert isinstance(body["rate"], (int, float))
    assert body["provider"] == "local-fx-primary-v1"


def test_primary_fx_fault_modes() -> None:
    client.post("/primary/mode", json={"mode": "http_503", "category": "fx"})
    assert client.get("/primary/fx", params={"base": "USD", "quote": "EUR"}).status_code == 503

    client.post("/primary/mode", json={"mode": "malformed_schema", "category": "fx"})
    body = client.get("/primary/fx", params={"base": "USD", "quote": "EUR"}).json()
    assert isinstance(body["rate"], str)  # wrong type
    assert "inverse_rate" not in body  # missing required field
    assert body["customer_email"] == "someone@example.com"  # prohibited leak

    client.post("/primary/mode", json={"mode": "stale_data", "category": "fx"})
    body = client.get("/primary/fx", params={"base": "USD", "quote": "EUR"}).json()
    assert isinstance(body["rate"], (int, float))  # valid shape, old timestamp

    client.post("/primary/mode", json={"mode": "healthy", "category": "fx"})


def test_backup_fx_shape_is_nested_and_different() -> None:
    body = client.get("/backup/fx", params={"base": "USD", "quote": "INR"}).json()
    assert set(body["result"]) == {
        "from_currency",
        "to_currency",
        "mid",
        "rate_of_exchange",
        "as_of",
    }
    assert body["service"] == {"name": "local-fx-backup-v1"}
    assert "disallowed_noise" in body


def test_fx_unknown_pair_gets_deterministic_synthetic_rates() -> None:
    params = {"base": "XXX", "quote": "YYY"}
    a = client.get("/backup/fx", params=params).json()
    b = client.get("/backup/fx", params=params).json()
    assert a["result"]["mid"] == b["result"]["mid"]  # deterministic
    assert a["result"]["mid"] > 0
