"""Unit tests: token redaction, sensitive-field detection, regression generation."""

from __future__ import annotations

from app.models import CheckResult, EvidenceRequest, EvidenceResponse, Finding, Probe
from app.scanner.redact import redact_authorization, redact_token
from app.scanner.regression import generate_regression_test
from app.scanner.sensitive import SENSITIVE_FIELDS, find_sensitive_fields


# --- redaction ---------------------------------------------------------------

def test_redact_token_middle_ellipsis() -> None:
    assert redact_token("alice-token") == "alic...oken"
    assert redact_token("bob-token") == "bob-...oken"


def test_redact_authorization_preserves_scheme() -> None:
    assert redact_authorization("Bearer alice-token") == "Bearer alic...oken"


def test_redact_authorization_none() -> None:
    assert redact_authorization(None) is None
    assert redact_authorization("") is None


# --- sensitive fields ----------------------------------------------------------

def test_sensitive_list_matches_spec() -> None:
    required = {
        "email", "phone", "address", "shipping_address", "date_of_birth", "dob",
        "card_number", "payment_method", "token", "password", "ssn", "aadhaar",
        "total", "items",
    }
    assert required == set(SENSITIVE_FIELDS)


def test_find_sensitive_fields_order_and_dedup() -> None:
    body = {
        "id": "order-1002",
        "user_id": "user-102",
        "items": ["Noise-Cancelling Headphones"],
        "total": 149.99,
        "shipping_address": "42 Park Street",
        "nested": {"card_number": "4111", "safe": "x"},
    }
    found = find_sensitive_fields(body)
    assert found == ["items", "total", "shipping_address", "nested.card_number"]


def test_find_sensitive_fields_in_lists_and_suffixes() -> None:
    body = [{"user_email": "a@b.c", "count": 1}, {"profile": {"phone": "123"}}]
    found = find_sensitive_fields(body)
    assert found == ["user_email", "profile.phone"]


def test_benign_body_has_no_findings() -> None:
    assert find_sensitive_fields({"id": "x", "name": "n", "status": "ok"}) == []


# --- regression generation ------------------------------------------------------

def _finding() -> Finding:
    probe = Probe(
        label="cross_user",
        url="http://127.0.0.1:8001/api/orders/order-1002",
        authorization_redacted="Bearer alic...oken",
        status_code=200,
        body={"id": "order-1002"},
    )
    return Finding(
        id="BOLA-001",
        title="Customer accessed another customer's private order",
        severity="critical",
        endpoint="GET /api/orders/{order_id}",
        method="GET",
        authenticated_user="Alice",
        authenticated_role="customer",
        resource_owner="Bob",
        expected_status=403,
        observed_status=200,
        request=EvidenceRequest(
            url=probe.url, method="GET", authorization=probe.authorization_redacted
        ),
        response=EvidenceResponse(status_code=200, body=probe.body),
        probes=[probe],
        sensitive_fields_exposed=["total"],
        impact="impact",
        recommendation="recommendation",
        status="fail",
    )


def test_generated_regression_test_matches_spec_shape() -> None:
    text = generate_regression_test(_finding())
    assert "def test_alice_cannot_access_another_customers_order_id():" in text
    assert '"/api/orders/order-1002"' in text
    assert '"Authorization": "Bearer alic...oken"' in text  # redacted, never raw
    assert "assert response.status_code in [401, 403]" in text


def test_check_regression_test_renders() -> None:
    check = CheckResult(
        id="CHK-001",
        endpoint="GET /api/orders/{order_id}",
        method="GET",
        authenticated_user="Alice",
        authenticated_role="customer",
        resource_owner="Bob",
        expected_status=403,
        observed_status=403,
        status="pass",
        probes=[
            Probe(
                label="cross_user",
                url="http://127.0.0.1:8001/api/orders/order-1002",
                authorization_redacted="Bearer alic...oken",
                status_code=403,
                body={"detail": "Access denied"},
            )
        ],
        sensitive_fields_exposed=[],
        impact="impact",
        recommendation="recommendation",
        regression_test="",
    )
    text = generate_regression_test(check)
    assert "def test_alice_cannot_access_another_customers_order_id():" in text
    assert "in [401, 403]" in text
