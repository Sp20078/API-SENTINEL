"""Deterministic, explainable trust score (0-100).

Components (weights from the approved payload spec):
  schema_valid 35 · latency 15 · required_fields 10 · prohibited_fields 10
  freshness 15 · availability 15

Hard gates drive fallback; the score explains it. If a gate fails, the
matching component earns 0 and the gate id lands in failed_gates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import TrustScore, TrustScoreComponent
from .normalizer import data_age_minutes
from .policies import MAX_LATENCY_MS, MAX_DATA_AGE_MINUTES

if TYPE_CHECKING:
    from .policies import ProviderObservation

WEIGHTS = {
    "schema_valid": 35,
    "latency": 15,
    "required_fields": 10,
    "prohibited_fields": 10,
    "freshness": 15,
    "availability": 15,
}


def _freshness_points(age_min: float) -> int:
    """Linear decay: 15 points at age 0 → 0 points at 60 minutes."""
    if age_min >= 60:
        return 0
    return max(int(round(15 * (1 - age_min / 60.0))), 0)


def compute_trust_score(
    observation: "ProviderObservation",
    required_count: int = 4,
) -> TrustScore:
    now_observed = observation.canonical is not None
    age = (
        data_age_minutes(observation.canonical.observed_at)
        if now_observed
        else float("inf")
    )
    available = observation.status_code == 200
    latency_ok = available and observation.latency_ms <= MAX_LATENCY_MS
    schema_ok = not observation.schema_errors
    fresh = now_observed and age <= MAX_DATA_AGE_MINUTES

    components: list[TrustScoreComponent] = [
        TrustScoreComponent(
            id="schema_valid",
            earned=WEIGHTS["schema_valid"] if schema_ok else 0,
            max=WEIGHTS["schema_valid"],
            detail=(
                f"{observation.role} schema valid"
                if schema_ok
                else observation.schema_errors[0]
            ),
        ),
        TrustScoreComponent(
            id="latency",
            earned=WEIGHTS["latency"] if latency_ok else 0,
            max=WEIGHTS["latency"],
            detail=(
                f"{observation.latency_ms} ms ≤ {MAX_LATENCY_MS} ms"
                if latency_ok
                else (
                    f"{observation.latency_ms} ms > {MAX_LATENCY_MS} ms"
                    if available
                    else "latency not evaluable — provider unavailable"
                )
            ),
        ),
        TrustScoreComponent(
            id="required_fields",
            earned=WEIGHTS["required_fields"] if now_observed else 0,
            max=WEIGHTS["required_fields"],
            detail=(
                f"{required_count}/{required_count} canonical fields present"
                if now_observed
                else "no valid payload"
            ),
        ),
        TrustScoreComponent(
            id="prohibited_fields",
            earned=0 if observation.prohibited_found else WEIGHTS["prohibited_fields"],
            max=WEIGHTS["prohibited_fields"],
            detail=(
                f"prohibited field present: {observation.prohibited_found[0]}"
                if observation.prohibited_found
                else "none found"
            ),
        ),
        TrustScoreComponent(
            id="freshness",
            earned=_freshness_points(age) if now_observed else 0,
            max=WEIGHTS["freshness"],
            detail=(
                f"observed_at {int(age)} min old" if now_observed else "no valid payload"
            ),
        ),
        TrustScoreComponent(
            id="availability",
            earned=WEIGHTS["availability"] if available else 0,
            max=WEIGHTS["availability"],
            detail=(
                f"HTTP {observation.status_code}"
                if observation.status_code is not None
                else (observation.error or "no response")
            ),
        ),
    ]

    total = sum(c.earned for c in components)
    band: str = "trusted" if total >= 85 else "acceptable" if total >= 60 else "untrusted"

    failed_gates: list[str] = []
    if not available:
        failed_gates.append("availability")
    if not latency_ok:
        failed_gates.append("latency")
    if not schema_ok:
        failed_gates.append("schema")
    if not fresh:
        failed_gates.append("freshness")
    if not now_observed:
        failed_gates.append("required_fields")
    if observation.prohibited_found:
        failed_gates.append("prohibited_fields")

    return TrustScore(
        total=total,
        band=band,  # type: ignore[arg-type]
        hard_gates_passed=not failed_gates,
        failed_gates=failed_gates,
        components=components,
    )
