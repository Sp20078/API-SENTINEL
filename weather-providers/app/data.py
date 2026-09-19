"""Synthetic weather data for the local provider simulators.

Curated entries for demo cities; any other city string gets deterministic
pseudo-weather derived from a stable hash, so the demo never breaks on a typo.
No real data, no network calls, no persistence.
"""

from __future__ import annotations

import hashlib
from typing import Any

# city -> (temperature_c, humidity_percent, condition)
CURATED_WEATHER: dict[str, tuple[float, int, str]] = {
    "Bengaluru": (27.5, 64, "Partly cloudy"),
    "London": (14.2, 78, "Light rain"),
    "New York": (21.8, 55, "Clear"),
    "Singapore": (31.4, 84, "Thunderstorms"),
    "Tokyo": (24.6, 70, "Cloudy"),
    "Sydney": (18.9, 60, "Sunny"),
}

_CONDITIONS = ("Clear", "Partly cloudy", "Cloudy", "Light rain", "Sunny")


def weather_for(city: str) -> dict[str, Any]:
    """Return synthetic scalar weather for a city (curated or deterministic)."""
    curated = CURATED_WEATHER.get(city)
    if curated is not None:
        return {
            "temp_c": curated[0],
            "humidity": curated[1],
            "condition": curated[2],
        }
    digest = hashlib.sha256(city.strip().lower().encode("utf-8")).digest()
    temp = round(5 + (digest[0] / 255) * 30, 1)  # 5..35 °C
    humidity = 35 + digest[1] % 61  # 35..95 %
    condition = _CONDITIONS[digest[2] % len(_CONDITIONS)]
    return {"temp_c": temp, "humidity": humidity, "condition": condition}
