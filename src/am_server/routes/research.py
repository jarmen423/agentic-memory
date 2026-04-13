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
) -> dict:
    """Search ``Research`` nodes in Neo4j (text match on content/title).

    When a Neo4j session is available, runs a case-insensitive ``CONTAINS`` query
    over ``n.content`` and ``n.title``. The Cypher also references the
    ``research_embeddings`` vector index name for alignment with the graph schema;
    this handler's live path uses the text fallback branch (no query embedding).

    If the pipeline has no connection or any error occurs while opening a session
    or running the query, returns an empty ``results`` list (e.g. tests with a
    mock pipeline).

    Args:
        q: Free-text query matched against research content and title.
        limit: Maximum rows to return (clamped by FastAPI to 1..50).

    Returns:
        ``{"results": [<row dicts with content, title, score>]}``. Each row uses
        score ``1.0`` for the text fallback. ``results`` is ``[]`` on failure or
        missing connection.

    Note:
        Uses ``pipeline._conn`` internally; keep in sync with how the research
        ``Pipeline`` exposes its Neo4j driver in tests and production.
    """
    pipeline = get_pipeline()
    try:
        conn = pipeline._conn  # type: ignore[attr-defined]
        loop = asyncio.get_event_loop()
        ctx = copy_context()

        def _query() -> list:
            with conn.session() as session:
                # Schema hook: vector index name matches graph setup; live path uses text_cypher below.
                cypher = (
                    "CALL db.index.vector.queryNodes("
                    "  'research_embeddings', $limit, $embedding"
                    ") YIELD node, score "
                    "RETURN node.content AS content, node.title AS title, score "
                    "LIMIT $limit"
                )
                # Text fallback: no embedding in this request path — substring match on Research nodes.
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
