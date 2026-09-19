"""Unit tests for the local-only target guard."""

from __future__ import annotations

import pytest

from app.target_guard import UnsafeTargetError, validate_target_url, validate_scan_target


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://127.0.0.1:8001/openapi.json",
        "http://demo-api:8001",  # project Docker service hostname
        "http://10.0.0.5",
        "http://192.168.1.10:8001",
        "http://[::1]:8001",
        "http://localhost",  # no port is fine
    ],
)
def test_local_targets_accepted(url: str) -> None:
    assert validate_target_url(url).startswith("http://")


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.com",  # non-local host
        "http://example.com",
        "http://169.254.1.1",  # link-local metadata range: still rejected in MVP
        "https://localhost:8001",  # scheme not allowed in MVP
        "ftp://localhost",
        "http://user:pass@localhost:8001",  # embedded credentials
        "http://../etc",  # malformed
        "",
    ],
)
def test_unsafe_targets_rejected(url: str) -> None:
    with pytest.raises(UnsafeTargetError):
        validate_target_url(url)


def test_validate_scan_target_returns_pair() -> None:
    base, contract = validate_scan_target(
        "http://127.0.0.1:8001/", "http://127.0.0.1:8001/openapi.json"
    )
    assert base == "http://127.0.0.1:8001"
    assert contract == "http://127.0.0.1:8001/openapi.json"
