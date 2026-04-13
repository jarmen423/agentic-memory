"""HTTP route for unified search across memory backends.

Exposes a single authenticated endpoint that delegates to
``search_all_memory_sync`` in ``agentic_memory.server.unified_search``. That
function merges code (graph), web, conversation, and research results according
to ``modules`` and optional filters.

Dependencies:
    ``get_graph``: Legacy code-memory graph accessor used for code-path search.
    ``get_pipeline`` / ``get_conversation_pipeline``: Research and conversation
    pipelines passed through so unified search can query each subsystem consistently.

All routes require Bearer authentication.
"""

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
    repo_id: str | None = Query(None, description="Optional repo filter for code search"),
    as_of: str | None = Query(None, description="Optional ISO-8601 temporal cutoff"),
    modules: str | None = Query(
        None,
        description="Optional comma-separated modules: code,web,conversation",
    ),
) -> dict:
    """Run unified search and return a normalized, JSON-serializable payload.

    ``modules`` (when provided) is split on commas and trimmed; allowed tokens
    typically include ``code``, ``web``, and ``conversation`` — see unified search
    implementation for the authoritative set and default behavior when omitted.

    Args:
        q: User query string forwarded to each enabled memory module.
        limit: Per-module or global cap depending on ``unified_search`` semantics.
        project_id: Optional scope for project-aware backends.
        repo_id: Optional repository scope for code-graph search.
        as_of: Optional ISO-8601 cutoff for time-bounded retrieval where supported.
        modules: Comma-separated subset of modules to include; ``None`` means use
            unified search defaults (all applicable modules).

    Returns:
        A dict produced by ``UnifiedSearchPayload.to_dict()`` — stable keys for
        clients aggregating code, web, conversation, and research hits.

    Note:
        ``get_graph()`` supplies the code-memory graph handle; research and
        conversation pipelines are injected separately so unified search can
        orchestrate all three without hard-coding globals inside the library.
    """
    requested_modules = None
    if modules:
        requested_modules = [part.strip() for part in modules.split(",") if part.strip()]

    # Single entry point: merges graph + pipeline-backed search according to filters/modules.
    payload = search_all_memory_sync(
        query=q,
        limit=limit,
        project_id=project_id,
        repo_id=repo_id,
        as_of=as_of,
        modules=requested_modules,
        graph=get_graph(),
        research_pipeline=get_pipeline(),
        conversation_pipeline=get_conversation_pipeline(),
    )
    return payload.to_dict()
