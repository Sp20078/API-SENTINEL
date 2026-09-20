"""FastAPI app for the local provider simulators (:8002).

Weather (first category) and FX rates (second category, proving the Trust
Router gateway is provider-agnostic). For each category:
  /primary/...   mode-switchable fault injector
  /backup/...    fixed healthy provider with a deliberately different schema

Data tiers (per category, resolved top-down on every request):
  live       — real data from free keyless upstreams (Open-Meteo / Frankfurter)
  cached     — a recent live answer reused within its TTL (or served while the
               network is flaky, ≤30 min old — still real data)
  synthetic  — the deterministic local generator (offline fallback)

The default tier is 'live' with silent fallback. Override per request with
?data_mode=synthetic|live, service-wide via POST /data-mode, or fully
offline via the TRUST_ROUTER_LIVE_DATA=0 env kill switch. Fault modes
(stale_data, http_503, slow_response, malformed_schema) inject on top of
whichever tier answered, so the Trust Router demo scenarios work over real
data too.

Endpoints:
  GET  /health
  GET  /primary/weather?city=...[&data_mode=...]     POST /primary/mode
  GET  /backup/weather?city=...[&data_mode=...]      GET  /primary/mode?category=...
  GET  /primary/fx?base=...&quote=...[&data_mode=...]
  GET  /backup/fx?base=...&quote=...[&data_mode=...]
  GET  /data-mode?category=...                       POST /data-mode

Only live_weather.py / live_fx.py reach the internet; everything else stays
local. 100% keyless, no accounts.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import data_mode, live_fx, live_weather
from .data import weather_for
from .fx_data import rate_for
from .modes import CATEGORIES, VALID_MODES, get_mode, set_mode


class HealthResponse(BaseModel):
    status: str
    service: str
    primary_mode: str
    category: str
    data_mode: str


class ModeSwitchRequest(BaseModel):
    mode: str
    category: str = "weather"


class ModeSwitchResponse(BaseModel):
    mode: str
    category: str
    message: str


class DataModeRequest(BaseModel):
    data_mode: Literal["live", "synthetic"]
    category: str = "weather"


class DataModeResponse(BaseModel):
    category: str
    data_mode: str
    message: str


DataModeParam = Literal["live", "synthetic"] | None


def _weather_values(city: str, tier: str) -> dict[str, Any]:
    """Resolve weather values for a city from the live → cached → synthetic chain.

    Returns {'temp_c', 'humidity', 'condition', 'observed_at', 'source'}.
    """
    if tier == "live":
        live = live_weather.fetch_live_weather(city)
        if live is not None:
            return {
                "temp_c": live["temp_c"],
                "humidity": live["humidity"],
                "condition": live["condition"],
                "observed_at": live["observed_at"],
                "source": live["source"],  # 'live' or 'cached'
            }
    values = weather_for(city)
    return {
        "temp_c": values["temp_c"],
        "humidity": values["humidity"],
        "condition": values["condition"],
        "observed_at": _now_iso(),
        "source": "synthetic",
    }


def _fx_values(base: str, quote: str, tier: str) -> dict[str, Any]:
    """Resolve FX values from the live → cached → synthetic chain.

    Returns {'rate', 'inverse_rate', 'observed_at', 'rate_date', 'source'}.
    """
    if tier == "live":
        live = live_fx.fetch_live_rate(base, quote)
        if live is not None:
            return {
                "rate": live["rate"],
                "inverse_rate": live["inverse_rate"],
                "observed_at": live["observed_at"],
                "rate_date": live.get("rate_date"),
                "source": live["source"],  # 'live' or 'cached'
            }
    values = rate_for(base.upper(), quote.upper())
    return {
        "rate": values["rate"],
        "inverse_rate": values["inverse_rate"],
        "observed_at": _now_iso(),
        "rate_date": None,
        "source": "synthetic",
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="Local Provider Simulators",
        description=(
            "Local-first providers for the API Sentinel Mesh Trust Router: "
            "weather and FX rates. Live-by-default over free keyless upstreams "
            "(Open-Meteo, Frankfurter/ECB) with a deterministic synthetic "
            "fallback. Primary providers are mode-switchable fault injectors; "
            "backups are fixed and healthy with different JSON schemas."
        ),
        version="1.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health(category: str = "weather") -> dict[str, Any]:
        cat = category if category in CATEGORIES else "weather"
        return {
            "status": "ok",
            "service": "provider-simulators",
            "primary_mode": get_mode(cat),
            "category": cat,
            "data_mode": data_mode.get_mode(cat),
        }

    # --- weather primary ---------------------------------------------------
    @app.get("/primary/weather", tags=["primary"])
    def primary_weather(
        city: str = Query(min_length=1, max_length=80),
        data_mode: DataModeParam = Query(default=None),
    ) -> dict[str, Any]:
        """Primary weather provider. Raw schema:
        {city, temp_c, humidity, condition, observed_at, provider, data_source}"""
        mode = get_mode("weather")

        if mode == "http_503":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="primary weather provider temporarily unavailable (simulated)",
            )
        if mode == "slow_response":
            time.sleep(3.5)  # far past the router's 2000 ms latency budget

        values = _weather_values(city, data_mode or data_mode_state("weather"))
        if mode == "malformed_schema":
            return {
                "city": city,
                "temp_c": str(values["temp_c"]),  # wrong type
                "humidity": values["humidity"],
                # 'condition' intentionally missing
                "observed_at": _now_iso(),
                "provider": "local-weather-primary-v1",
                "data_source": values["source"],
                "internal_user_id": "user-424242",  # prohibited field
            }

        observed_at = values["observed_at"]
        if mode == "stale_data":
            observed_at = _iso(datetime.now(timezone.utc) - timedelta(minutes=90))

        return {
            "city": city,
            "temp_c": values["temp_c"],
            "humidity": values["humidity"],
            "condition": values["condition"],
            "observed_at": observed_at,
            "provider": "local-weather-primary-v1",
            "data_source": values["source"],
        }

    # --- fx primary ----------------------------------------------------------
    @app.get("/primary/fx", tags=["primary"])
    def primary_fx(
        base: str = Query(min_length=3, max_length=3),
        quote: str = Query(min_length=3, max_length=3),
        data_mode: DataModeParam = Query(default=None),
    ) -> dict[str, Any]:
        """Primary FX provider. Raw schema:
        {base, quote, rate, inverse_rate, observed_at, provider, data_source,
         [rate_date when live/cached — the ECB publication date]}"""
        mode = get_mode("fx")

        if mode == "http_503":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="primary fx provider temporarily unavailable (simulated)",
            )
        if mode == "slow_response":
            time.sleep(3.5)

        values = _fx_values(base, quote, data_mode or data_mode_state("fx"))
        if mode == "malformed_schema":
            return {
                "base": base.upper(),
                "quote": quote.upper(),
                "rate": "not-a-number",  # wrong type
                # 'inverse_rate' intentionally missing
                "observed_at": _now_iso(),
                "provider": "local-fx-primary-v1",
                "data_source": values["source"],
                "customer_email": "someone@example.com",  # prohibited field
            }

        observed_at = values["observed_at"]
        if mode == "stale_data":
            observed_at = _iso(datetime.now(timezone.utc) - timedelta(minutes=90))

        payload: dict[str, Any] = {
            "base": base.upper(),
            "quote": quote.upper(),
            "rate": values["rate"],
            "inverse_rate": values["inverse_rate"],
            "observed_at": observed_at,
            "provider": "local-fx-primary-v1",
            "data_source": values["source"],
        }
        if values.get("rate_date"):
            payload["rate_date"] = values["rate_date"]
        return payload

    # --- mode control (per category) -----------------------------------------
    @app.post("/primary/mode", response_model=ModeSwitchResponse, tags=["primary"])
    def switch_mode(body: ModeSwitchRequest) -> dict[str, Any]:
        try:
            set_mode(body.mode, body.category)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        cat = body.category if body.category in CATEGORIES else "weather"
        return {
            "mode": get_mode(cat),
            "category": cat,
            "message": f"{cat} primary provider mode set to {get_mode(cat)}",
        }

    @app.get("/primary/mode", response_model=ModeSwitchResponse, tags=["primary"])
    def read_mode(category: str = "weather") -> dict[str, Any]:
        try:
            mode = get_mode(category)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        cat = category if category in CATEGORIES else "weather"
        return {"mode": mode, "category": cat, "message": f"current {cat} primary mode is {mode}"}

    # --- data-mode control (per category) --------------------------------------
    @app.get("/data-mode", response_model=DataModeResponse, tags=["system"])
    def read_data_mode(category: str = "weather") -> dict[str, Any]:
        try:
            current = data_mode.get_mode(category)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        cat = category if category in CATEGORIES else "weather"
        return {
            "category": cat,
            "data_mode": current,
            "message": f"current {cat} data mode is {current}",
        }

    @app.post("/data-mode", response_model=DataModeResponse, tags=["system"])
    def switch_data_mode(body: DataModeRequest) -> dict[str, Any]:
        try:
            current = data_mode.set_mode(body.data_mode, body.category)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        cat = body.category if body.category in CATEGORIES else "weather"
        return {
            "category": cat,
            "data_mode": current,
            "message": f"{cat} data mode set to {current}",
        }

    # --- weather backup ------------------------------------------------------
    @app.get("/backup/weather", tags=["backup"])
    def backup_weather(
        city: str = Query(min_length=1, max_length=80),
        data_mode: DataModeParam = Query(default=None),
    ) -> dict[str, Any]:
        """Backup weather provider (nested, deliberately different schema)."""
        values = _weather_values(city, data_mode or data_mode_state("weather"))
        return {
            "meta": {"city_name": city, "provider": "local-weather-backup-v1"},
            "current": {
                "tempC": values["temp_c"],
                "relHumidity": values["humidity"],
                "sky": values["condition"],
                "ts_iso": values["observed_at"],
            },
            "extra_field_ignored": {"build": 7, "notes": "schema noise on purpose"},
            "data_source": values["source"],
        }

    # --- fx backup -------------------------------------------------------------
    @app.get("/backup/fx", tags=["backup"])
    def backup_fx(
        base: str = Query(min_length=3, max_length=3),
        quote: str = Query(min_length=3, max_length=3),
        data_mode: DataModeParam = Query(default=None),
    ) -> dict[str, Any]:
        """Backup FX provider — deliberately different schema:
        {result: {from_currency, to_currency, mid, rate_of_exchange, as_of},
         service: {name}, disallowed_noise, data_source}"""
        values = _fx_values(base, quote, data_mode or data_mode_state("fx"))
        return {
            "result": {
                "from_currency": base.upper(),
                "to_currency": quote.upper(),
                "mid": values["rate"],
                "rate_of_exchange": values["inverse_rate"],
                "as_of": values["observed_at"],
            },
            "service": {"name": "local-fx-backup-v1"},
            "disallowed_noise": "deliberately unexpected top-level field",
            "data_source": values["source"],
        }

    return app


def data_mode_state(category: str) -> str:
    """Default data tier for a category (thin indirection for readability)."""
    return data_mode.get_mode(category)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


app = create_app()
