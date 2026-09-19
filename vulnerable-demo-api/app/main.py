"""FastAPI app factory for the vulnerable demo e-commerce API.

Implements the full spec'd endpoint set with a runtime-switchable `vulnerable`/`secure`
mode. In vulnerable mode, object-ownership checks are intentionally missing on selected
protected endpoints (the hero BOLA bug). FastAPI serves /openapi.json automatically.

Note: request/response models live at module level so Pydantic can resolve them for
schema generation and body parsing.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth import enforce_object_access, get_current_user, get_mode, set_mode
from .data import ORDERS, PRODUCTS, USERS, Mode


class HealthResponse(BaseModel):
    status: str
    service: str
    mode: Mode


class ModeSwitchRequest(BaseModel):
    mode: Mode


class ModeSwitchResponse(BaseModel):
    mode: Mode
    message: str


class RefundRequest(BaseModel):
    order_id: str
    reason: str | None = None


class RefundResponse(BaseModel):
    refund_id: str
    order_id: str
    status: str


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sentinel Demo Shop",
        description=(
            "Local e-commerce demo API for API Sentinel. Has a runtime-switchable "
            "`vulnerable`/`secure` mode; vulnerable mode intentionally omits "
            "object-level authorization checks."
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> dict[str, Any]:
        """Liveness + the active demo mode, so tools can see what is being scanned."""
        return {"status": "ok", "service": "sentinel-demo-shop", "mode": get_mode()}

    @app.post("/admin/mode", response_model=ModeSwitchResponse, tags=["system"])
    def switch_mode(body: ModeSwitchRequest) -> dict[str, Any]:
        """Switch between vulnerable and secure demo modes at runtime."""
        set_mode(body.mode)
        return {"mode": get_mode(), "message": f"Demo mode set to {get_mode()}"}

    @app.get("/api/products", tags=["shop"])
    def list_products() -> list[dict[str, Any]]:
        """Public catalog."""
        return PRODUCTS

    @app.get("/api/orders/{order_id}", tags=["shop"])
    def get_order(order_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
        """Order detail. BUG (vulnerable mode): no object-level authorization check."""
        order = ORDERS.get(order_id)
        if order is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        enforce_object_access(current_user, order["user_id"])
        return order

    @app.get("/api/users/{user_id}", tags=["shop"])
    def get_user(user_id: str, current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
        """Profile. Secure mode: only the owner or an admin may read it."""
        profile = next((u for u in USERS.values() if u["id"] == user_id), None)
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        enforce_object_access(current_user, profile["id"])
        if get_mode() == "vulnerable":
            return profile  # BUG: full private profile for any authenticated user
        return profile  # reachable only for owner/admin; enforce_object_access 403s others

    @app.get("/api/users/{user_id}/orders", tags=["shop"])
    def get_user_orders(
        user_id: str, current_user: dict = Depends(get_current_user)
    ) -> list[dict[str, Any]]:
        """Order list per user. Vulnerable mode: cross-user list is readable."""
        owner = next((u for u in USERS.values() if u["id"] == user_id), None)
        if owner is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        orders = [o for o in ORDERS.values() if o["user_id"] == user_id]
        enforce_object_access(current_user, user_id)
        return orders

    @app.post("/api/admin/refunds", response_model=RefundResponse, tags=["admin"])
    def admin_refunds(
        body: RefundRequest, current_user: dict = Depends(get_current_user)
    ) -> dict[str, Any]:
        """Admin-only action. Vulnerable mode: any customer can trigger a refund."""
        if body.order_id not in ORDERS:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
        if get_mode() == "vulnerable":  # BUG: missing role check
            return {
                "refund_id": f"ref-{body.order_id.removeprefix('order-')}",
                "order_id": body.order_id,
                "status": "refunded",
            }
        if current_user["role"] != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
            )
        return {
            "refund_id": f"ref-{body.order_id.removeprefix('order-')}",
            "order_id": body.order_id,
            "status": "refunded",
        }

    return app


app = create_app()
