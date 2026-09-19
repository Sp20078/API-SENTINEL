"""Minimal OpenAPI contract client.

Fetches /openapi.json from the (local) target and extracts what the MVP
scanner needs: GET operations with path parameters. Deliberately does not
support the full OpenAPI feature surface — just enough to discover object
endpoints and their metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class OpenAPIError(RuntimeError):
    """Raised when the contract cannot be fetched or parsed."""


@dataclass(frozen=True)
class EndpointInfo:
    path: str  # templated, e.g. "/api/orders/{order_id}"
    method: str  # uppercase
    path_params: tuple[str, ...]
    summary: str | None
    operation_id: str | None
    tags: tuple[str, ...]


def fetch_openapi(client: httpx.Client, openapi_url: str) -> dict[str, Any]:
    try:
        resp = client.get(openapi_url)
    except httpx.HTTPError as exc:
        raise OpenAPIError(f"Could not fetch OpenAPI contract at {openapi_url}: {exc}") from exc
    if resp.status_code != 200:
        raise OpenAPIError(
            f"OpenAPI contract at {openapi_url} returned HTTP {resp.status_code}"
        )
    try:
        doc = resp.json()
    except ValueError as exc:
        raise OpenAPIError(f"OpenAPI contract at {openapi_url} is not valid JSON") from exc
    if not isinstance(doc, dict) or "paths" not in doc:
        raise OpenAPIError("OpenAPI document is missing the 'paths' section")
    return doc


def discover_get_endpoints(doc: dict[str, Any]) -> list[EndpointInfo]:
    """Extract GET operations with their path parameters from an OpenAPI dict."""
    endpoints: list[EndpointInfo] = []
    for path, path_item in (doc.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        op = path_item.get("get")
        if not isinstance(op, dict):
            continue
        params: list[dict[str, Any]] = list(op.get("parameters") or [])
        params += list(path_item.get("parameters") or [])
        path_params = tuple(
            p["name"]
            for p in params
            if isinstance(p, dict) and p.get("in") == "path" and p.get("name")
        )
        declared = set(path_params)
        for raw in path.split("/"):
            if raw.startswith("{") and raw.endswith("}"):
                declared.add(raw[1:-1])
        endpoints.append(
            EndpointInfo(
                path=path,
                method="GET",
                path_params=tuple(sorted(declared)),
                summary=op.get("summary"),
                operation_id=op.get("operationId"),
                tags=tuple(op.get("tags") or []),
            )
        )
    return endpoints
