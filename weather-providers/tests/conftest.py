"""Suite-wide defaults for provider-simulator tests.

The whole suite runs FULLY OFFLINE by default (TRUST_ROUTER_LIVE_DATA=0), so
every existing assertion keeps exercising the deterministic synthetic tier.
The live-data tests in test_live_data.py re-enable live mode per-test via
monkeypatch and mock the HTTP seam — no real network in CI.
"""

from __future__ import annotations

import os

os.environ["TRUST_ROUTER_LIVE_DATA"] = "0"
