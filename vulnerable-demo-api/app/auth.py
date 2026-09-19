"""Authentication and runtime mode state for the demo API.

Deliberately simple: static bearer tokens from the synthetic seed data and a single
in-process mode flag (`vulnerable` / `secure`) that tests and the dashboard can toggle.
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException, status

from .data import USERS

_state: dict[str, Any] = {"mode": "vulnerable"}


def get_mode() -> str:
    return _state["mode"]


def set_mode(mode: str) -> None:
    if mode not in ("vulnerable", "secure"):
        raise ValueError(f"Unknown mode: {mode!r}")
    _state["mode"] = mode


def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    """Resolve the caller from the Authorization header; 401 if missing/unknown."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    token = authorization.removeprefix("Bearer ").strip()
    user = USERS.get(token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def enforce_object_access(user: dict, resource_owner_id: str) -> None:
    """Secure-mode object ownership check; 403 unless owner or admin.

    Callers that skip this check in vulnerable mode produce the hero BOLA bug.
    """
    if get_mode() == "vulnerable":
        return
    if user["role"] == "admin" or user["id"] == resource_owner_id:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
