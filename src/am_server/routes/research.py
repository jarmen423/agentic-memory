"""HTTP routes for research memory: ingest and search.

This module wires FastAPI handlers to the application's research ``Pipeline``
(dependency-injected via ``get_pipeline``). Ingestion runs the synchronous
``pipeline.ingest`` in a thread pool so the event loop stays responsive; search
executes blocking Neo4j access the same way.

All routes require Bearer authentication (see ``router`` dependencies).

Attributes:
    router: APIRouter with ``require_auth`` applied to every route in this module.
    logger: Module logger for operational messages.
"""

from __future__ import annotations

import asyncio
from contextvars import copy_context

from fastapi import APIRouter, Depends, HTTPException, Query

from am_server.auth import require_auth
from am_server.dependencies import get_pipeline
from am_server.models import ResearchIngestRequest
from agentic_memory.server.research_search import search_research as run_research_search
from agentic_memory.server.temporal_contract import TemporalRetrievalRequiredError

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/ingest/research", status_code=202)
async def ingest_research(body: ResearchIngestRequest) -> dict:
    """Accept a research payload and enqueue graph ingestion via the research pipeline.

    The request body is passed to ``Pipeline.ingest`` as a plain dict. Work is
    scheduled on the default executor so sync graph/embedding IO does not block
    the asyncio event loop.

    Args:
        body: Validated ingest payload including ``session_id`` and research fields.
            ``session_id`` must be supplied by the client; the server must not invent one.

    Returns:
        A small JSON envelope: ``{"status": "ok", "result": ...}`` where ``result``
        is the return value from ``pipeline.ingest``.

    Note:
        ``copy_context`` preserves contextvars when the callable runs in the executor,
        matching other pipeline-offloading patterns in this codebase.
    """
    pipeline = get_pipeline()
    loop = asyncio.get_event_loop()
    ctx = copy_context()
    # Offload sync pipeline.ingest (graph writes, embeddings) from the event loop.
    result = await loop.run_in_executor(None, lambda: ctx.run(pipeline.ingest, body.model_dump()))
    return {"status": "ok", "result": result}


@router.get("/search/research")
async def search_research(
    q: str = Query(..., description="Search query string"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
    as_of: str | None = Query(None, description="Optional ISO-8601 temporal cutoff"),
) -> dict:
    """Search research memory through the temporal-first retrieval path.

    Public hosted publication treats temporal research retrieval as a required
    contract. If the temporal bridge is unavailable or cannot produce a usable
    candidate set, this route returns ``503`` with a stable error envelope
    instead of degrading to dense-only behavior.
    """
    pipeline = get_pipeline()
    try:
        loop = asyncio.get_event_loop()
        ctx = copy_context()

        def _query() -> list:
            return run_research_search(
                pipeline,
                query=q,
                limit=limit,
                as_of=as_of,
            )

        results = await loop.run_in_executor(None, lambda: ctx.run(_query))
    except TemporalRetrievalRequiredError as exc:
        raise HTTPException(status_code=503, detail=exc.to_http_detail()) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "research_search_failed",
                "message": "Research search failed unexpectedly.",
                "details": {"error": str(exc)},
            },
        ) from exc

    return {"results": results}
