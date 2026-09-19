"""HTTP API for the Trust Router (API Sentinel Mesh).

Endpoints (MVP spec + multi-category extension):
  GET  /trust-router/providers            catalog of approved local providers (all categories)
  POST /trust-router/request              run one trusted request: {"location"|"city", "category"}
  POST /trust-router/primary-mode         switch a category's primary simulator fault mode
  GET  /trust-router/audit/{request_id}   fetch a stored decision record

`city` remains accepted (weather MVP field); `location` generalizes it
(FX expects "USD/INR"). Isolation: mounts via APIRouter; tests can mount
this router into a fresh FastAPI app (see build_trust_router_app).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .audit import audit_store
from .config import backup_url, default_client_factory, primary_mode_url, primary_url
from .models import (
    CategoryCatalogEntry,
    PrimaryModeRequest,
    PrimaryModeResponse,
    ProviderInfo,
    ProvidersCatalog,
    TrustRouterRequest,
    TrustRouterResult,
)
from .providers import ProviderConfig
from .registry import CATEGORIES, CategorySpec, get_category
from .router import TrustRouter

router = APIRouter(prefix="/trust-router", tags=["trust-router"])


def _specs() -> list[CategorySpec]:
    # stable order: weather first (MVP), then others alphabetically
    return [CATEGORIES["weather"]] + [
        CATEGORIES[c] for c in sorted(CATEGORIES) if c != "weather"
    ]


def _provider_info(spec: CategorySpec, role: str) -> ProviderInfo:
    if role == "primary":
        return ProviderInfo(
            role="primary",
            id=spec.primary_schema.provider_id,
            url=primary_url(spec),
            description=(
                f"Local primary {spec.category} provider simulator with fault modes: "
                "healthy, slow_response, http_503, malformed_schema, stale_data"
            ),
            modes=["healthy", "slow_response", "http_503", "malformed_schema", "stale_data"],
        )
    backup_ids = {
        "weather": "local-weather-backup-v1",
        "fx": "local-fx-backup-v1",
    }
    return ProviderInfo(
        role="backup",
        id=backup_ids.get(spec.category, f"local-{spec.category}-backup-v1"),
        url=backup_url(spec),
        description=(
            f"Local backup {spec.category} provider: fixed healthy, deliberately "
            "different (nested) JSON schema requiring normalization"
        ),
    )


def get_router_instance(spec: CategorySpec) -> TrustRouter:
    """Fresh orchestrator per request; reads pinned config each time so tests
    can override env between calls."""
    return TrustRouter(
        primary=ProviderConfig(
            role="primary", provider_id=spec.primary_schema.provider_id, url=primary_url(spec)
        ),
        backup=ProviderConfig(
            role="backup",
            provider_id=_provider_info(spec, "backup").id,
            url=backup_url(spec),
        ),
        spec=spec,
        client_factory=default_client_factory(),
    )


@router.get("/providers", response_model=ProvidersCatalog)
def list_providers() -> ProvidersCatalog:
    entries = [
        CategoryCatalogEntry(
            category=spec.category,
            label=spec.label,
            input_hint=spec.input_hint,
            default_location=spec.default_location,
            primary=_provider_info(spec, "primary"),
            backup=_provider_info(spec, "backup"),
        )
        for spec in _specs()
    ]
    return ProvidersCatalog(categories=entries)


@router.post("/request", response_model=TrustRouterResult)
def trusted_request(body: TrustRouterRequest) -> TrustRouterResult:
    location = (body.location or body.city or "").strip()
    if not location:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide a location (city name or currency pair like USD/INR)",
        )
    try:
        spec = get_category(body.category)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return get_router_instance(spec).handle_request(location, spec.category)


@router.post("/primary-mode", response_model=PrimaryModeResponse)
def set_primary_mode(body: PrimaryModeRequest) -> PrimaryModeResponse:
    """Proxy the mode switch to the local primary provider simulator."""
    import httpx

    try:
        spec = get_category(body.category)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    try:
        response = httpx.post(
            primary_mode_url(spec),
            json={"mode": body.mode, "category": spec.category},
            timeout=2.0,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"primary provider simulator unreachable: {exc.__class__.__name__}",
        )
    if response.status_code != 200:
        detail = None
        try:
            detail = response.json().get("detail")
        except ValueError:
            pass
        raise HTTPException(
            status_code=(
                response.status_code if response.status_code in (404, 422) else status.HTTP_502_BAD_GATEWAY
            ),
            detail=detail or f"mode switch failed (HTTP {response.status_code})",
        )
    try:
        payload = response.json()
        mode = payload.get("mode", body.mode)
        category = payload.get("category", spec.category)
    except ValueError:
        mode, category = body.mode, spec.category
    return PrimaryModeResponse(
        mode=mode, category=category, message=f"{category} primary provider mode set to {mode}"
    )


@router.get("/audit/{request_id}", response_model=TrustRouterResult)
def get_audit_record(request_id: str) -> TrustRouterResult:
    record = audit_store.get(request_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no audit record for {request_id}",
        )
    return record


def build_trust_router_app():
    """Standalone app for isolated testing (no scanner, no conftest coupling)."""
    from fastapi import FastAPI

    app = FastAPI(title="API Sentinel Mesh — Trust Router (isolated)")
    app.include_router(router)
    return app
