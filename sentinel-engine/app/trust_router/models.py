"""Trust Router pydantic models.

Canonical response contract (weather, per MVP spec):
  {location, temperature_c, humidity_percent, condition, observed_at,
   source, fallback_used, trust_score, decision_reason}

Multi-category extension (additive): CanonicalResponse carries `category`
and a `metrics` map for category-specific values (FX: rate, inverse_rate).
Weather responses keep the exact flat fields above.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Outcome = Literal["primary", "fallback", "degraded"]
CheckStatus = Literal["pass", "fail"]
StepStatus = Literal["info", "ok", "fail"]
ScoreBand = Literal["trusted", "acceptable", "untrusted"]


class PolicyCheck(BaseModel):
    """One named policy evaluation with a human-readable reason."""

    id: str
    label: str
    status: CheckStatus
    detail: str


class TrustScoreComponent(BaseModel):
    """One attributable slice of the trust score."""

    id: str
    earned: int
    max: int
    detail: str


class TrustScore(BaseModel):
    """Explainable 0-100 score with hard-gate status."""

    total: int
    band: ScoreBand
    hard_gates_passed: bool
    failed_gates: list[str] = []
    components: list[TrustScoreComponent] = Field(default_factory=list)


class DecisionStep(BaseModel):
    """One entry in the auditable decision timeline."""

    t_ms: int
    step: str
    status: StepStatus
    detail: str
    at: str


class ProviderAttempt(BaseModel):
    """Evidence for one provider call. Raw bodies are never stored — only
    field NAMES; prohibited ones are moved to raw_fields_redacted."""

    role: Literal["primary", "backup"]
    provider: str
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    schema_valid: bool | None = None
    schema_errors: list[str] = Field(default_factory=list)
    raw_fields: list[str] = Field(default_factory=list)
    raw_fields_redacted: list[str] = Field(default_factory=list)
    trust_score: TrustScore | None = None


class CanonicalResponse(BaseModel):
    """The stable canonical response contract, generalized per category.

    Weather keeps the spec'd flat fields; other categories carry their
    canonical values in `metrics` (e.g. FX: rate, inverse_rate).
    """

    category: str = "weather"
    location: str | None = None
    temperature_c: float | None = None
    humidity_percent: int | None = None
    condition: str | None = None
    observed_at: str | None = None
    source: str
    fallback_used: bool
    trust_score: int
    decision_reason: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class TrustRouterResult(BaseModel):
    """Full auditable outcome of one trusted request."""

    request_id: str
    created_at: str
    category: str = "weather"
    city: str  # the requested location input (city or pair label)
    primary_mode: str | None = None
    outcome: Outcome
    fallback_used: bool
    decision_reason: str
    policy_checks: list[PolicyCheck] = Field(default_factory=list)
    trust_score: TrustScore
    attempts: list[ProviderAttempt] = Field(default_factory=list)
    decision_timeline: list[DecisionStep] = Field(default_factory=list)
    response: CanonicalResponse


class TrustRouterRequest(BaseModel):
    """Client input. Deliberately NO URLs: provider endpoints are pinned
    server-side to the local simulators.

    `city` is the original (weather) field name; `location` generalizes it.
    """

    city: str | None = Field(default=None, min_length=1, max_length=80)
    location: str | None = Field(default=None, min_length=1, max_length=80)
    category: str = "weather"


class PrimaryModeRequest(BaseModel):
    mode: str
    category: str = "weather"


class ProviderInfo(BaseModel):
    role: Literal["primary", "backup"]
    id: str
    url: str
    description: str
    modes: list[str] | None = None


class CategoryCatalogEntry(BaseModel):
    """One supported category with its approved local providers."""

    category: str
    label: str
    input_hint: str
    default_location: str
    primary: ProviderInfo
    backup: ProviderInfo


class ProvidersCatalog(BaseModel):
    """Catalog of all supported categories (provider-agnostic gateway)."""

    categories: list[CategoryCatalogEntry]


class PrimaryModeResponse(BaseModel):
    mode: str
    category: str = "weather"
    message: str | None = None
