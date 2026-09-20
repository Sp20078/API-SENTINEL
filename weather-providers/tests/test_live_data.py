"""Tests for the live data tiers (Open-Meteo weather, Frankfurter FX).

All HTTP is mocked at the module seam (_http_get_json) — no real network in
CI. Handler-level tests verify the tier marker (data_source) and that fault
modes layer cleanly on top of live data.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import live_fx, live_weather
from app.main import app

client = TestClient(app)

OPEN_METEO_GEOCODE = {"results": [{"latitude": 12.97, "longitude": 77.59}]}
OPEN_METEO_FORECAST = {
    "current": {
        "time": "2026-09-20T12:30",
        "temperature_2m": 21.5,
        "relative_humidity_2m": 61,
        "weather_code": 2,
        "utc_offset_seconds": 0,
    }
}
FRANKFURTER = {"amount": 1.0, "base": "USD", "date": "2026-09-19", "rates": {"INR": 83.12}}


@pytest.fixture(autouse=True)
def _clean_state():
    live_weather.reset_cache()
    live_fx.reset_cache()
    client.post("/primary/mode", json={"mode": "healthy", "category": "weather"})
    client.post("/primary/mode", json={"mode": "healthy", "category": "fx"})
    yield
    live_weather.reset_cache()
    live_fx.reset_cache()
    client.post("/primary/mode", json={"mode": "healthy", "category": "weather"})
    client.post("/primary/mode", json={"mode": "healthy", "category": "fx"})


def _mock_weather_http(calls: list[str], *, geocode: dict | None = None):
    def fake_get_json(url, params, timeout_s):
        calls.append(url)
        if "geocoding-api" in url:
            return geocode if geocode is not None else OPEN_METEO_GEOCODE
        return OPEN_METEO_FORECAST

    return fake_get_json


def _enable_live(monkeypatch):
    monkeypatch.setenv("TRUST_ROUTER_LIVE_DATA", "1")


# --- fetcher unit tests (weather) -------------------------------------------


def test_fetch_live_weather_parses_open_meteo(monkeypatch):
    _enable_live(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http(calls))

    result = live_weather.fetch_live_weather("Bengaluru")

    assert result is not None
    assert result["source"] == "live"
    assert result["temp_c"] == 21.5
    assert result["humidity"] == 61
    assert result["condition"] == "Partly cloudy"  # WMO code 2
    assert result["observed_at"] == "2026-09-20T12:30:00Z"
    assert len(calls) == 2  # one geocode + one forecast


def test_fetch_live_weather_unknown_city_returns_none(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(
        live_weather, "_http_get_json", _mock_weather_http([], geocode={"results": []})
    )

    assert live_weather.fetch_live_weather("Nowhereville") is None


def test_fetch_live_weather_failure_returns_none(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(live_weather, "_http_get_json", lambda *a, **k: None)

    assert live_weather.fetch_live_weather("X") is None


def test_fetch_live_weather_cache_hit_avoids_second_fetch(monkeypatch):
    _enable_live(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http(calls))

    first = live_weather.fetch_live_weather("Tokyo")
    second = live_weather.fetch_live_weather("tokyo")  # case-insensitive key

    assert first["source"] == "live"
    assert second["source"] == "cached"
    assert second["temp_c"] == first["temp_c"]
    assert len(calls) == 2  # no additional HTTP on the cache hit


def test_fetch_live_weather_circuit_breaker_skips_api_after_failure(monkeypatch):
    _enable_live(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http(calls))
    monkeypatch.setattr(
        live_weather, "_fetch_open_meteo", lambda *a, **k: None  # upstream down
    )

    assert live_weather.fetch_live_weather("Oslo") is None  # breaker opens
    assert live_weather.fetch_live_weather("Oslo") is None  # served from empty cache

    # breaker prevented a second real attempt within the cooldown window
    monkeypatch.setattr(live_weather, "_fetch_open_meteo", lambda *a, **k: dict(OPEN_METEO_FORECAST))
    assert live_weather.fetch_live_weather("Oslo") is None  # still blocked


def test_fetch_live_weather_kill_switch(monkeypatch):
    monkeypatch.setenv("TRUST_ROUTER_LIVE_DATA", "0")
    calls: list[str] = []
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http(calls))

    assert live_weather.fetch_live_weather("Bengaluru") is None
    assert calls == []


# --- fetcher unit tests (fx) --------------------------------------------------


def test_fetch_live_fx_parses_frankfurter(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(
        live_fx, "_http_get_json", lambda *a, **k: dict(FRANKFURTER)
    )

    result = live_fx.fetch_live_rate("USD", "INR")

    assert result is not None
    assert result["source"] == "live"
    assert result["rate"] == pytest.approx(83.12)
    assert result["inverse_rate"] == pytest.approx(1.0 / 83.12, abs=1e-6)
    assert result["rate_date"] == "2026-09-19"
    assert result["observed_at"].endswith("Z")


def test_fetch_live_fx_unsupported_pair_returns_none(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(
        live_fx, "_http_get_json", lambda *a, **k: {"base": "USD", "date": "2026-09-19", "rates": {}}
    )

    assert live_fx.fetch_live_rate("USD", "XYZ") is None


def test_fetch_live_fx_cache_hit(monkeypatch):
    _enable_live(monkeypatch)
    calls: list[str] = []

    def fake_get_json(url, params, timeout_s):
        calls.append(url)
        return dict(FRANKFURTER)

    monkeypatch.setattr(live_fx, "_http_get_json", fake_get_json)

    first = live_fx.fetch_live_rate("USD", "INR")
    second = live_fx.fetch_live_rate("usd", "inr")

    assert first["source"] == "live"
    assert second["source"] == "cached"
    assert len(calls) == 1


# --- handler integration --------------------------------------------------------


def test_primary_weather_serves_live_data_with_source_marker(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http([]))

    body = client.get("/primary/weather", params={"city": "Bengaluru"}).json()

    assert body["data_source"] == "live"
    assert body["temp_c"] == 21.5
    assert body["provider"] == "local-weather-primary-v1"


def test_primary_weather_silent_synthetic_fallback_when_live_fails(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(live_weather, "_http_get_json", lambda *a, **k: None)

    body = client.get("/primary/weather", params={"city": "Bengaluru"}).json()

    assert body["data_source"] == "synthetic"
    assert body["temp_c"] == 27.5  # curated synthetic value


def test_data_mode_synthetic_override_skips_live_entirely(monkeypatch):
    _enable_live(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http(calls))

    body = client.get(
        "/primary/weather", params={"city": "Bengaluru", "data_mode": "synthetic"}
    ).json()

    assert body["data_source"] == "synthetic"
    assert body["temp_c"] == 27.5
    assert calls == []  # no network attempt at all


def test_stale_fault_mode_layers_over_live_data(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http([]))
    client.post("/primary/mode", json={"mode": "stale_data", "category": "weather"})

    body = client.get("/primary/weather", params={"city": "Bengaluru"}).json()

    assert body["data_source"] == "live"  # real data answered…
    assert body["observed_at"].endswith("Z")
    assert body["observed_at"] != "2026-09-20T12:30:00Z"  # …with the injected staleness


def test_backup_weather_carries_top_level_data_source(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(live_weather, "_http_get_json", _mock_weather_http([]))

    body = client.get("/backup/weather", params={"city": "London"}).json()

    assert set(body["meta"]) == {"city_name", "provider"}  # nested schema unchanged
    assert body["data_source"] == "live"
    assert body["current"]["tempC"] == 21.5


def test_backup_fx_carries_top_level_data_source(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(
        live_fx, "_http_get_json", lambda *a, **k: dict(FRANKFURTER)
    )

    body = client.get("/backup/fx", params={"base": "USD", "quote": "INR"}).json()

    assert set(body["result"]) == {
        "from_currency",
        "to_currency",
        "mid",
        "rate_of_exchange",
        "as_of",
    }  # nested schema unchanged
    assert body["data_source"] == "live"
    assert body["result"]["mid"] == pytest.approx(83.12)


def test_primary_fx_carries_rate_date_when_live(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(
        live_fx, "_http_get_json", lambda *a, **k: dict(FRANKFURTER)
    )

    body = client.get("/primary/fx", params={"base": "USD", "quote": "INR"}).json()

    assert body["data_source"] == "live"
    assert body["rate_date"] == "2026-09-19"
    assert body["rate"] == pytest.approx(83.12)


def test_data_mode_endpoints(monkeypatch):
    # suite default is live (the env kill switch is what keeps tests offline)
    body = client.get("/data-mode", params={"category": "weather"}).json()
    assert body["data_mode"] == "live"
    assert body["category"] == "weather"

    body = client.post("/data-mode", json={"data_mode": "synthetic", "category": "fx"}).json()
    assert body["data_mode"] == "synthetic"
    assert client.get("/primary/fx", params={"base": "USD", "quote": "INR"}).json()[
        "data_source"
    ] == "synthetic"
    client.post("/data-mode", json={"data_mode": "live", "category": "fx"})

    assert client.post("/data-mode", json={"data_mode": "chaos"}).status_code == 422
    assert client.post("/data-mode", json={"data_mode": "live", "category": "chaos"}).status_code == 422
    assert client.get("/data-mode", params={"category": "chaos"}).status_code == 422


def test_invalid_data_mode_query_param_rejected():
    assert (
        client.get(
            "/primary/weather", params={"city": "Bengaluru", "data_mode": "chaos"}
        ).status_code
        == 422
    )
