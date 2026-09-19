"""HTTP API for the Trust Router (API Sentinel Mesh).

Endpoints (MVP spec):
  GET  /trust-router/providers            catalog of approved local providers
  POST /trust-router/request              run one trusted weather request
  POST /trust-router/primary-mode         switch the primary simulator's fault mode
  GET  /trust-router/audit/{request_id}   fetch a stored decision record

Isolation: mounts via APIRouter; the scanner module is untouched. Tests can
mount this router into a fresh FastAPI app (see build_trust_router_app).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from .audit import audit_store
from .config import backup_url, primary_mode_url, primary_url, default_client_factory
from .models import (
    PrimaryModeRequest,
    PrimaryModeResponse,
    ProviderInfo,
    ProvidersCatalog,
    TrustRouterRequest,
    TrustRouterResult,
)
from .providers import ProviderConfig, build_provider_config
from .router import BACKUP_PROVIDER_ID, PRIMARY_PROVIDER_ID, TrustRouter

router = APIRouter(prefix="/trust-router", tags=["trust-router"])


def _mode_url() -> str:
    return primary_mode_url()


def get_router_instance() -> TrustRouter:
    """Fresh orchestrator per request; reads pinned config each time so tests
    can override env between calls."""
    return TrustRouter(
        primary=ProviderConfig(role="primary", provider_id=PRIMARY_PROVIDER_ID, url=primary_url()),
        backup=ProviderConfig(role="backup", provider_id=BACKUP_PROVIDER_ID, url=backup_url()),
        client_factory=default_client_factory(),
    )


@router.get("/providers", response_model=ProvidersCatalog)
def list_providers() -> ProvidersCatalog:
    return ProvidersCatalog(
        category="weather",
        primary=ProviderInfo(
            role="primary",
            id=PRIMARY_PROVIDER_ID,
            url=primary_url(),
            description=(
                "Local primary weather provider simulator with fault modes: "
                "healthy, slow_response, http_503, malformed_schema, stale_data"
            ),
            modes=["healthy", "slow_response", "http_503", "malformed_schema", "stale_data"],
        ),
        backup=ProviderInfo(
            role="backup",
            id=BACKUP_PROVIDER_ID,
            url=backup_url(),
            description=(
                "Local backup weather provider: fixed healthy, deliberately "
                "different (nested) JSON schema requiring normalization"
            ),
        ),
    )


@router.post("/request", response_model=TrustRouterResult)
def trusted_request(body: TrustRouterRequest) -> TrustRouterResult:
    return get_router_instance().handle_request(body.city)


@router.post("/primary-mode", response_model=PrimaryModeResponse)
def set_primary_mode(body: PrimaryModeRequest) -> PrimaryModeResponse:
    """Proxy the mode switch to the local primary provider simulator."""
    import httpx

    try:
        response = httpx.post(_mode_url(), json={"mode": body.mode}, timeout=2.0)
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
            status_code=response.status_code if response.status_code in (404, 422) else status.HTTP_502_BAD_GATEWAY,
            detail=detail or f"mode switch failed (HTTP {response.status_code})",
        )
    try:
        mode = response.json().get("mode", body.mode)
    except ValueError:
        mode = body.mode
    return PrimaryModeResponse(mode=mode, message=f"primary provider mode set to {mode}")


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
