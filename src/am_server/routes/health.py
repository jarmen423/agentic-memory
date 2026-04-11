"""Health and metrics endpoints for am_server."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from am_server.auth import require_auth
from am_server.metrics import render_prometheus_metrics

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Return service liveness status."""
    return {"status": "ok"}


@router.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(require_auth)])
def metrics() -> PlainTextResponse:
    """Return Prometheus-style request and error metrics.

    The endpoint is authenticated because these labels reveal route structure
    and live traffic/error counts that should stay operator-only.
    """

    return PlainTextResponse(render_prometheus_metrics())
