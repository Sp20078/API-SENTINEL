"""Live weather data via Open-Meteo (free, keyless, no signup).

First tier of the provider data chain: LIVE → CACHED → SYNTHETIC.

  live      — Open-Meteo answered now; real observation + real WMO condition
  cached    — a recent live answer (≤10 min) reused without re-hitting the
              API, or (≤30 min) served while the network is flaky so the
              Trust Router's own freshness policy stays the honest judge
  synthetic — callers fall back to the deterministic generator (data.py)

Any failure (timeout, DNS, bad status, unknown city, malformed body) returns
None so the caller falls through silently — the demo never breaks because
the internet does. Only this module and live_fx.py may leave localhost;
the Trust Router engine and the scanner remain 100% loopback-only.
Disable entirely with TRUST_ROUTER_LIVE_DATA=0.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_USER_AGENT = "api-sentinel-provider-simulators/1.0 (local demo tool)"

_CACHE_REUSE_TTL_S = 600.0   # serve cache without re-fetching for 10 minutes
_CACHE_FALLBACK_MAX_AGE_S = 1800.0  # stale cache is still honest data for 30 min
_BREAKER_COOLDOWN_S = 30.0   # after a failure, stop hitting the API for 30 s
_CACHE_MAX_ENTRIES = 256

# WMO weather interpretation codes → human conditions (real values, not the
# synthetic generator's five curated strings).
_WMO_CONDITIONS: dict[int, str] = {
    0: "Clear",
    1: "Clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Fog",
    51: "Light drizzle",
    53: "Light drizzle",
    55: "Light drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent rain showers",
    85: "Snow showers",
    86: "Snow showers",
    95: "Thunderstorms",
    96: "Thunderstorms with hail",
    99: "Thunderstorms with hail",
}

_lock = threading.Lock()
_weather_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_geocode_cache: dict[str, tuple[float, float]] = {}
_down_until = 0.0  # circuit breaker: monotonic time until which live is skipped


def live_enabled() -> bool:
    """Env kill switch — TRUST_ROUTER_LIVE_DATA=0 forces fully-offline mode."""
    return os.environ.get("TRUST_ROUTER_LIVE_DATA", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def live_timeout_s() -> float:
    """Total seconds the live chain (geocode + forecast) may take.

    Must fit inside the Trust Router's 2.0 s provider read timeout, so the
    default is 1.8 s split across the two calls.
    """
    try:
        return max(float(os.environ.get("TRUST_ROUTER_LIVE_TIMEOUT_S", "1.8")), 0.2)
    except ValueError:
        return 1.8


def cache_stats() -> dict[str, int]:
    with _lock:
        return {"weather": len(_weather_cache), "geocode": len(_geocode_cache)}


def reset_cache() -> None:
    """Test hook: drop all cached state and reset the circuit breaker."""
    global _down_until
    with _lock:
        _weather_cache.clear()
        _geocode_cache.clear()
        _down_until = 0.0


def _http_get_json(url: str, params: dict[str, str], timeout_s: float) -> dict[str, Any] | None:
    """One GET → JSON dict, or None on any failure. Test seam: monkeypatch me."""
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                return None
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return body if isinstance(body, dict) else None


def _geocode(city: str, timeout_s: float) -> tuple[float, float] | None:
    """City name → (lat, lon). Geocode results are cached forever (cities don't move)."""
    key = city.strip().lower()
    with _lock:
        hit = _geocode_cache.get(key)
    if hit is not None:
        return hit
    body = _http_get_json(
        GEOCODE_URL,
        {"name": city, "count": "1", "language": "en", "format": "json"},
        timeout_s,
    )
    coords: tuple[float, float] | None = None
    results = (body or {}).get("results") or []
    if results and isinstance(results[0], dict):
        try:
            coords = (float(results[0]["latitude"]), float(results[0]["longitude"]))
        except (KeyError, TypeError, ValueError):
            coords = None
    with _lock:
        if len(_geocode_cache) >= _CACHE_MAX_ENTRIES:
            _geocode_cache.clear()
        _geocode_cache[key] = coords  # negative results cached too (unknown city)
    return coords


def _observed_iso(current: dict[str, Any]) -> str | None:
    """Open-Meteo 'current.time' (requested in UTC, e.g. 2026-09-20T12:30) → ISO Z."""
    raw_time = current.get("time")
    if not isinstance(raw_time, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw_time.strip()).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    # `timezone=UTC` guarantees the timestamp is UTC; guard against offsets anyway.
    offset_seconds = current.get("utc_offset_seconds") or 0
    try:
        parsed = parsed - timedelta(seconds=int(offset_seconds))
    except (TypeError, ValueError):
        pass
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _fetch_open_meteo(city: str, budget_s: float) -> dict[str, Any] | None:
    """Geocode + current conditions → {'temp_c','humidity','condition','observed_at'} or None."""
    per_call = max(budget_s / 2.0, 0.1)
    coords = _geocode(city, per_call)
    if coords is None:
        return None
    body = _http_get_json(
        FORECAST_URL,
        {
            "latitude": f"{coords[0]:.4f}",
            "longitude": f"{coords[1]:.4f}",
            "current": "temperature_2m,relative_humidity_2m,weather_code",
            "timezone": "UTC",
        },
        per_call,
    )
    current = (body or {}).get("current")
    if not isinstance(current, dict):
        return None
    observed_at = _observed_iso(current)
    if observed_at is None:
        return None
    try:
        temp_c = round(float(current["temperature_2m"]), 1)
        humidity = int(round(float(current["relative_humidity_2m"])))
    except (KeyError, TypeError, ValueError):
        return None
    code = current.get("weather_code")
    condition = (
        _WMO_CONDITIONS.get(int(code), "Unknown") if isinstance(code, (int, float)) else "Unknown"
    )
    if humidity < 0 or humidity > 100:
        return None
    return {
        "temp_c": temp_c,
        "humidity": humidity,
        "condition": condition,
        "observed_at": observed_at,
    }


def _cached(city_key: str, now: float) -> dict[str, Any] | None:
    with _lock:
        entry = _weather_cache.get(city_key)
    if entry is None:
        return None
    fetched_at, payload = entry
    if now - fetched_at <= _CACHE_REUSE_TTL_S:
        return {**payload, "source": "cached"}
    if now - fetched_at <= _CACHE_FALLBACK_MAX_AGE_S:
        # Network is down; a ≤30-min-old live reading is still real data —
        # the Trust Router's freshness policy stays the honest judge.
        return {**payload, "source": "cached"}
    return None


def fetch_live_weather(city: str) -> dict[str, Any] | None:
    """Best-effort live weather for a city.

    Returns {'temp_c','humidity','condition','observed_at','source'} where
    source is 'live' or 'cached', or None when synthetic should be used.
    Never raises; never takes longer than ~live_timeout_s().
    """
    if not live_enabled():
        return None
    city_key = city.strip().lower()
    now = time.monotonic()

    with _lock:
        entry = _weather_cache.get(city_key)
    if entry is not None and now - entry[0] <= _CACHE_REUSE_TTL_S:
        return {**entry[1], "source": "cached"}

    global _down_until
    with _lock:
        breaker_open = now < _down_until
    if breaker_open:
        return _cached(city_key, now)

    payload = _fetch_open_meteo(city.strip(), live_timeout_s())
    if payload is None:
        with _lock:
            _down_until = time.monotonic() + _BREAKER_COOLDOWN_S
        return _cached(city_key, time.monotonic())

    with _lock:
        _down_until = 0.0
        if len(_weather_cache) >= _CACHE_MAX_ENTRIES:
            _weather_cache.clear()
        _weather_cache[city_key] = (time.monotonic(), payload)
    return {**payload, "source": "live"}
