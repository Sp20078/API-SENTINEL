"""Default data-source tier per category: 'live' (real upstreams with silent
fallback) or 'synthetic' (deterministic offline values).

Process-global like modes.py; per-request `data_mode` query params override
the default for a single call.
"""

from __future__ import annotations

import threading

CATEGORIES: tuple[str, ...] = ("weather", "fx")
VALID: tuple[str, ...] = ("live", "synthetic")

_modes: dict[str, str] = {"weather": "live", "fx": "live"}
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
    if mode not in VALID:
        raise ValueError(f"unknown data mode {mode!r}; valid modes: {', '.join(VALID)}")
    cat = _norm(category)
    with _lock:
        _modes[cat] = mode
    return _modes[cat]
