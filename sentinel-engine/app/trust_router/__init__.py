"""API Sentinel Mesh — Trust Router.

Policy-aware API fallback and trusted response routing for local providers.

Isolation contract (enforced by tests/test_module_isolation.py):
  - this package imports ONLY stdlib + httpx + pydantic + fastapi
  - it never imports app.scanner, app.store, app.models, or app.target_guard
  - it owns its own ID space (prefix `tr-req-`), store, and config guard
"""

from __future__ import annotations
