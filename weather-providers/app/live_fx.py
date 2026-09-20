"""Live FX rates via Frankfurter (free, keyless, ECB reference rates).

Same data-tier contract as live_weather.py: LIVE → CACHED → SYNTHETIC.

Frankfurter serves the European Central Bank's daily reference rates, so a
rate is published once per working day. `observed_at` is therefore stamped
with the *retrieval* instant (the moment this provider confirmed and served
the rate — which is what the freshness policy measures), while the honest
ECB publication date travels alongside as `rate_date` for the audit trail.

The inverse rate is computed as 1/rate (rounded to 6 dp), mirroring the
synthetic generator's convention. Unsupported pairs, timeouts, and malformed
bodies all return None so callers fall through silently. Only this module
and live_weather.py may leave localhost; the Trust Router engine and the
scanner remain 100% loopback-only. Disable with TRUST_ROUTER_LIVE_DATA=0.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"

_USER_AGENT = "api-sentinel-provider-simulators/1.0 (local demo tool)"

_CACHE_REUSE_TTL_S = 600.0   # serve cache without re-fetching for 10 minutes
_CACHE_FALLBACK_MAX_AGE_S = 1800.0  # stale cache is still honest data for 30 min
_BREAKER_COOLDOWN_S = 30.0   # after a failure, stop hitting the API for 30 s
_CACHE_MAX_ENTRIES = 256

_lock = threading.Lock()
_fx_cache: dict[str, tuple[float, dict[str, Any]]] = {}
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
    """Seconds one Frankfurter call may take (single request, no geocoding)."""
    try:
        return max(float(os.environ.get("TRUST_ROUTER_LIVE_TIMEOUT_S", "1.8")), 0.2)
    except ValueError:
        return 1.8


def cache_stats() -> dict[str, int]:
    with _lock:
        return {"fx": len(_fx_cache)}


def reset_cache() -> None:
    """Test hook: drop all cached state and reset the circuit breaker."""
    global _down_until
    with _lock:
        _fx_cache.clear()
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fetch_frankfurter(base: str, quote: str, budget_s: float) -> dict[str, Any] | None:
    """Frankfurter latest → {'rate','inverse_rate','observed_at','rate_date'} or None."""
    body = _http_get_json(
        FRANKFURTER_URL,
        {"base": base, "symbols": quote},
        budget_s,
    )
    rates = (body or {}).get("rates")
    if not isinstance(rates, dict) or quote not in rates:
        return None
    try:
        rate = float(rates[quote])
    except (TypeError, ValueError):
        return None
    if not rate > 0.0:
        return None
    rate_date = body.get("date") if isinstance(body, dict) else None
    return {
        "rate": round(rate, 6),
        "inverse_rate": round(1.0 / rate, 6),
        "observed_at": _now_iso(),
        "rate_date": rate_date if isinstance(rate_date, str) else None,
    }


def _cached(pair_key: str, now: float) -> dict[str, Any] | None:
    with _lock:
        entry = _fx_cache.get(pair_key)
    if entry is None:
        return None
    fetched_at, payload = entry
    if now - fetched_at <= _CACHE_FALLBACK_MAX_AGE_S:
        # Network is down; a ≤30-min-old live rate is still real data —
        # the Trust Router's freshness policy stays the honest judge.
        return {**payload, "source": "cached"}
    return None


def fetch_live_rate(base: str, quote: str) -> dict[str, Any] | None:
    """Best-effort live FX rate for a currency pair.

    Returns {'rate','inverse_rate','observed_at','rate_date','source'} where
    source is 'live' or 'cached', or None when synthetic should be used.
    Never raises; never takes longer than ~live_timeout_s().
    """
    if not live_enabled():
        return None
    pair_key = f"{base.upper()}/{quote.upper()}"
    now = time.monotonic()

    with _lock:
        entry = _fx_cache.get(pair_key)
    if entry is not None and now - entry[0] <= _CACHE_REUSE_TTL_S:
        return {**entry[1], "source": "cached"}

    global _down_until
    with _lock:
        breaker_open = now < _down_until
    if breaker_open:
        return _cached(pair_key, now)

    payload = _fetch_frankfurter(base.upper(), quote.upper(), live_timeout_s())
    if payload is None:
        with _lock:
            _down_until = time.monotonic() + _BREAKER_COOLDOWN_S
        return _cached(pair_key, time.monotonic())

    with _lock:
        _down_until = 0.0
        if len(_fx_cache) >= _CACHE_MAX_ENTRIES:
            _fx_cache.clear()
        _fx_cache[pair_key] = (time.monotonic(), payload)
    return {**payload, "source": "live"}
