"""FastAPI app for the local provider simulators (:8002).

Weather (first category) and FX rates (second category, proving the Trust
Router gateway is provider-agnostic). For each category:
  /primary/...   mode-switchable fault injector
  /backup/...    fixed healthy provider with a deliberately different schema

Endpoints:
  GET  /health
  GET  /primary/weather?city=...        POST /primary/mode {"mode":..., "category":"weather"}
  GET  /backup/weather?city=...         GET  /primary/mode?category=weather
  GET  /primary/fx?base=...&quote=...   POST /primary/mode {"mode":..., "category":"fx"}
  GET  /backup/fx?base=...&quote=...    GET  /primary/mode?category=fx

100% local and synthetic.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .data import weather_for
from .fx_data import rate_for
from .modes import CATEGORIES, VALID_MODES, get_mode, set_mode


class HealthResponse(BaseModel):
    status: str
    service: str
    primary_mode: str
    category: str


class ModeSwitchRequest(BaseModel):
    mode: str
    category: str = "weather"


class ModeSwitchResponse(BaseModel):
    mode: str
    category: str
    message: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="Local Provider Simulators",
        description=(
            "Local-first synthetic providers for the API Sentinel Mesh Trust "
            "Router: weather and FX rates. Primary providers are mode-switchable "
            "fault injectors; backups are fixed and healthy with different JSON "
            "schemas."
        ),
        version="1.1.0",
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
        return {
            "status": "ok",
            "service": "provider-simulators",
            "primary_mode": get_mode(category),
            "category": category if category in CATEGORIES else "weather",
        }

    # --- weather primary ---------------------------------------------------
    @app.get("/primary/weather", tags=["primary"])
    def primary_weather(city: str = Query(min_length=1, max_length=80)) -> dict[str, Any]:
        """Primary weather provider. Raw schema:
        {city, temp_c, humidity, condition, observed_at, provider}"""
        mode = get_mode("weather")

        if mode == "http_503":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="primary weather provider temporarily unavailable (simulated)",
            )
        if mode == "slow_response":
            time.sleep(3.5)  # far past the router's 2000 ms latency budget

        data = weather_for(city)
        if mode == "malformed_schema":
            return {
                "city": city,
                "temp_c": str(data["temp_c"]),  # wrong type
                "humidity": data["humidity"],
                # 'condition' intentionally missing
                "observed_at": _now_iso(),
                "provider": "local-weather-primary-v1",
                "internal_user_id": "user-424242",  # prohibited field
            }

        observed_at = _now_iso()
        if mode == "stale_data":
            observed_at = _iso(datetime.now(timezone.utc) - timedelta(minutes=90))

        return {
            "city": city,
            "temp_c": data["temp_c"],
            "humidity": data["humidity"],
            "condition": data["condition"],
            "observed_at": observed_at,
            "provider": "local-weather-primary-v1",
        }

    # --- fx primary ----------------------------------------------------------
    @app.get("/primary/fx", tags=["primary"])
    def primary_fx(
        base: str = Query(min_length=3, max_length=3),
        quote: str = Query(min_length=3, max_length=3),
    ) -> dict[str, Any]:
        """Primary FX provider. Raw schema:
        {base, quote, rate, inverse_rate, observed_at, provider}"""
        mode = get_mode("fx")

        if mode == "http_503":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="primary fx provider temporarily unavailable (simulated)",
            )
        if mode == "slow_response":
            time.sleep(3.5)

        data = rate_for(base.upper(), quote.upper())
        if mode == "malformed_schema":
            return {
                "base": base.upper(),
                "quote": quote.upper(),
                "rate": "not-a-number",  # wrong type
                # 'inverse_rate' intentionally missing
                "observed_at": _now_iso(),
                "provider": "local-fx-primary-v1",
                "customer_email": "someone@example.com",  # prohibited field
            }

        observed_at = _now_iso()
        if mode == "stale_data":
            observed_at = _iso(datetime.now(timezone.utc) - timedelta(minutes=90))

        return {
            "base": base.upper(),
            "quote": quote.upper(),
            "rate": data["rate"],
            "inverse_rate": data["inverse_rate"],
            "observed_at": observed_at,
            "provider": "local-fx-primary-v1",
        }

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

    # --- weather backup ------------------------------------------------------
    @app.get("/backup/weather", tags=["backup"])
    def backup_weather(city: str = Query(min_length=1, max_length=80)) -> dict[str, Any]:
        """Backup weather provider (nested, deliberately different schema)."""
        data = weather_for(city)
        return {
            "meta": {"city_name": city, "provider": "local-weather-backup-v1"},
            "current": {
                "tempC": data["temp_c"],
                "relHumidity": data["humidity"],
                "sky": data["condition"],
                "ts_iso": _now_iso(),
            },
            "extra_field_ignored": {"build": 7, "notes": "schema noise on purpose"},
        }

    # --- fx backup -------------------------------------------------------------
    @app.get("/backup/fx", tags=["backup"])
    def backup_fx(
        base: str = Query(min_length=3, max_length=3),
        quote: str = Query(min_length=3, max_length=3),
    ) -> dict[str, Any]:
        """Backup FX provider — deliberately different schema:
        {result: {from_currency, to_currency, mid, rate_of_exchange, as_of},
         service: {name}, disallowed_noise}"""
        data = rate_for(base.upper(), quote.upper())
        return {
            "result": {
                "from_currency": base.upper(),
                "to_currency": quote.upper(),
                "mid": data["rate"],
                "rate_of_exchange": data["inverse_rate"],
                "as_of": _now_iso(),
            },
            "service": {"name": "local-fx-backup-v1"},
            "disallowed_noise": "deliberately unexpected top-level field",
        }

    return app


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


app = create_app()
