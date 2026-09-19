"""Per-category registry — the provider-agnostic core of the Trust Router.

Each supported category declares: its raw provider schemas (primary flat,
backup nested), a raw→canonical normalizer, a canonical response builder,
its canonical required-field list, env-var names for pinned URLs, and its
prohibited fields. Adding a category = one CategorySpec here (plus
simulator endpoints). Nothing else in the Trust Router is category-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .models import CanonicalResponse
from .normalizer import RawCanonical
from .schema import (
    FieldSpec,
    ProviderSchema,
    SchemaRegistry,
    validate_backup_body,
)

# ---------------------------------------------------------------------------
# shared normalizer plumbing
# ---------------------------------------------------------------------------


def _parse_pair(location: str) -> tuple[str, str]:
    """'USD/INR' → ('USD', 'INR'); raises ValueError on malformed input."""
    parts = [p.strip().upper() for p in location.split("/")]
    if len(parts) != 2 or len(parts[0]) != 3 or len(parts[1]) != 3:
        raise ValueError("fx location must look like 'USD/INR' (two 3-letter codes)")
    return parts[0], parts[1]


# --- weather -------------------------------------------------------------


def _normalize_weather_primary(body: dict[str, Any]) -> RawCanonical:
    from .normalizer import normalize_primary

    return normalize_primary(body)


def _normalize_weather_backup(body: dict[str, Any]) -> RawCanonical:
    from .normalizer import normalize_backup

    return normalize_backup(body)


def _validate_weather_backup(body: Any) -> list[str]:
    return validate_backup_body(body)


def _build_weather_canonical(
    raw: RawCanonical, source: str, fallback_used: bool, trust_score: int, reason: str
) -> CanonicalResponse:
    return CanonicalResponse(
        category="weather",
        location=raw.location,
        temperature_c=raw.temperature_c,
        humidity_percent=raw.humidity_percent,
        condition=raw.condition,
        observed_at=raw.observed_at,
        source=source,
        fallback_used=fallback_used,
        trust_score=trust_score,
        decision_reason=reason,
    )


# --- fx --------------------------------------------------------------------

FX_PRIMARY_SCHEMA = ProviderSchema(
    provider_id="local-fx-primary-v1",
    required_fields=(
        FieldSpec("base", str),
        FieldSpec("quote", str),
        FieldSpec("rate", (int, float)),
        FieldSpec("inverse_rate", (int, float)),
        FieldSpec("observed_at", str),
        FieldSpec("provider", str),
    ),
)


def _validate_fx_backup(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return ["response body is not a JSON object"]
    if "result" not in body or "service" not in body:
        return ["missing required field 'result'/'service'"]
    result = body["result"]
    if not isinstance(result, dict):
        return ["field 'result' expected dict"]
    errors: list[str] = []
    for spec in (
        FieldSpec("from_currency", str),
        FieldSpec("to_currency", str),
        FieldSpec("mid", (int, float)),
        FieldSpec("rate_of_exchange", (int, float)),
        FieldSpec("as_of", str),
    ):
        if spec.name not in result:
            errors.append(f"missing required field result.{spec.name!r}")
        elif not isinstance(result[spec.name], spec.type) or isinstance(result[spec.name], bool):
            got = type(result[spec.name]).__name__
            errors.append(
                f"field result.{spec.name!r} expected {spec.type.__name__}, got {got}"
            )
    service = body.get("service")
    if isinstance(service, dict):
        name = service.get("name")
        if not isinstance(name, str):
            errors.append("field service.name expected str")
    else:
        errors.append("field 'service' expected dict")
    return errors


def _normalize_fx_primary(body: dict[str, Any]) -> RawCanonical:
    from .normalizer import SchemaViolation

    try:
        return RawCanonical(
            location=f"{body['base']}/{body['quote']}",
            observed_at=str(body["observed_at"]),
            provider_id=str(body["provider"]),
            metrics={
                "rate": float(body["rate"]),
                "inverse_rate": float(body["inverse_rate"]),
            },
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaViolation(f"fx primary payload not normalizable: {exc}") from exc


def _normalize_fx_backup(body: dict[str, Any]) -> RawCanonical:
    from .normalizer import SchemaViolation

    try:
        result = body["result"]
        return RawCanonical(
            location=f"{result['from_currency']}/{result['to_currency']}",
            observed_at=str(result["as_of"]),
            provider_id=str(body["service"]["name"]),
            metrics={
                "rate": float(result["mid"]),
                "inverse_rate": float(result["rate_of_exchange"]),
            },
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchemaViolation(f"fx backup payload not normalizable: {exc}") from exc


def _build_fx_canonical(
    raw: RawCanonical, source: str, fallback_used: bool, trust_score: int, reason: str
) -> CanonicalResponse:
    return CanonicalResponse(
        category="fx",
        location=raw.location,
        observed_at=raw.observed_at,
        source=source,
        fallback_used=fallback_used,
        trust_score=trust_score,
        decision_reason=reason,
        metrics=dict(raw.metrics),
    )


# ---------------------------------------------------------------------------
# the spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CategorySpec:
    category: str
    label: str
    input_hint: str  # e.g. "City name" / "Pair like USD/INR"
    default_location: str
    required_canonical_fields: tuple[str, ...]
    primary_schema: ProviderSchema
    validate_backup: Callable[[Any], list[str]]
    normalize_primary: Callable[[dict[str, Any]], RawCanonical]
    normalize_backup: Callable[[dict[str, Any]], RawCanonical]
    build_canonical: Callable[
        [RawCanonical, str, bool, int, str], CanonicalResponse
    ]
    parse_location: Callable[[str], tuple[str, ...]]  # → provider query params
    query_param_names: tuple[str, ...]  # matching the parsed values
    env_primary_url: str
    env_backup_url: str
    env_primary_mode_url: str
    default_primary_url: str
    default_backup_url: str
    default_primary_mode_url: str
    prohibited_fields: tuple[str, ...] = field(
        default=("api_key", "internal_user_id", "customer_email")
    )


def _parse_weather(location: str) -> tuple[str, ...]:
    return (location,)


def _parse_fx(location: str) -> tuple[str, ...]:
    return _parse_pair(location)


WEATHER = CategorySpec(
    category="weather",
    label="Weather",
    input_hint="City name",
    default_location="Bengaluru",
    required_canonical_fields=("location", "temperature_c", "condition", "observed_at"),
    primary_schema=ProviderSchema(
        provider_id="local-weather-primary-v1",
        required_fields=(
            FieldSpec("city", str),
            FieldSpec("temp_c", (int, float)),
            FieldSpec("humidity", int),
            FieldSpec("condition", str),
            FieldSpec("observed_at", str),
            FieldSpec("provider", str),
        ),
    ),
    validate_backup=_validate_weather_backup,
    normalize_primary=_normalize_weather_primary,
    normalize_backup=_normalize_weather_backup,
    build_canonical=_build_weather_canonical,
    parse_location=_parse_weather,
    query_param_names=("city",),
    env_primary_url="TRUST_ROUTER_PRIMARY_URL",
    env_backup_url="TRUST_ROUTER_BACKUP_URL",
    env_primary_mode_url="TRUST_ROUTER_PRIMARY_MODE_URL",
    default_primary_url="http://127.0.0.1:8002/primary/weather",
    default_backup_url="http://127.0.0.1:8002/backup/weather",
    default_primary_mode_url="http://127.0.0.1:8002/primary/mode",
)

FX = CategorySpec(
    category="fx",
    label="Currency rates (FX)",
    input_hint="Currency pair like USD/INR",
    default_location="USD/INR",
    required_canonical_fields=("location", "rate", "observed_at"),
    primary_schema=FX_PRIMARY_SCHEMA,
    validate_backup=_validate_fx_backup,
    normalize_primary=_normalize_fx_primary,
    normalize_backup=_normalize_fx_backup,
    build_canonical=_build_fx_canonical,
    parse_location=_parse_fx,
    query_param_names=("base", "quote"),
    env_primary_url="TRUST_ROUTER_FX_PRIMARY_URL",
    env_backup_url="TRUST_ROUTER_FX_BACKUP_URL",
    env_primary_mode_url="TRUST_ROUTER_FX_PRIMARY_MODE_URL",
    default_primary_url="http://127.0.0.1:8002/primary/fx",
    default_backup_url="http://127.0.0.1:8002/backup/fx",
    default_primary_mode_url="http://127.0.0.1:8002/primary/mode",  # shared control endpoint
)

CATEGORIES: dict[str, CategorySpec] = {"weather": WEATHER, "fx": FX}


def get_category(category: str | None) -> CategorySpec:
    cat = (category or "weather").strip().lower()
    if cat not in CATEGORIES:
        valid = ", ".join(sorted(CATEGORIES))
        raise ValueError(f"unknown category {category!r}; supported categories: {valid}")
    return CATEGORIES[cat]
