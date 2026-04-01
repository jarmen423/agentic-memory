"""Research ingest and search endpoints — requires Bearer auth."""

from __future__ import annotations

import asyncio
import logging
from contextvars import copy_context

from fastapi import APIRouter, Depends, Query

from am_server.auth import require_auth
from am_server.dependencies import get_pipeline
from am_server.models import ResearchIngestRequest

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/ingest/research", status_code=202)
async def ingest_research(body: ResearchIngestRequest) -> dict:
    """Ingest a research report or finding into the memory graph.

    Delegates synchronous pipeline.ingest() to a thread pool executor.
    session_id MUST come from the request body — never generated server-side.
    """
    pipeline = get_pipeline()
    loop = asyncio.get_event_loop()
    ctx = copy_context()
    result = await loop.run_in_executor(None, lambda: ctx.run(pipeline.ingest, body.model_dump()))
    return {"status": "ok", "result": result}


@router.get("/search/research")
async def search_research(
    q: str = Query(..., description="Search query string"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
) -> dict:
    """Search the research memory graph for relevant findings.

    Returns a list of matching research nodes. If the pipeline connection
    is not available (e.g., during tests with a mock pipeline), returns
    an empty results list.
    """
    pipeline = get_pipeline()
    try:
        conn = pipeline._conn  # type: ignore[attr-defined]
        loop = asyncio.get_event_loop()
        ctx = copy_context()

        def _query() -> list:
            with conn.session() as session:
                cypher = (
                    "CALL db.index.vector.queryNodes("
                    "  'research_embeddings', $limit, $embedding"
                    ") YIELD node, score "
                    "RETURN node.content AS content, node.title AS title, score "
                    "LIMIT $limit"
                )
                # Without a query embedding we do a text fallback
                text_cypher = (
                    "MATCH (n:Research) "
                    "WHERE toLower(n.content) CONTAINS toLower($q) "
                    "   OR toLower(coalesce(n.title,'')) CONTAINS toLower($q) "
                    "RETURN n.content AS content, n.title AS title, 1.0 AS score "
                    "LIMIT $limit"
                )
                result = session.run(text_cypher, q=q, limit=limit)
                return [dict(record) for record in result]

        results = await loop.run_in_executor(None, lambda: ctx.run(_query))
    except Exception:
        results = []

    return {"results": results}
