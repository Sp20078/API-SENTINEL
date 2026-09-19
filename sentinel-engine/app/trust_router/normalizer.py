"""Normalization: raw provider payloads → canonical WeatherResponse fields.

Each provider's raw schema is mapped to the stable canonical contract. The
normalizer assumes validation already succeeded (callers validate first) but
still raises SchemaViolation on anything un-mappable, with an exact reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class SchemaViolation(Exception):
    """Raw payload could not be normalized into the canonical contract."""


@dataclass(frozen=True)
class RawCanonical:
    """Canonical field values extracted from one provider's raw payload.

    Weather populates the flat fields; other categories (FX) populate
    `metrics` and leave the weather-specific fields as None.
    """

    location: str
    temperature_c: float | None = None
    humidity_percent: int | None = None
    condition: str | None = None
    observed_at: str = ""
    provider_id: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


def _parse_ts(value: str) -> datetime:
    ts = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_primary(body: dict[str, Any]) -> RawCanonical:
    try:
        temp = float(body["temp_c"])
        humidity = int(body["humidity"])
        return RawCanonical(
            location=str(body["city"]),
            temperature_c=temp,
            humidity_percent=humidity,
            condition=str(body["condition"]),
            observed_at=str(body["observed_at"]),
            provider_id=str(body["provider"]),
        )
    except SchemaViolation:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaViolation(f"primary payload not normalizable: {exc}") from exc


def normalize_backup(body: dict[str, Any]) -> RawCanonical:
    try:
        meta, current = body["meta"], body["current"]
        temp = float(current["tempC"])
        humidity = int(current["relHumidity"])
        return RawCanonical(
            location=str(meta["city_name"]),
            temperature_c=temp,
            humidity_percent=humidity,
            condition=str(current["sky"]),
            observed_at=str(current["ts_iso"]),
            provider_id=str(meta["provider"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaViolation(f"backup payload not normalizable: {exc}") from exc


def normalize(provider_role: str, body: dict[str, Any]) -> RawCanonical:
    if provider_role == "primary":
        return normalize_primary(body)
    if provider_role == "backup":
        return normalize_backup(body)
    raise SchemaViolation(f"unknown provider role {provider_role!r}")


def data_age_minutes(observed_at: str, now: datetime | None = None) -> float:
    """Age of an observed_at timestamp in minutes (0 if unparseable-future)."""
    reference = now or datetime.now(timezone.utc)
    try:
        parsed = _parse_ts(observed_at)
    except (ValueError, TypeError):
        return float("inf")  # unparseable timestamps are maximally stale
    age = (reference - parsed).total_seconds() / 60.0
    return max(age, 0.0)
