"""HTTP API for the local product control plane (desktop shell, CLI, dogfooding).

Defines authenticated routes that read and update the in-process
:class:`~agentic_memory.product.state.ProductStateStore`: aggregate status,
tracked repos and integrations, runtime component health, product events, and
onboarding progress. Companion modules mount graph and OpenClaw surfaces; this
file stays focused on first-party product state.
"""

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

# Auth boundary: Bearer token required for all product control-plane routes.
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
    """Return merged product state and ephemeral server/runtime facts.

    Args:
        repo_path: Optional path expanded and resolved to scope repo-specific
            portions of the status payload.

    Returns:
        Product store ``status_payload`` augmented with ``runtime`` (server
        version, graph connectivity, Tree-sitter selectors path metadata).
    """
    store = get_product_store()
    # Optional query: resolve repo_path for store-scoped summary when provided.
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
    """Create or update a tracked repository record in product state.

    Args:
        body: Path, label, and optional metadata for the repo.

    Returns:
        Dict with ``status`` ``"ok"`` and the persisted ``repo`` dict.
    """
    store = get_product_store()
    repo = store.upsert_repo(body.repo_path, label=body.label, metadata=body.metadata)
    return {"status": "ok", "repo": repo}


@router.post("/product/integrations")
async def upsert_product_integration(body: ProductIntegrationUpsertRequest) -> dict:
    """Create or update an integration registration (surface, target, config).

    Args:
        body: Integration identity, status, config blob, and optional last error.

    Returns:
        Dict with ``status`` ``"ok"`` and the persisted ``integration`` dict.
    """
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
    """Update health status and details for a named runtime component.

    Args:
        component: Component key from the URL path.
        body: New ``status`` and structured ``details`` for operators.

    Returns:
        Dict with ``status`` ``"ok"``, echoed ``component``, and ``record``.
    """
    store = get_product_store()
    record = store.set_component_status(component, status=body.status, details=body.details)
    return {"status": "ok", "component": component, "record": record}


@router.post("/product/events")
async def record_product_event(body: ProductEventRequest) -> dict:
    """Append an append-only product event (install, integration, telemetry).

    Args:
        body: Event type, status, actor, and details payload.

    Returns:
        Dict with ``status`` ``"ok"`` and the stored ``event`` dict.
    """
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
    """Mark an onboarding step complete or incomplete for the local shell.

    Args:
        body: Step identifier and ``completed`` flag.

    Returns:
        Dict with ``status`` ``"ok"`` and the updated ``onboarding`` structure.
    """
    store = get_product_store()
    onboarding = store.update_onboarding_step(body.step, completed=body.completed)
    return {"status": "ok", "onboarding": onboarding}
