"""Trust Router configuration: pinned loopback provider URLs.

Defaults point at the local weather-providers simulator (:8002). Overrides
are server-side only (env vars), validated by the package's own loopback
guard — API clients can never point the Trust Router at another host.
"""

from __future__ import annotations

import os

from .guard import validate_provider_url

DEFAULT_PRIMARY_URL = "http://127.0.0.1:8002/primary/weather"
DEFAULT_BACKUP_URL = "http://127.0.0.1:8002/backup/weather"
DEFAULT_PRIMARY_MODE_URL = "http://127.0.0.1:8002/primary/mode"

ENV_PRIMARY_URL = "TRUST_ROUTER_PRIMARY_URL"
ENV_BACKUP_URL = "TRUST_ROUTER_BACKUP_URL"
ENV_PRIMARY_MODE_URL = "TRUST_ROUTER_PRIMARY_MODE_URL"


def primary_url() -> str:
    return validate_provider_url(
        os.environ.get(ENV_PRIMARY_URL, DEFAULT_PRIMARY_URL), what="primary provider URL"
    )


def backup_url() -> str:
    return validate_provider_url(
        os.environ.get(ENV_BACKUP_URL, DEFAULT_BACKUP_URL), what="backup provider URL"
    )


def primary_mode_url() -> str:
    return validate_provider_url(
        os.environ.get(ENV_PRIMARY_MODE_URL, DEFAULT_PRIMARY_MODE_URL),
        what="primary-mode URL",
    )


def default_client_factory():
    """httpx.Client factory with hard timeouts for provider calls.

    read timeout 2.0s sits just past the 2000 ms latency budget so a slow
    provider fails the latency policy (or times out) either way.
    """
    import httpx

    return lambda: httpx.Client(timeout=httpx.Timeout(connect=1.5, read=2.0, write=2.0, pool=2.0))
