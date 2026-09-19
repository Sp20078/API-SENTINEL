"""Shared mock provider server + state for Trust Router tests.

Serves weather AND fx categories on one ephemeral uvicorn; STATE is
module-level so tests can flip fault modes per category.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException

STATE: dict = {
    "primary_mode": "healthy",  # weather primary
    "primary_up": True,
    "backup_up": True,
    "leak_fields": [],  # extra prohibited fields merged into valid weather payloads
    "fx_mode": "healthy",  # fx primary
    "fx_up": True,
    "fx_backup_up": True,
    "fx_leak_fields": [],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stale_iso(minutes: int) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(minutes=minutes))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def build_mock_app() -> FastAPI:
    app = FastAPI()

    @app.get("/primary/weather")
    def primary(city: str):
        if not STATE["primary_up"]:
            raise HTTPException(status_code=503, detail="primary down")
        mode = STATE["primary_mode"]
        if mode == "http_503":
            raise HTTPException(status_code=503, detail="primary 503 (simulated)")
        if mode == "slow_response":
            time.sleep(2.2)  # just past the engine's 2.0 s read timeout
        payload = {
            "city": city,
            "temp_c": 27.5,
            "humidity": 64,
            "condition": "Partly cloudy",
            "observed_at": _now_iso(),
            "provider": "mock-primary",
        }
        if mode == "malformed_schema":
            payload = {
                "city": city,
                "temp_c": "27.5",  # wrong type
                "humidity": 64,
                "observed_at": _now_iso(),
                "provider": "mock-primary",
                "internal_user_id": "user-424242",  # prohibited
            }
        if mode == "stale_data":
            payload["observed_at"] = _stale_iso(90)
        for field in STATE["leak_fields"]:
            payload[field] = "leaked-value"
        return payload

    @app.get("/backup/weather")
    def backup(city: str):
        if not STATE["backup_up"]:
            raise HTTPException(status_code=503, detail="backup down")
        return {
            "meta": {"city_name": city, "provider": "mock-backup"},
            "current": {
                "tempC": 27.5,
                "relHumidity": 64,
                "sky": "Partly cloudy",
                "ts_iso": _now_iso(),
            },
            "extra_field_ignored": {"build": 7},
        }

    @app.get("/primary/fx")
    def primary_fx(base: str, quote: str):
        if not STATE["fx_up"]:
            raise HTTPException(status_code=503, detail="fx primary down")
        mode = STATE["fx_mode"]
        if mode == "http_503":
            raise HTTPException(status_code=503, detail="fx primary 503 (simulated)")
        if mode == "slow_response":
            time.sleep(2.2)
        payload = {
            "base": base,
            "quote": quote,
            "rate": 83.12,
            "inverse_rate": 0.012,
            "observed_at": _now_iso(),
            "provider": "mock-fx-primary",
        }
        if mode == "malformed_schema":
            payload = {
                "base": base,
                "quote": quote,
                "rate": "not-a-number",  # wrong type
                # 'inverse_rate' intentionally missing
                "observed_at": _now_iso(),
                "provider": "mock-fx-primary",
                "customer_email": "leak@example.com",  # prohibited
            }
        if mode == "stale_data":
            payload["observed_at"] = _stale_iso(90)
        for field in STATE["fx_leak_fields"]:
            payload[field] = "leaked-value"
        return payload

    @app.get("/backup/fx")
    def backup_fx(base: str, quote: str):
        if not STATE["fx_backup_up"]:
            raise HTTPException(status_code=503, detail="fx backup down")
        return {
            "result": {
                "from_currency": base,
                "to_currency": quote,
                "mid": 83.12,
                "rate_of_exchange": 0.012,
                "as_of": _now_iso(),
            },
            "service": {"name": "mock-fx-backup"},
            "disallowed_noise": "ignore me",
        }

    @app.get("/primary/mode")
    def read_mode(category: str = "weather"):
        key = "fx_mode" if category == "fx" else "primary_mode"
        return {"mode": STATE[key], "category": category}

    @app.post("/primary/mode")
    def write_mode(body: dict):
        mode = body.get("mode")
        category = body.get("category", "weather")
        if mode not in {"healthy", "slow_response", "http_503", "malformed_schema", "stale_data"}:
            raise HTTPException(status_code=422, detail="unknown mode")
        key = "fx_mode" if category == "fx" else "primary_mode"
        STATE[key] = mode
        return {"mode": mode, "category": category, "message": f"set to {mode}"}

    return app
