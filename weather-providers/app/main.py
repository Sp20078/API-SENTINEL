"""FastAPI app for the local weather provider simulators (:8002).

Endpoints:
  GET  /health
  GET  /primary/weather?city=...      mode-switchable fault injector
  POST /primary/mode                  {"mode": healthy|slow_response|http_503|malformed_schema|stale_data}
  GET  /primary/mode
  GET  /backup/weather?city=...       fixed healthy provider, different JSON schema

Deliberately different schemas between the two providers so the Trust Router's
normalization layer has real work to do. 100% local and synthetic.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .data import weather_for
from .modes import VALID_MODES, get_mode, set_mode


class HealthResponse(BaseModel):
    status: str
    service: str
    primary_mode: str


class ModeSwitchRequest(BaseModel):
    mode: str


class ModeSwitchResponse(BaseModel):
    mode: str
    message: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="Weather Provider Simulators",
        description=(
            "Local-first synthetic weather providers for the API Sentinel Mesh "
            "Trust Router. Primary provider is mode-switchable to inject faults; "
            "backup provider is fixed and healthy with a different JSON schema."
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "weather-providers",
            "primary_mode": get_mode(),
        }

    # --- primary provider -------------------------------------------------
    @app.get("/primary/weather", tags=["primary"])
    def primary_weather(
        city: str = Query(min_length=1, max_length=80),
    ) -> dict[str, Any]:
        """Primary provider. Behavior depends on the current fault mode.

        Raw schema (canonical-adjacent on purpose):
          {city, temp_c, humidity, condition, observed_at, provider}
        """
        mode = get_mode()

        if mode == "http_503":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="primary weather provider temporarily unavailable (simulated)",
            )

        if mode == "slow_response":
            time.sleep(3.5)  # far past the router's 2000 ms latency budget

        data = weather_for(city)

        if mode == "malformed_schema":
            # Schema-invalid: drop a required field, wrong-type another, and
            # leak a prohibited internal field the policy engine must catch.
            return {
                "city": city,
                "temp_c": str(data["temp_c"]),  # wrong type: string, not number
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

    @app.post("/primary/mode", response_model=ModeSwitchResponse, tags=["primary"])
    def switch_mode(body: ModeSwitchRequest) -> dict[str, Any]:
        try:
            set_mode(body.mode)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            )
        return {"mode": get_mode(), "message": f"primary provider mode set to {get_mode()}"}

    @app.get("/primary/mode", response_model=ModeSwitchResponse, tags=["primary"])
    def read_mode() -> dict[str, Any]:
        return {"mode": get_mode(), "message": f"current primary provider mode is {get_mode()}"}

    # --- backup provider --------------------------------------------------
    @app.get("/backup/weather", tags=["backup"])
    def backup_weather(city: str = Query(min_length=1, max_length=80)) -> dict[str, Any]:
        """Backup provider: always healthy, deliberately different JSON schema.

        Raw schema (nested, different names — normalization required):
          {meta: {city_name, provider}, current: {tempC, relHumidity, sky, ts_iso},
           extra_field_ignored}
        """
        data = weather_for(city)
        return {
            "meta": {
                "city_name": city,
                "provider": "local-weather-backup-v1",
            },
            "current": {
                "tempC": data["temp_c"],
                "relHumidity": data["humidity"],
                "sky": data["condition"],
                "ts_iso": _now_iso(),
            },
            "extra_field_ignored": {"build": 7, "notes": "schema noise on purpose"},
        }

    return app


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


app = create_app()
