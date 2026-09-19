"""Target-safety guard: the scanner only talks to local, controlled targets.

Allowed hosts: localhost, *.localhost, 127.0.0.1/8, ::1, [::1], 0.0.0.0,
and this project's Docker service hostnames. Everything else is rejected
(422 at the API layer) before any request is made.
"""

from __future__ import annotations

from urllib.parse import urlparse

DOCKER_SERVICE_HOSTS = {"demo-api", "sentinel-engine", "frontend"}

LOCAL_HOSTNAMES = {"localhost", "0.0.0.0"} | {
    f"{name}.localhost" for name in DOCKER_SERVICE_HOSTS
} | DOCKER_SERVICE_HOSTS

PRIVATE_IPV4_PREFIXES = ("127.", "10.", "192.168.")

ALLOWED_LOCAL_SCHEMES = {"http"}  # deliberately no https scanning in the MVP


class UnsafeTargetError(ValueError):
    """Raised when a scan target is not an approved local target."""


def _host_allowed(host: str) -> bool:
    h = host.strip("[]").lower()
    if h == "::1" or h == "::" or h.startswith("::ffff:127."):
        return True
    if h in LOCAL_HOSTNAMES:
        return True
    return h.startswith(PRIVATE_IPV4_PREFIXES)


def validate_target_url(url: str, *, what: str = "target") -> str:
    """Validate a URL points at a local target; return the normalized base URL.

    Raises UnsafeTargetError for anything remote, non-http, or malformed.
    """
    if not url or not isinstance(url, str):
        raise UnsafeTargetError(f"{what} URL must be a non-empty string")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ALLOWED_LOCAL_SCHEMES:
        raise UnsafeTargetError(
            f"{what} URL must use http (got scheme {parsed.scheme!r}); "
            "only controlled local targets are supported"
        )
    host = parsed.hostname or ""
    if not _host_allowed(host):
        raise UnsafeTargetError(
            f"{what} host {host!r} is not an approved local target. "
            "API Sentinel only scans localhost, 127.0.0.0/8, private LAN ranges, "
            "and this project's Docker service hostnames."
        )
    if parsed.username or parsed.password:
        raise UnsafeTargetError(f"{what} URL must not embed credentials")
    # Normalize: no trailing slash, no query/fragment expected for base URLs.
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
    return base


def validate_scan_target(target_base_url: str, openapi_url: str) -> tuple[str, str]:
    return (
        validate_target_url(target_base_url, what="target_base_url"),
        validate_target_url(openapi_url, what="openapi_url"),
    )
