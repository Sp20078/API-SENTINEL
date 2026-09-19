"""Trust-Router-local URL guard: providers must be loopback http endpoints.

Standalone on purpose (isolation contract): this module must not import
app.target_guard, so it carries its own minimal loopback-only validation.
Provider URLs are configured server-side (env or defaults) — never supplied
by API clients.
"""

from __future__ import annotations

from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http"}
ALLOWED_HOSTS = {"localhost", "0.0.0.0", "::1", "::"}


class UnsafeProviderURLError(ValueError):
    """Raised when a configured provider URL is not a loopback http URL."""


def _host_allowed(host: str) -> bool:
    h = host.strip("[]").lower()
    if h in ALLOWED_HOSTS or h.endswith(".localhost"):
        return True
    return h.startswith("127.")


def validate_provider_url(url: str, *, what: str = "provider URL") -> str:
    """Validate a provider URL is local http; return it unchanged.

    Raises UnsafeProviderURLError for remote, non-http, or malformed URLs.
    """
    if not url or not isinstance(url, str):
        raise UnsafeProviderURLError(f"{what} must be a non-empty string")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeProviderURLError(
            f"{what} must use http (got scheme {parsed.scheme!r}); "
            "the Trust Router only calls controlled local providers"
        )
    host = parsed.hostname or ""
    if not _host_allowed(host):
        raise UnsafeProviderURLError(
            f"{what} host {host!r} is not a loopback target. The Trust Router "
            "only calls 127.0.0.0/8, localhost, ::1, or *.localhost providers."
        )
    if parsed.username or parsed.password:
        raise UnsafeProviderURLError(f"{what} must not embed credentials")
    return url.strip()
