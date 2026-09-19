"""FX category tests (API Sentinel Mesh) — proving the Trust Router gateway
is provider-agnostic: same policy engine, same score, same audit trail, a
different provider schema and canonical shape.

Uses the same isolated fresh-app + mock provider fixtures as the weather
suite (see STATE/build_mock_app in test_trust_router.py).
"""

from __future__ import annotations

from tests.conftest_tr import (  # noqa: F401  (fixture registration)
    mock_providers,
    tr_client,
)
from tests.test_trust_router import _request  # weather helper (regression test)
from tests.trust_mock import STATE


def _fx_request(client, location: str = "USD/INR") -> dict:
    r = client.post(
        "/trust-router/request", json={"location": location, "category": "fx"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_fx_healthy_primary_used_without_fallback(tr_client) -> None:
    result = _fx_request(tr_client)
    assert result["category"] == "fx"
    assert result["outcome"] == "primary"
    assert result["fallback_used"] is False
    assert result["response"]["source"] == "primary:local-fx-primary-v1"
    assert result["response"]["category"] == "fx"
    # canonical FX shape: pair in location, values in metrics
    assert result["response"]["location"] == "USD/INR"
    assert result["response"]["metrics"]["rate"] == 83.12
    assert result["response"]["metrics"]["inverse_rate"] == 0.0120
    assert result["response"]["temperature_c"] is None  # weather fields untouched
    assert result["trust_score"]["total"] == 100
    assert result["trust_score"]["hard_gates_passed"] is True
    assert all(c["status"] == "pass" for c in result["policy_checks"])
    assert [a["role"] for a in result["attempts"]] == ["primary"]


def test_fx_malformed_schema_and_prohibited_field_triggers_backup(tr_client) -> None:
    STATE["fx_mode"] = "malformed_schema"
    result = _fx_request(tr_client)
    assert result["outcome"] == "fallback"
    primary_attempt = result["attempts"][0]
    assert primary_attempt["schema_valid"] is False
    assert any("inverse_rate" in e for e in primary_attempt["schema_errors"])
    assert any("rate" in e for e in primary_attempt["schema_errors"])
    # the FX primary leaks customer_email — the prohibited-field check must fire
    prohibited = next(
        c for c in result["policy_checks"] if c["id"] == "prohibited_fields"
    )
    assert prohibited["status"] == "fail"
    assert prohibited["detail"] == "prohibited field present: customer_email"
    assert "customer_email" in primary_attempt["raw_fields_redacted"]
    assert result["response"]["source"] == "backup:local-fx-backup-v1"
    assert result["response"]["metrics"]["rate"] == 83.12  # normalized from backup's 'mid'


def test_fx_stale_primary_triggers_backup(tr_client) -> None:
    STATE["fx_mode"] = "stale_data"
    result = _fx_request(tr_client)
    assert result["outcome"] == "fallback"
    freshness = next(c for c in result["policy_checks"] if c["id"] == "freshness")
    assert freshness["status"] == "fail"
    assert "90 min old" in freshness["detail"]
    assert result["response"]["source"] == "backup:local-fx-backup-v1"
    assert result["response"]["observed_at"] is not None
    assert result["response"]["observed_at"]


def test_fx_http_503_triggers_backup(tr_client) -> None:
    STATE["fx_mode"] = "http_503"
    result = _fx_request(tr_client)
    assert result["outcome"] == "fallback"
    assert result["attempts"][0]["status_code"] == 503
    assert result["response"]["source"] == "backup:local-fx-backup-v1"


def test_fx_both_fail_returns_safe_degraded(tr_client) -> None:
    STATE["fx_mode"] = "http_503"
    STATE["fx_backup_up"] = False
    result = _fx_request(tr_client)
    assert result["outcome"] == "degraded"
    response = result["response"]
    # no fabricated FX values
    assert response["metrics"] == {}
    assert response["observed_at"] is None
    assert response["location"] == "USD/INR"  # echoed from the request
    assert response["source"] == "none"
    assert response["trust_score"] == 0
    assert result["decision_reason"].startswith("unavailable:")
    assert [a["role"] for a in result["attempts"]] == ["primary", "backup"]


def test_fx_invalid_pair_is_rejected_safely(tr_client) -> None:
    r = tr_client.post(
        "/trust-router/request", json={"location": "US DOLLARS", "category": "fx"}
    )
    assert r.status_code == 200  # handled, not crashed
    result = r.json()
    assert result["outcome"] == "degraded"
    assert "invalid location" in result["decision_reason"]
    assert result["response"]["source"] == "none"


def test_weather_regresses_not_after_fx_addition(tr_client) -> None:
    """Same app instance: weather path unchanged by the FX extension."""
    result = _request(tr_client)
    assert result["category"] == "weather"
    assert result["outcome"] == "primary"
    assert result["response"]["temperature_c"] == 27.5
    assert result["response"]["humidity_percent"] == 64
    assert result["trust_score"]["total"] == 100


def test_providers_catalog_lists_both_categories(tr_client) -> None:
    body = tr_client.get("/trust-router/providers").json()
    categories = {c["category"] for c in body["categories"]}
    assert categories == {"weather", "fx"}
    fx = next(c for c in body["categories"] if c["category"] == "fx")
    assert fx["default_location"] == "USD/INR"
    assert fx["primary"]["id"] == "local-fx-primary-v1"
    assert fx["backup"]["id"] == "local-fx-backup-v1"
    assert fx["primary"]["modes"] is not None


def test_primary_mode_is_per_category(tr_client) -> None:
    r = tr_client.post(
        "/trust-router/primary-mode", json={"mode": "stale_data", "category": "fx"}
    )
    assert r.status_code == 200
    assert r.json()["category"] == "fx"
    assert STATE["fx_mode"] == "stale_data"
    assert STATE["primary_mode"] == "healthy"  # weather untouched

    # stale FX run reports the mode in its audit record
    result = _fx_request(tr_client)
    assert result["primary_mode"] == "stale_data"

    r = tr_client.post(
        "/trust-router/primary-mode", json={"mode": "healthy", "category": "fx"}
    )
    assert r.status_code == 200


def test_unknown_category_rejected(tr_client) -> None:
    r = tr_client.post(
        "/trust-router/request", json={"location": "X", "category": "bitcoin"}
    )
    assert r.status_code == 422
    r = tr_client.post("/trust-router/primary-mode", json={"mode": "healthy", "category": "x"})
    assert r.status_code == 422
