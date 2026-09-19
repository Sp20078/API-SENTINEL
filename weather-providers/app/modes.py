"""Primary-provider fault mode state (process-global, single uvicorn worker).

Modes (spec):
  healthy          → normal response, ~120 ms simulated latency
  slow_response    → normal shape after ~3.5 s (past the router's 2000 ms budget)
  http_503         → 503 Service Unavailable
  malformed_schema → schema-invalid payload: missing 'condition', adds
                     prohibited 'internal_user_id'
  stale_data       → valid shape, but observed_at is 90 minutes old
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

_mode = "healthy"
_lock = threading.Lock()


def get_mode() -> str:
    with _lock:
        return _mode


def set_mode(mode: str) -> str:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}; valid modes: {', '.join(VALID_MODES)}")
    with _lock:
        global _mode
        _mode = mode
    return _mode
