"""Provider HTTP client layer for the Trust Router.

Hard timeouts on every external call; failures surface as typed errors so the
router can fall back or degrade gracefully instead of raising to the caller.
Latency is measured around the actual HTTP exchange.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from .guard import validate_provider_url


class ProviderError(Exception):
    """Base class: any provider failure the router should handle."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ProviderUnavailableError(ProviderError):
    """Non-200 status, connection failure, or protocol error."""


class ProviderTimeoutError(ProviderUnavailableError):
    """The provider did not answer within the configured timeout budget."""


@dataclass(frozen=True)
class ProviderCall:
    """Raw outcome of one provider HTTP call."""

    url: str
    status_code: int | None
    latency_ms: int
    body: Any | None
    error: str | None = None


@dataclass(frozen=True)
class ProviderConfig:
    role: str  # "primary" | "backup"
    provider_id: str  # e.g. "local-weather-primary-v1"
    url: str  # pinned loopback URL, validated at construction
    connect_timeout_s: float = 1.5
    read_timeout_s: float = 2.0


def build_provider_config(role: str, provider_id: str, url: str) -> ProviderConfig:
    return ProviderConfig(role=role, provider_id=provider_id, url=validate_provider_url(url))


def call_provider(
    client: httpx.Client, config: ProviderConfig, params: dict[str, str]
) -> ProviderCall:
    """Call a provider with hard timeouts; never raises.

    Returns a ProviderCall with status_code/body, or status_code=None plus a
    typed error message (timeout / connection failure / non-JSON body).
    """
    started = time.perf_counter()
    try:
        response = client.get(config.url, params=params)
    except httpx.TimeoutException:
        latency = int((time.perf_counter() - started) * 1000)
        return ProviderCall(
            url=config.url,
            status_code=None,
            latency_ms=latency,
            body=None,
            error=f"no response within {int(config.read_timeout_s * 1000)} ms (read timeout)",
        )
    except httpx.HTTPError as exc:
        latency = int((time.perf_counter() - started) * 1000)
        return ProviderCall(
            url=config.url,
            status_code=None,
            latency_ms=latency,
            body=None,
            error=f"provider unreachable: {exc.__class__.__name__}",
        )
    latency = int((time.perf_counter() - started) * 1000)

    if response.status_code != 200:
        return ProviderCall(
            url=config.url,
            status_code=response.status_code,
            latency_ms=latency,
            body=None,
            error=f"HTTP {response.status_code} from provider",
        )
    try:
        return ProviderCall(url=config.url, status_code=200, latency_ms=latency, body=response.json())
    except ValueError:
        return ProviderCall(
            url=config.url,
            status_code=200,
            latency_ms=latency,
            body=None,
            error="provider returned a non-JSON body",
        )
