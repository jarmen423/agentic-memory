"""Health check endpoint — unauthenticated."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Return service liveness status."""
    return {"status": "ok"}
