"""Local product control-plane routes for desktop, CLI, and dogfooding workflows."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from fastapi import APIRouter, Depends, Query

from am_server.auth import require_auth
from am_server.dependencies import get_product_store
from am_server.models import (
    ProductComponentStatusRequest,
    ProductEventRequest,
    ProductIntegrationUpsertRequest,
    ProductOnboardingStepRequest,
    ProductRepoUpsertRequest,
)
from agentic_memory.server.app import get_graph
from agentic_memory.product.state import ProductStateStore

from .ext import _SELECTORS_PATH

router = APIRouter(dependencies=[Depends(require_auth)])


def _package_version() -> str:
    """Return the installed agentic-memory package version."""
    try:
        return importlib.metadata.version("agentic-memory")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


@router.get("/product/status")
async def product_status(
    repo_path: str | None = Query(None, description="Optional repository path to summarize"),
) -> dict:
    """Return local product state plus lightweight live runtime facts."""
    store = get_product_store()
    repo_root = Path(repo_path).expanduser().resolve() if repo_path else None
    payload = store.status_payload(repo_root=repo_root)
    payload["runtime"] = {
        "server": {"status": "healthy", "version": _package_version()},
        "graph": {"connected": get_graph() is not None},
        "selectors": {
            "path": str(_SELECTORS_PATH),
            "exists": _SELECTORS_PATH.exists(),
        },
    }
    return payload


@router.post("/product/repos")
async def upsert_product_repo(body: ProductRepoUpsertRequest) -> dict:
    """Create or update a tracked repository entry."""
    store = get_product_store()
    repo = store.upsert_repo(body.repo_path, label=body.label, metadata=body.metadata)
    return {"status": "ok", "repo": repo}


@router.post("/product/integrations")
async def upsert_product_integration(body: ProductIntegrationUpsertRequest) -> dict:
    """Create or update a tracked integration entry."""
    store = get_product_store()
    integration = store.upsert_integration(
        surface=body.surface,
        target=body.target,
        status=body.status,
        config=body.config,
        last_error=body.last_error,
    )
    return {"status": "ok", "integration": integration}


@router.post("/product/components/{component}")
async def set_product_component_status(
    component: str,
    body: ProductComponentStatusRequest,
) -> dict:
    """Update runtime component health information."""
    store = get_product_store()
    record = store.set_component_status(component, status=body.status, details=body.details)
    return {"status": "ok", "component": component, "record": record}


@router.post("/product/events")
async def record_product_event(body: ProductEventRequest) -> dict:
    """Append a local product event for install and integration loops."""
    store = get_product_store()
    event = store.record_event(
        event_type=body.event_type,
        status=body.status,
        actor=body.actor,
        details=body.details,
    )
    return {"status": "ok", "event": event}


@router.post("/product/onboarding")
async def update_product_onboarding(body: ProductOnboardingStepRequest) -> dict:
    """Update onboarding progress for the local product shell."""
    store = get_product_store()
    onboarding = store.update_onboarding_step(body.step, completed=body.completed)
    return {"status": "ok", "onboarding": onboarding}
