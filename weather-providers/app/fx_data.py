"""Synthetic FX (currency rate) data for the local provider simulators.

Curated USD-based rates for demo currencies; any other base gets
deterministic pseudo-rates derived from a stable hash. No real data, no
network calls, no persistence.
"""

from __future__ import annotations

import hashlib
from typing import Any

# base -> {quote: (rate, inverse_rate)}  (synthetic snapshot values)
CURATED_RATES: dict[str, dict[str, tuple[float, float]]] = {
    "USD": {
        "EUR": (0.9134, 1.0948),
        "GBP": (0.7841, 1.2753),
        "INR": (83.12, 0.0120),
        "JPY": (147.55, 0.0068),
        "SGD": (1.3452, 0.7434),
        "AUD": (1.5218, 0.6571),
    },
    "EUR": {
        "USD": (1.0948, 0.9134),
        "INR": (91.03, 0.0110),
    },
}


def _deterministic_rate(base: str, quote: str) -> tuple[float, float]:
    digest = hashlib.sha256(f"{base}/{quote}".encode("utf-8")).digest()
    rate = round(0.5 + (digest[0] / 255) * 150, 4)  # 0.5..150.5
    inverse = round(1.0 / rate, 6)
    return rate, inverse


def rate_for(base: str, quote: str) -> dict[str, Any]:
    """Return synthetic scalar FX data (curated or deterministic)."""
    curated = CURATED_RATES.get(base, {}).get(quote)
    if curated is not None:
        return {"rate": curated[0], "inverse_rate": curated[1]}
    rate, inverse = _deterministic_rate(base, quote)
    return {"rate": rate, "inverse_rate": inverse}
