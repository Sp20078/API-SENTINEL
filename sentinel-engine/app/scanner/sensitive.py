"""Deterministic sensitive-field detection over JSON response bodies.

The field list is the spec'd MVP set. Detection is exact/lowercase-key based
plus a small suffix set (e.g. "user_email") to catch common naming, with no
fuzzy matching — evidence must be reproducible.
"""

from __future__ import annotations

from typing import Any

SENSITIVE_FIELDS: frozenset[str] = frozenset(
    {
        "email",
        "phone",
        "address",
        "shipping_address",
        "date_of_birth",
        "dob",
        "card_number",
        "payment_method",
        "token",
        "password",
        "ssn",
        "aadhaar",
        "total",
        "items",
    }
)

# Key suffixes treated as sensitive when the exact name is absent
# (e.g. "user_email"). Kept small and deterministic on purpose.
SENSITIVE_SUFFIXES: tuple[str, ...] = ("email", "phone", "address", "dob")


def _key_is_sensitive(key: str) -> bool:
    k = key.lower()
    if k in SENSITIVE_FIELDS:
        return True
    return k.endswith(SENSITIVE_SUFFIXES)


def find_sensitive_fields(payload: Any, _prefix: str = "") -> list[str]:
    """Return dotted paths of sensitive fields present in a JSON-ish payload.

    Top-level and nested dict keys are inspected; lists are traversed one level
    into their elements. Deterministic ordering (insertion order of the body).
    """
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{_prefix}.{key}" if _prefix else str(key)
            if _key_is_sensitive(str(key)):
                found.append(path)
            found.extend(find_sensitive_fields(value, path))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(find_sensitive_fields(item, _prefix))
    return found
