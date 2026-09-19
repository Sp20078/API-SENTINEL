"""Tests for /health and /admin/mode."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_mode(client: TestClient, set_mode_to) -> None:
    set_mode_to("vulnerable")
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "sentinel-demo-shop"
    assert body["mode"] == "vulnerable"

    set_mode_to("secure")
    assert client.get("/health").json()["mode"] == "secure"


def test_switch_mode_endpoint(client: TestClient) -> None:
    r = client.post("/admin/mode", json={"mode": "secure"})
    assert r.status_code == 200
    assert r.json()["mode"] == "secure"

    r = client.post("/admin/mode", json={"mode": "vulnerable"})
    assert r.status_code == 200
    assert r.json()["mode"] == "vulnerable"


def test_switch_mode_rejects_unknown_value(client: TestClient) -> None:
    r = client.post("/admin/mode", json={"mode": "chaos"})
    assert r.status_code == 422


def test_openapi_contract_available(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["openapi"].startswith("3.")
    paths = spec["paths"]
    assert "/api/orders/{order_id}" in paths
    assert "/api/users/{user_id}" in paths
    assert "/api/users/{user_id}/orders" in paths
    assert "/api/products" in paths
    assert "/api/admin/refunds" in paths
    assert "/admin/mode" in paths
    assert "/health" in paths
    get_op = paths["/api/orders/{order_id}"]["get"]
    assert get_op["parameters"][0]["name"] == "order_id"
    assert get_op["parameters"][0]["in"] == "path"
