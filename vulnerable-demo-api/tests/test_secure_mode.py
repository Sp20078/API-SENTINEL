"""Acceptance tests: secure mode enforces object-level authorization."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_alice_accesses_her_own_order_200(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.get("/api/orders/order-1001", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "order-1001"
    assert body["shipping_address"] == "18 Lake View Road"


def test_hero_fix_alice_blocked_from_bobs_order_403(client: TestClient, set_mode_to) -> None:
    """The hero fix: Alice must NOT read Bob's order in secure mode."""
    set_mode_to("secure")
    r = client.get("/api/orders/order-1002", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 403
    assert "denied" in r.json()["detail"].lower()


def test_bob_blocked_from_alices_order_403(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.get("/api/orders/order-1001", headers={"Authorization": "Bearer bob-token"})
    assert r.status_code == 403


def test_admin_can_access_bobs_order_in_secure_mode(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.get("/api/orders/order-1002", headers={"Authorization": "Bearer admin-token"})
    assert r.status_code == 200
    assert r.json()["user_id"] == "user-102"


def test_cross_user_profile_blocked_in_secure_mode(client: TestClient, set_mode_to) -> None:
    """Secure mode: customers access only their own profile (403 for others)."""
    set_mode_to("secure")
    r = client.get("/api/users/user-102", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 403


def test_own_profile_returns_private_fields(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.get("/api/users/user-101", headers={"Authorization": "Bearer alice-token"})
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"


def test_admin_reads_full_profile(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.get("/api/users/user-102", headers={"Authorization": "Bearer admin-token"})
    assert r.status_code == 200
    assert r.json()["email"] == "bob@example.com"


def test_cross_user_order_list_blocked(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.get(
        "/api/users/user-102/orders", headers={"Authorization": "Bearer alice-token"}
    )
    assert r.status_code == 403


def test_own_order_list_ok(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.get(
        "/api/users/user-101/orders", headers={"Authorization": "Bearer alice-token"}
    )
    assert r.status_code == 200
    assert [o["id"] for o in r.json()] == ["order-1001"]


def test_customer_refund_blocked_in_secure_mode(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.post(
        "/api/admin/refunds",
        json={"order_id": "order-1002"},
        headers={"Authorization": "Bearer alice-token"},
    )
    assert r.status_code == 403


def test_admin_refund_ok_in_secure_mode(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    r = client.post(
        "/api/admin/refunds",
        json={"order_id": "order-1002", "reason": "damaged in transit"},
        headers={"Authorization": "Bearer admin-token"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "refunded"


def test_missing_token_still_401_in_secure_mode(client: TestClient, set_mode_to) -> None:
    set_mode_to("secure")
    assert client.get("/api/orders/order-1001").status_code == 401
