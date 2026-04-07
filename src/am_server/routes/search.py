"""Unified cross-module search endpoint — requires Bearer auth."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from am_server.auth import require_auth
from am_server.dependencies import get_conversation_pipeline, get_pipeline
from agentic_memory.server.app import get_graph
from agentic_memory.server.unified_search import search_all_memory_sync

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/search/all")
async def search_all(
    q: str = Query(..., description="Unified search query string"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
    project_id: str | None = Query(None, description="Optional project filter"),
    as_of: str | None = Query(None, description="Optional ISO-8601 temporal cutoff"),
    modules: str | None = Query(
        None,
        description="Optional comma-separated modules: code,web,conversation",
    ),
) -> dict:
    """Return normalized unified results across code, web, and conversation memory."""
    requested_modules = None
    if modules:
        requested_modules = [part.strip() for part in modules.split(",") if part.strip()]

    payload = search_all_memory_sync(
        query=q,
        limit=limit,
        project_id=project_id,
        as_of=as_of,
        modules=requested_modules,
        graph=get_graph(),
        research_pipeline=get_pipeline(),
        conversation_pipeline=get_conversation_pipeline(),
    )
    return payload.to_dict()
