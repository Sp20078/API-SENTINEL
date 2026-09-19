"""Trust Router orchestration.

Flow:
  request → call primary (timed) → validate schema → evaluate policies
          → if all pass: return normalized primary response
          → else: call backup (timed) → validate → policies
                → if pass: return normalized backup response (fallback)
                → else: safe degraded response (no fabricated values)

Every stage appends to a decision timeline; the full record is auditable.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from .audit import audit_store
from .models import (
    DecisionStep,
    PolicyCheck,
    ProviderAttempt,
    TrustRouterResult,
    TrustScore,
    WeatherResponse,
)
from .normalizer import SchemaViolation, normalize, normalize_backup, normalize_primary
from .policies import (
    CHECK_LABELS,
    ProviderObservation,
    evaluate_policies,
    failed_gates,
    find_prohibited_fields,
)
from .providers import ProviderConfig, ProviderCall, call_provider
from .schema import REGISTRY, validate_backup_body

CATEGORY = "weather"

PRIMARY_PROVIDER_ID = "local-weather-primary-v1"
BACKUP_PROVIDER_ID = "local-weather-backup-v1"


class TrustRouter:
    """Configurable orchestrator; provider transports are injectable for tests."""

    def __init__(
        self,
        primary: ProviderConfig,
        backup: ProviderConfig,
        client_factory: Any = None,
        now_fn: Any = dt.datetime.now,
        mode_fn: Any = None,
    ) -> None:
        self.primary = primary
        self.backup = backup
        self._client_factory = client_factory or _default_client_factory()
        self._now_fn = now_fn
        self._mode_fn = mode_fn or _current_primary_mode

    # ------------------------------------------------------------------ flow
    def handle_request(self, city: str) -> TrustRouterResult:
        request_id = audit_store.next_request_id()
        started = self._now_fn()
        timeline: list[DecisionStep] = []
        attempts: list[ProviderAttempt] = []

        def now_ms() -> int:
            return int((self._now_fn() - started).total_seconds() * 1000)

        def iso_now() -> str:
            return self._now_fn().astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

        def step(t_ms: int, name: str, status: str, detail: str) -> None:
            timeline.append(DecisionStep(t_ms=t_ms, step=name, status=status, detail=detail, at=iso_now()))

        step(0, "request_received", "info", f"weather request for city={city}")

        with self._client_factory() as client:
            # ---- primary attempt -----------------------------------------
            primary_call = call_provider(client, self.primary, city)
            primary_obs = self._observe(self.primary, primary_call)
            primary_checks = evaluate_policies(primary_obs)
            primary_score = _score_or_zero(primary_obs)
            attempts.append(
                _attempt_from(self.primary, primary_call, primary_obs, primary_score)
            )

            step(
                now_ms(),
                "primary_call",
                "ok" if primary_call.status_code == 200 else "fail",
                _call_detail("primary", primary_call),
            )
            step(
                now_ms(),
                "primary_schema",
                "ok" if not primary_obs.schema_errors else "fail",
                _schema_detail("primary", primary_obs),
            )
            failed = failed_gates(primary_checks)
            if not failed:
                step(now_ms(), "primary_policies", "ok", "all policies pass")
            else:
                step(
                    now_ms(),
                    "primary_policies",
                    "fail",
                    _failed_detail(primary_checks),
                )

            if not failed:
                canonical = primary_obs.canonical
                assert canonical is not None  # all gates passed ⇒ canonical exists
                decision_reason = (
                    "primary accepted: all policies pass "
                    f"(trust {primary_score.total})"
                )
                step(
                    now_ms(),
                    "final_selection",
                    "ok",
                    f"primary accepted; fallback_used=false; trust {primary_score.total}",
                )
                result = self._result(
                    request_id=request_id,
                    created_at=iso_now(),
                    city=city,
                    outcome="primary",
                    fallback_used=False,
                    decision_reason=decision_reason,
                    policy_checks=primary_checks,
                    trust_score=primary_score,
                    attempts=attempts,
                    decision_timeline=timeline,
                    response=WeatherResponse(
                        location=canonical.location,
                        temperature_c=canonical.temperature_c,
                        humidity_percent=canonical.humidity_percent,
                        condition=canonical.condition,
                        observed_at=canonical.observed_at,
                        source=f"primary:{self.primary.provider_id}",
                        fallback_used=False,
                        trust_score=primary_score.total,
                        decision_reason=decision_reason,
                    ),
                )
                audit_store.put(result)
                return result

            step(
                now_ms(),
                "primary_rejected",
                "fail",
                f"hard gate failed ({', '.join(failed)}) → selecting backup provider",
            )

            # ---- backup attempt ------------------------------------------
            backup_call = call_provider(client, self.backup, city)
            backup_obs = self._observe(self.backup, backup_call)
            backup_checks = evaluate_policies(backup_obs)
            backup_score = _score_or_zero(backup_obs)
            attempts.append(
                _attempt_from(self.backup, backup_call, backup_obs, backup_score)
            )

            step(
                now_ms(),
                "backup_call",
                "ok" if backup_call.status_code == 200 else "fail",
                _call_detail("backup", backup_call),
            )
            step(
                now_ms(),
                "backup_validated",
                "ok" if not backup_obs.schema_errors and not failed_gates(backup_checks) else "fail",
                (
                    "schema valid, all policies pass"
                    if not backup_obs.schema_errors and not failed_gates(backup_checks)
                    else _failed_detail(backup_checks)
                ),
            )

            backup_failed = failed_gates(backup_checks)
            if not backup_failed:
                canonical = backup_obs.canonical
                assert canonical is not None
                primary_failure = _failure_summary(primary_call, primary_checks)
                decision_reason = (
                    f"primary rejected: {primary_failure}; "
                    f"backup accepted (trust {backup_score.total})"
                )
                step(
                    now_ms(),
                    "final_selection",
                    "ok",
                    f"backup accepted; fallback_used=true; trust {backup_score.total}",
                )
                result = self._result(
                    request_id=request_id,
                    created_at=iso_now(),
                    city=city,
                    outcome="fallback",
                    fallback_used=True,
                    decision_reason=decision_reason,
                    policy_checks=primary_checks,  # the checks that drove the decision
                    trust_score=backup_score,
                    attempts=attempts,
                    decision_timeline=timeline,
                    response=WeatherResponse(
                        location=canonical.location,
                        temperature_c=canonical.temperature_c,
                        humidity_percent=canonical.humidity_percent,
                        condition=canonical.condition,
                        observed_at=canonical.observed_at,
                        source=f"backup:{self.backup.provider_id}",
                        fallback_used=True,
                        trust_score=backup_score.total,
                        decision_reason=decision_reason,
                    ),
                )
                audit_store.put(result)
                return result

            # ---- both providers failed → safe degraded --------------------
            primary_failure = _failure_summary(primary_call, primary_checks)
            backup_failure = _failure_summary(backup_call, backup_checks)
            decision_reason = (
                f"unavailable: primary failed ({primary_failure}) and "
                f"backup failed ({backup_failure}); no fabricated values returned"
            )
            step(
                now_ms(),
                "degraded",
                "fail",
                "both providers failed → returning safe degraded response "
                "(no weather values fabricated)",
            )
            result = self._result(
                request_id=request_id,
                created_at=iso_now(),
                city=city,
                outcome="degraded",
                fallback_used=True,
                decision_reason=decision_reason,
                policy_checks=primary_checks,
                trust_score=TrustScore(total=0, band="untrusted", hard_gates_passed=False, failed_gates=failed),
                attempts=attempts,
                decision_timeline=timeline,
                response=WeatherResponse(
                    location=city,  # echoed from the request, never fabricated
                    temperature_c=None,
                    humidity_percent=None,
                    condition=None,
                    observed_at=None,
                    source="none",
                    fallback_used=True,
                    trust_score=0,
                    decision_reason=decision_reason,
                ),
            )
            audit_store.put(result)
            return result

    # ------------------------------------------------------------- internals
    def _observe(self, config: ProviderConfig, call: ProviderCall) -> ProviderObservation:
        """Validate + normalize one raw provider call into an observation."""
        role = config.role
        body = call.body
        schema_errors: list[str] = []
        canonical = None

        if call.status_code == 200 and body is not None:
            if role == "primary":
                schema_errors = REGISTRY.primary.validate(body)
                if not schema_errors:
                    try:
                        canonical = normalize_primary(body)
                    except SchemaViolation as exc:
                        schema_errors = [str(exc)]
            elif role == "backup":
                schema_errors = validate_backup_body(body)
                if not schema_errors:
                    try:
                        canonical = normalize_backup(body)
                    except SchemaViolation as exc:
                        schema_errors = [str(exc)]
        elif call.status_code == 200 and body is None:
            schema_errors = ["provider returned a non-JSON body"]

        return ProviderObservation(
            role=role,
            provider_id=config.provider_id,
            status_code=call.status_code,
            latency_ms=call.latency_ms,
            error=call.error,
            schema_errors=schema_errors,
            prohibited_found=find_prohibited_fields(body) if isinstance(body, dict) else [],
            canonical=canonical,
            raw_fields=_raw_field_names(body),
        )

    def _result(self, **kwargs: Any) -> TrustRouterResult:
        payload = dict(kwargs)
        payload["category"] = CATEGORY
        try:
            payload["primary_mode"] = self._mode_fn()
        except Exception:
            payload["primary_mode"] = None
        return TrustRouterResult(**payload)


# ---------------------------------------------------------------- helpers
def _score_or_zero(observation: ProviderObservation):
    from .scoring import compute_trust_score

    return compute_trust_score(observation)


def _default_client_factory():
    from .config import default_client_factory

    return default_client_factory()


def _call_detail(role: str, call: ProviderCall) -> str:
    if call.status_code is None:
        return f"{role} call failed: {call.error}"
    if call.status_code != 200:
        return f"{role} call returned HTTP {call.status_code}"
    return f"{role} provider responded 200 in {call.latency_ms} ms"


def _schema_detail(role: str, observation: ProviderObservation) -> str:
    if observation.schema_errors:
        return observation.schema_errors[0]
    return f"{role} schema valid"


def _failed_detail(checks: list[PolicyCheck]) -> str:
    failed = [check for check in checks if check.status == "fail"]
    return "; ".join(f"{CHECK_LABELS.get(check.id, check.id)}: {check.detail}" for check in failed)


def _failure_summary(call: ProviderCall, checks: list[PolicyCheck]) -> str:
    if call.status_code is None or call.status_code != 200:
        return call.error or f"HTTP {call.status_code}"
    failed = failed_gates(checks)
    return f"gate failed: {', '.join(failed)}" if failed else "policy failure"


def _raw_field_names(body: Any) -> list[str]:
    """Top-level (dotted for nested) field NAMES only — values are never stored."""
    if not isinstance(body, dict):
        return []

    def _walk(node: dict, prefix: str, out: list[str]) -> None:
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                _walk(value, path, out)
            else:
                out.append(path)

    names: list[str] = []
    _walk(body, "", names)
    return names


def _current_primary_mode() -> str | None:
    """Best-effort read of the simulator's current mode for the record."""
    try:
        import httpx as _httpx

        from .config import primary_mode_url

        response = _httpx.get(primary_mode_url(), timeout=1.0)
        if response.status_code == 200:
            mode = response.json().get("mode")
            return mode if isinstance(mode, str) else None
    except Exception:
        return None
    return None


def _attempt_from(
    config: ProviderConfig, call: ProviderCall, observation: ProviderObservation, score: Any
) -> ProviderAttempt:
    return ProviderAttempt(
        role=config.role,
        provider=config.provider_id,
        status_code=call.status_code,
        latency_ms=call.latency_ms,
        error=call.error,
        schema_valid=(not observation.schema_errors) if call.status_code == 200 else None,
        schema_errors=observation.schema_errors,
        raw_fields=observation.raw_fields,
        raw_fields_redacted=observation.prohibited_found,
        trust_score=score,
    )
