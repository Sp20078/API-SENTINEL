"""Primary-provider fault mode state, per category (process-global).

The Trust Router supports multiple categories; each category's primary
simulator has its own independent fault mode. Modes (spec):
  healthy | slow_response | http_503 | malformed_schema | stale_data
"""

from __future__ import annotations

import threading

VALID_MODES: tuple[str, ...] = (
    "healthy",
    "slow_response",
    "http_503",
    "malformed_schema",
    "stale_data",
)

CATEGORIES: tuple[str, ...] = ("weather", "fx")

_modes: dict[str, str] = {"weather": "healthy", "fx": "healthy"}
_lock = threading.Lock()


def _norm(category: str | None) -> str:
    cat = (category or "weather").strip().lower()
    if cat not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; valid categories: {', '.join(CATEGORIES)}")
    return cat


def get_mode(category: str | None = None) -> str:
    with _lock:
        return _modes[_norm(category)]


def set_mode(mode: str, category: str | None = None) -> str:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}; valid modes: {', '.join(VALID_MODES)}")
    cat = _norm(category)
    with _lock:
        _modes[cat] = mode
    return _modes[cat]
