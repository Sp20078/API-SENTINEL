"""Deterministic token redaction.

Tokens must never reach the frontend. Every Authorization value the scanner
stores or returns is first passed through `redact_authorization`, which turns
"Bearer <token>" into "Bearer <first4>...<last4>" (e.g. "Bearer alic...oken").
"""

from __future__ import annotations


def redact_token(token: str) -> str:
    token = token.strip()
    if len(token) <= 8:
        return token[:2] + "..." + token[-2:] if len(token) > 4 else "..."
    return f"{token[:4]}...{token[-4:]}"


def redact_authorization(header_value: str | None) -> str | None:
    """Redact an Authorization header value, preserving the auth scheme."""
    if not header_value:
        return None
    value = header_value.strip()
    scheme, sep, token = value.partition(" ")
    if sep and scheme.lower() in {"bearer", "token", "basic"}:
        return f"{scheme} {redact_token(token)}"
    return redact_token(value)  # no recognizable scheme: redact conservatively
