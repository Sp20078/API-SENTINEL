"""Trust Router configuration: pinned loopback provider URLs, per category.

Defaults point at the local provider simulator (:8002). Overrides are
server-side only (env vars, per category), validated by the package's own
loopback guard — API clients can never point the Trust Router at another
host.
"""

from __future__ import annotations

import os

from .guard import validate_provider_url
from .registry import CategorySpec


def _url(env_name: str, default: str, what: str) -> str:
    return validate_provider_url(os.environ.get(env_name, default), what=what)


def primary_url(spec: CategorySpec) -> str:
    return _url(spec.env_primary_url, spec.default_primary_url, f"{spec.category} primary provider URL")


def backup_url(spec: CategorySpec) -> str:
    return _url(spec.env_backup_url, spec.default_backup_url, f"{spec.category} backup provider URL")


def primary_mode_url(spec: CategorySpec) -> str:
    return _url(
        spec.env_primary_mode_url,
        spec.default_primary_mode_url,
        f"{spec.category} primary-mode URL",
    )


def default_client_factory():
    """httpx.Client factory with hard timeouts for provider calls.

    read timeout 2.0s sits just past the 2000 ms latency budget so a slow
    provider fails the latency policy (or times out) either way.
    """
    import httpx

    return lambda: httpx.Client(timeout=httpx.Timeout(connect=1.5, read=2.0, write=2.0, pool=2.0))
