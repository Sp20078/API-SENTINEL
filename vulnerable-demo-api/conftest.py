"""Shared pytest fixtures for the demo API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.auth import set_mode


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def set_mode_to():
    """Fixture factory: set_mode_to("secure") pins the mode, then restores vulnerable."""

    def _set(mode: str) -> None:
        set_mode(mode)

    yield _set
    set_mode("vulnerable")
