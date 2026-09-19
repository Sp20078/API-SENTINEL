"""Trust Router integration tests (API Sentinel Mesh, weather MVP scenarios).

Runs against a FRESH app built from build_trust_router_app() — deliberately
NOT the session-scoped scanner client — with provider HTTP served by a
shared in-thread mock uvicorn on an ephemeral loopback port (fixtures in
conftest_tr.py, mock in trust_mock.py). The slow scenario really exercises
the 2.0 s read timeout; everything else is fast.
"""

from __future__ import annotations

import uuid

import pytest

from tests.conftest_tr import (  # noqa: F401  (fixture registration)
    mock_providers,
    tr_client,
)
from tests.trust_mock import STATE, _now_iso, _stale_iso


def _request(client, city: str = "Bengaluru") -> dict:
    r = client.post("/trust-router/request", json={"city": city})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# The 7 required scenarios
# ---------------------------------------------------------------------------

def test_scenario_1_healthy_primary_used_without_fallback(tr_client) -> None:
    result = _request(tr_client)
    assert result["outcome"] == "primary"
    assert result["fallback_used"] is False
    assert result["response"]["source"] == "primary:local-weather-primary-v1"
    assert result["response"]["fallback_used"] is False
    # canonical normalized values come from the primary payload
    assert result["response"]["location"] == "Bengaluru"
    assert result["response"]["temperature_c"] == 27.5
    assert result["response"]["humidity_percent"] == 64
    assert result["response"]["condition"] == "Partly cloudy"
    assert result["response"]["observed_at"] is not None
    # healthy payload passes every gate with a full score
    assert result["trust_score"]["total"] == 100
    assert result["trust_score"]["hard_gates_passed"] is True
    check_ids = [c["id"] for c in result["policy_checks"]]
    assert check_ids == [
        "availability",
        "latency",
        "schema",
        "freshness",
        "required_fields",
        "prohibited_fields",
    ]
    assert all(c["status"] == "pass" for c in result["policy_checks"])
    # no backup attempt happened
    assert [a["role"] for a in result["attempts"]] == ["primary"]
    assert any(s["step"] == "final_selection" for s in result["decision_timeline"])


def test_scenario_2_slow_primary_triggers_backup(tr_client) -> None:
    STATE["primary_mode"] = "slow_response"  # 2.2 s > 2.0 s read timeout
    result = _request(tr_client)
    assert result["outcome"] == "fallback"
    assert result["fallback_used"] is True
    primary_attempt = result["attempts"][0]
    assert primary_attempt["role"] == "primary"
    assert primary_attempt["status_code"] is None  # timed out
    assert "timeout" in (primary_attempt["error"] or "").lower()
    assert result["response"]["source"] == "backup:local-weather-backup-v1"
    assert result["decision_reason"].startswith("primary rejected")
    steps = [s["step"] for s in result["decision_timeline"]]
    assert "primary_rejected" in steps and "backup_call" in steps


def test_scenario_3_http_503_triggers_backup(tr_client) -> None:
    STATE["primary_mode"] = "http_503"
    result = _request(tr_client)
    assert result["outcome"] == "fallback"
    assert result["fallback_used"] is True
    primary_attempt = result["attempts"][0]
    assert primary_attempt["status_code"] == 503
    availability = next(c for c in result["policy_checks"] if c["id"] == "availability")
    assert availability["status"] == "fail"
    assert "503" in availability["detail"]
    assert result["response"]["source"] == "backup:local-weather-backup-v1"
    assert result["decision_reason"].startswith("primary rejected")


def test_scenario_4_malformed_primary_schema_triggers_backup(tr_client) -> None:
    STATE["primary_mode"] = "malformed_schema"
    result = _request(tr_client)
    assert result["outcome"] == "fallback"
    primary_attempt = result["attempts"][0]
    assert primary_attempt["schema_valid"] is False
    assert primary_attempt["schema_errors"], "expected explicit schema errors"
    assert any("condition" in e for e in primary_attempt["schema_errors"])
    assert result["response"]["source"] == "backup:local-weather-backup-v1"
    assert result["fallback_used"] is True


def test_scenario_5_stale_primary_response_triggers_backup(tr_client) -> None:
    STATE["primary_mode"] = "stale_data"
    result = _request(tr_client)
    assert result["outcome"] == "fallback"
    freshness = next(c for c in result["policy_checks"] if c["id"] == "freshness")
    assert freshness["status"] == "fail"
    assert "90 min old" in freshness["detail"]
    primary_attempt = result["attempts"][0]
    # stale-but-valid data still scores high: only the freshness gate fails
    assert primary_attempt["trust_score"]["total"] == 85
    assert primary_attempt["trust_score"]["failed_gates"] == ["freshness"]
    assert primary_attempt["trust_score"]["hard_gates_passed"] is False
    assert result["response"]["source"] == "backup:local-weather-backup-v1"


def test_scenario_6_prohibited_field_triggers_backup(tr_client) -> None:
    STATE["leak_fields"] = ["api_key"]  # valid payload otherwise
    result = _request(tr_client)
    assert result["outcome"] == "fallback"
    primary_attempt = result["attempts"][0]
    assert primary_attempt["schema_valid"] is True  # schema itself is fine
    assert "api_key" in primary_attempt["raw_fields_redacted"]
    prohibited = next(
        c for c in result["policy_checks"] if c["id"] == "prohibited_fields"
    )
    assert prohibited["status"] == "fail"
    assert prohibited["detail"] == "prohibited field present: api_key"
    assert result["response"]["source"] == "backup:local-weather-backup-v1"


def test_scenario_7_both_providers_fail_returns_safe_degraded(tr_client) -> None:
    STATE["primary_mode"] = "http_503"
    STATE["backup_up"] = False
    result = _request(tr_client)
    assert result["outcome"] == "degraded"
    assert result["fallback_used"] is True
    response = result["response"]
    # no fabricated weather values anywhere
    assert response["temperature_c"] is None
    assert response["humidity_percent"] is None
    assert response["condition"] is None
    assert response["observed_at"] is None
    assert response["location"] == "Bengaluru"  # echoed from the request
    assert response["source"] == "none"
    assert response["trust_score"] == 0
    assert result["decision_reason"].startswith("unavailable:")
    assert "no fabricated values" in result["decision_reason"]
    assert result["trust_score"]["total"] == 0
    assert any(s["step"] == "degraded" for s in result["decision_timeline"])
    # both providers attempted
    assert [a["role"] for a in result["attempts"]] == ["primary", "backup"]


# ---------------------------------------------------------------------------
# Endpoint behavior: catalog, primary-mode proxy, audit
# ---------------------------------------------------------------------------

def test_providers_catalog(tr_client) -> None:
    r = tr_client.get("/trust-router/providers")
    assert r.status_code == 200
    body = r.json()
    categories = {entry["category"]: entry for entry in body["categories"]}
    assert set(categories) == {"weather", "fx"}
    weather = categories["weather"]
    assert weather["primary"]["role"] == "primary"
    assert weather["backup"]["role"] == "backup"
    assert set(weather["primary"]["modes"]) == {
        "healthy",
        "slow_response",
        "http_503",
        "malformed_schema",
        "stale_data",
    }
    assert weather["default_location"] == "Bengaluru"
    # provider URLs must be loopback — never anything remote
    for entry in categories.values():
        for side in ("primary", "backup"):
            url = entry[side]["url"]
            assert url.startswith("http://127.0.0.1") or url.startswith("http://localhost")


def test_primary_mode_proxy_roundtrip(tr_client) -> None:
    r = tr_client.post("/trust-router/primary-mode", json={"mode": "stale_data"})
    assert r.status_code == 200
    assert r.json()["mode"] == "stale_data"
    assert STATE["primary_mode"] == "stale_data"

    r = tr_client.post("/trust-router/primary-mode", json={"mode": "bogus"})
    assert r.status_code == 422


def test_audit_record_roundtrip(tr_client) -> None:
    result = _request(tr_client)
    request_id = result["request_id"]
    assert request_id.startswith("tr-req-")
    r = tr_client.get(f"/trust-router/audit/{request_id}")
    assert r.status_code == 200
    stored = r.json()
    assert stored["request_id"] == request_id
    assert stored["outcome"] == result["outcome"]
    assert stored["response"] == result["response"]
    assert len(stored["decision_timeline"]) >= 2
    # raw response bodies are never stored — only field names
    for attempt in stored["attempts"]:
        assert "body" not in attempt
        assert "raw_fields" in attempt


def test_audit_unknown_id_is_404(tr_client) -> None:
    r = tr_client.get("/trust-router/audit/tr-req-does-not-exist")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Unit-level determinism checks (no HTTP)
# ---------------------------------------------------------------------------

def test_policy_engine_latency_exceeded_but_200_fails_gate() -> None:
    from app.trust_router.models import TrustScore
    from app.trust_router.normalizer import RawCanonical
    from app.trust_router.policies import ProviderObservation, evaluate_policies, failed_gates
    from app.trust_router.scoring import compute_trust_score

    canonical = RawCanonical(
        location="X",
        temperature_c=1.0,
        humidity_percent=50,
        condition="Clear",
        observed_at=_now_iso(),
        provider_id="p",
    )
    obs = ProviderObservation(
        role="primary",
        provider_id="p",
        status_code=200,
        latency_ms=3412,  # over the 2000 ms budget with a real 200 response
        error=None,
        schema_errors=[],
        prohibited_found=[],
        canonical=canonical,
    )
    checks = evaluate_policies(obs)
    assert failed_gates(checks) == ["latency"]
    score = compute_trust_score(obs)
    assert isinstance(score, TrustScore)
    assert score.failed_gates == ["latency"]
    # 35 schema + 0 latency + 10 required + 10 prohibited + 15 freshness + 15 availability
    assert score.total == 85
    assert score.band == "trusted"  # 85 hits the trusted threshold, but the gate still failed


def test_guard_rejects_remote_and_credential_urls() -> None:
    from app.trust_router.guard import UnsafeProviderURLError, validate_provider_url

    with pytest.raises(UnsafeProviderURLError):
        validate_provider_url("https://api.openweathermap.org/data")
    with pytest.raises(UnsafeProviderURLError):
        validate_provider_url("http://example.com/weather")
    with pytest.raises(UnsafeProviderURLError):
        validate_provider_url("http://user:pass@127.0.0.1:8002/primary/weather")
    assert (
        validate_provider_url("http://127.0.0.1:8002/primary/weather")
        == "http://127.0.0.1:8002/primary/weather"
    )


def test_audit_store_fifo_cap_and_id_space() -> None:
    from app.trust_router.audit import AuditStore
    from app.trust_router.models import (
        CanonicalResponse,
        TrustRouterResult,
        TrustScore,
    )

    store = AuditStore(max_records=3)
    ids = [store.next_request_id() for _ in range(3)]
    assert ids[0] != ids[1] != ids[2]

    def make_valid(rid: str) -> TrustRouterResult:
        return TrustRouterResult(
            request_id=rid,
            created_at=_now_iso(),
            city="X",
            outcome="primary",
            fallback_used=False,
            decision_reason="test",
            trust_score=TrustScore(total=100, band="trusted", hard_gates_passed=True),
            response=CanonicalResponse(
                category="weather",
                source="primary:p",
                fallback_used=False,
                trust_score=100,
                decision_reason="test",
            ),
        )

    for rid in ids:
        store.put(make_valid(rid))
    store.put(make_valid("tr-req-0004"))
    assert store.get(ids[0]) is None  # FIFO evicted
    assert store.get("tr-req-0004") is not None
    assert store.get(uuid.uuid4().hex) is None  # unused unique key
