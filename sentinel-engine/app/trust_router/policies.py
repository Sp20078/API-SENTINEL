"""Policy evaluation for the Trust Router.

Policies (spec):
  max_latency_ms: 2000
  max_data_age_minutes: 30
  required canonical fields: location, temperature_c, condition, observed_at
  prohibited raw fields: api_key, internal_user_id, customer_email

Each check yields a stable id, a pass/fail status, and a human-readable
reason string used verbatim in the UI and asserted in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import PolicyCheck
from .normalizer import RawCanonical, data_age_minutes
from .schema import PROHIBITED_RAW_FIELDS

MAX_LATENCY_MS = 2000
MAX_DATA_AGE_MINUTES = 30.0


def canonical_value(canonical: "RawCanonical", name: str) -> Any:
    """Read a canonical field: flat attribute first, then the metrics map."""
    value = getattr(canonical, name, None)
    if value is None and canonical.metrics:
        return canonical.metrics.get(name)
    return value

CHECK_LABELS = {
    "availability": "Primary reachable",
    "latency": "Latency ≤ 2000 ms",
    "schema": "Provider schema valid",
    "freshness": "Freshness ≤ 30 min",
    "required_fields": "Required canonical fields",
    "prohibited_fields": "No prohibited fields",
}


@dataclass(frozen=True)
class ProviderObservation:
    """Everything the policy engine needs about one provider attempt."""

    role: str  # "primary" | "backup"
    provider_id: str
    status_code: int | None
    latency_ms: int
    error: str | None
    schema_errors: list[str] = field(default_factory=list)
    prohibited_found: list[str] = field(default_factory=list)
    canonical: RawCanonical | None = None
    raw_fields: list[str] = field(default_factory=list)
    data_source: str | None = None  # provider's own provenance marker


def _check(
    check_id: str, passed: bool, detail: str, checks: list[PolicyCheck]
) -> bool:
    checks.append(
        PolicyCheck(
            id=check_id,
            label=CHECK_LABELS[check_id],
            status="pass" if passed else "fail",
            detail=detail,
        )
    )
    return passed


def find_prohibited_fields(
    body: Any,
    prohibited: tuple[str, ...] = PROHIBITED_RAW_FIELDS,
) -> list[str]:
    """Return prohibited raw-field names present anywhere in the payload.

    Recurses into nested objects so leaked secrets cannot hide in sub-objects
    (e.g. the backup provider's meta/current nesting).
    """
    forbidden = set(prohibited)
    found: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key in forbidden:
                    found.append(key)
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(body)
    seen: set[str] = set()
    ordered = [name for name in found if not (name in seen or seen.add(name))]
    return ordered


def evaluate_policies(
    observation: ProviderObservation,
    required_canonical_fields: tuple[str, ...] = (
        "location",
        "temperature_c",
        "condition",
        "observed_at",
    ),
) -> list[PolicyCheck]:
    """Evaluate all six policy checks for one provider observation."""
    now = datetime.now(timezone.utc)
    checks: list[PolicyCheck] = []
    role = observation.role

    # 1. availability -------------------------------------------------------
    if observation.status_code == 200:
        _check(
            "availability",
            True,
            f"HTTP 200 from {role} in {observation.latency_ms} ms",
            checks,
        )
    elif observation.error:
        _check("availability", False, observation.error, checks)
    else:
        _check(
            "availability",
            False,
            f"HTTP {observation.status_code} from {role}",
            checks,
        )

    # 2. latency ------------------------------------------------------------
    if observation.status_code == 200 and observation.latency_ms <= MAX_LATENCY_MS:
        _check(
            "latency",
            True,
            f"{observation.latency_ms} ms ≤ {MAX_LATENCY_MS} ms budget",
            checks,
        )
    elif observation.status_code == 200:
        _check(
            "latency",
            False,
            f"{observation.latency_ms} ms > {MAX_LATENCY_MS} ms budget",
            checks,
        )
    else:
        _check(
            "latency",
            False,
            f"latency not evaluable — provider unavailable ({observation.error or observation.status_code})",
            checks,
        )

    # 3. schema -------------------------------------------------------------
    if observation.schema_errors:
        _check("schema", False, observation.schema_errors[0], checks)
    else:
        _check("schema", True, f"{role} schema valid", checks)

    # 4. freshness ----------------------------------------------------------
    if observation.canonical is not None:
        age = data_age_minutes(observation.canonical.observed_at, now)
        if age <= MAX_DATA_AGE_MINUTES:
            _check(
                "freshness",
                True,
                f"observed_at is {max(int(age), 0)} min old (≤ 30 min budget)",
                checks,
            )
        else:
            _check(
                "freshness",
                False,
                f"observed_at is {int(age)} min old (> 30 min budget)",
                checks,
            )
    else:
        _check("freshness", False, "freshness not evaluable — no valid payload", checks)

    # 5. required canonical fields -------------------------------------------
    if observation.canonical is not None:
        missing = [
            name
            for name in required_canonical_fields
            if canonical_value(observation.canonical, name) in (None, "")
        ]
        if not missing:
            _check(
                "required_fields",
                True,
                f"{len(required_canonical_fields)}/{len(required_canonical_fields)} canonical fields present",
                checks,
            )
        else:
            _check(
                "required_fields",
                False,
                f"missing canonical field {missing[0]!r}",
                checks,
            )
    else:
        _check(
            "required_fields",
            False,
            "required fields not evaluable — no valid payload",
            checks,
        )

    # 6. prohibited raw fields ------------------------------------------------
    if observation.prohibited_found:
        _check(
            "prohibited_fields",
            False,
            f"prohibited field present: {observation.prohibited_found[0]}",
            checks,
        )
    else:
        _check("prohibited_fields", True, "no prohibited fields found", checks)

    return checks


def failed_gates(checks: list[PolicyCheck]) -> list[str]:
    return [check.id for check in checks if check.status == "fail"]
