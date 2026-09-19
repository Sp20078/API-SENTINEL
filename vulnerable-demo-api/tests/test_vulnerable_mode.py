"""Acceptance tests: vulnerable mode intentionally lacks object-level authorization.

The hero scenario: Alice (customer) requesting Bob's order returns 200 with his
private data in vulnerable mode.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_defaults_to_vulnerable(client: TestClient) -> None:
    assert client.get("/health").json()["mode"] == "vulnerable"


def test_alice_accesses_her_own_order_200(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get("/api/orders/order-1001", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "order-1001"
    assert body["user_id"] == "user-101"
    assert body["shipping_address"] == "18 Lake View Road"


def test_hero_vulnerability_alice_gets_bobs_order_200(client: TestClient, set_mode_to) -> None:
    """THE hero bug: cross-user order read must be blocked in secure mode, is 200 here."""
    set_mode_to("vulnerable")
    r = client.get("/api/orders/order-1002", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "order-1002"
    assert body["user_id"] == "user-102"  # Bob's order, not Alice's!
    assert body["shipping_address"] == "42 Park Street"  # Bob's private address leaked
    assert body["total"] == 149.99


def test_alice_reads_bobs_full_profile(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get("/api/users/user-102", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "bob@example.com"  # private field leaked
    assert body["phone"] == "+1-555-0102"
    assert body["date_of_birth"] == "1988-11-02"


def test_alice_lists_bobs_orders(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get(
        "/api/users/user-102/orders", headers={"Authorization": "Bearer alice-token"}
    )
    assert r.status_code == 200
    orders = r.json()
    assert isinstance(orders, list) and len(orders) == 1
    assert orders[0]["id"] == "order-1002"  # Bob's order visible to Alice


def test_customer_triggers_admin_refund(client: TestClient, set_mode_to) -> None:
    """Vulnerable mode: the admin-only refund action accepts any customer."""
    set_mode_to("vulnerable")
    r = client.post(
        "/api/admin/refunds",
        json={"order_id": "order-1002", "reason": "broken item"},
        headers={"Authorization": "Bearer alice-token"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "refunded"


def test_products_public_without_token(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get("/api/products")
    assert r.status_code == 200
    assert {p["name"] for p in r.json()} >= {"Wireless Keyboard", "USB-C Hub"}


def test_missing_token_returns_401(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get("/api/orders/order-1001")
    assert r.status_code == 401


def test_invalid_token_returns_401(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get("/api/orders/order-1001", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_unknown_order_returns_404(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get("/api/orders/order-9999", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 404
