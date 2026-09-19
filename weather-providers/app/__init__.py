"""Local weather provider simulators for the Trust Router (API Sentinel Mesh).

Two deliberately different synthetic providers on one local service:
  - /primary/weather  mode-switchable fault injector (5 modes)
  - /backup/weather   fixed healthy provider with a different JSON schema

100% local, 100% synthetic. No real weather data, no external calls.
"""
