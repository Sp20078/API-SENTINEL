"""Provider-specific response schemas and the prohibited-field policy.

Each provider declares: required raw fields (with types), plus the canonical
fields normalization must produce. The prohibited-field list is a raw-payload
policy: any occurrence fails the primary provider before fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Raw fields that must never survive into (or onto) a trusted response.
PROHIBITED_RAW_FIELDS: tuple[str, ...] = ("api_key", "internal_user_id", "customer_email")


def _type_name(expected: type | tuple[type, ...]) -> str:
    """Human-readable name for a type or tuple-of-types spec."""
    if isinstance(expected, tuple):
        return "|".join(t.__name__ for t in expected)
    return expected.__name__


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: type  # python type expected in the JSON payload (int/float, str, int)


@dataclass(frozen=True)
class ProviderSchema:
    provider_id: str
    required_fields: tuple[FieldSpec, ...]

    def validate(self, body: Any) -> list[str]:
        """Return a list of schema violations (empty list = valid).

        Tolerates dict-typed bodies only; anything else is one violation.
        """
        if not isinstance(body, dict):
            return ["response body is not a JSON object"]
        errors: list[str] = []
        for spec in self.required_fields:
            if spec.name not in body:
                errors.append(f"missing required field {spec.name!r}")
            elif not isinstance(body[spec.name], spec.type) or isinstance(
                body[spec.name], bool
            ):
                got = type(body[spec.name]).__name__
                errors.append(
                    f"field {spec.name!r} expected {_type_name(spec.type)}, got {got}"
                )
        return errors

    def field_names(self) -> list[str]:
        return [spec.name for spec in self.required_fields]


@dataclass(frozen=True)
class SchemaRegistry:
    primary: ProviderSchema
    backup: ProviderSchema
    prohibited: tuple[str, ...] = field(default=PROHIBITED_RAW_FIELDS)


# Primary provider raw schema (weather-providers /primary/weather):
# {city, temp_c, humidity, condition, observed_at, provider}
PRIMARY_SCHEMA = ProviderSchema(
    provider_id="local-weather-primary-v1",
    required_fields=(
        FieldSpec("city", str),
        FieldSpec("temp_c", (int, float)),
        FieldSpec("humidity", int),
        FieldSpec("condition", str),
        FieldSpec("observed_at", str),
        FieldSpec("provider", str),
    ),
)

# Backup provider raw schema (weather-providers /backup/weather):
# {meta: {city_name, provider}, current: {tempC, relHumidity, sky, ts_iso},
#  extra_field_ignored} — nested, deliberately different names.
BACKUP_SCHEMA = ProviderSchema(
    provider_id="local-weather-backup-v1",
    required_fields=(
        FieldSpec("meta", dict),
        FieldSpec("current", dict),
    ),
)


def validate_backup_body(body: Any) -> list[str]:
    """Nested-schema validation for the backup provider payload."""
    errors = BACKUP_SCHEMA.validate(body)
    if errors:
        return errors
    if not isinstance(body, dict):  # narrowed for type-checkers
        return ["response body is not a JSON object"]
    meta, current = body["meta"], body["current"]
    for spec in (
        FieldSpec("city_name", str),
        FieldSpec("provider", str),
    ):
        if spec.name not in meta:
            errors.append(f"missing required field meta.{spec.name!r}")
        elif not isinstance(meta[spec.name], spec.type):
            errors.append(f"field meta.{spec.name!r} expected {spec.type.__name__}")
    for spec in (
        FieldSpec("tempC", (int, float)),
        FieldSpec("relHumidity", int),
        FieldSpec("sky", str),
        FieldSpec("ts_iso", str),
    ):
        if spec.name not in current:
            errors.append(f"missing required field current.{spec.name!r}")
        elif not isinstance(current[spec.name], spec.type) or isinstance(
            current[spec.name], bool
        ):
            got = type(current[spec.name]).__name__
            errors.append(
                f"field current.{spec.name!r} expected {_type_name(spec.type)}, got {got}"
            )
    return errors


REGISTRY = SchemaRegistry(primary=PRIMARY_SCHEMA, backup=BACKUP_SCHEMA)
