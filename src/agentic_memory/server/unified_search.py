"""Cross-module search orchestration for unified memory retrieval.

This module implements the *fan-out / normalize / merge* pipeline behind
``search_all_memory`` in :mod:`agentic_memory.server.app`. It does not register
MCP tools itself; instead :func:`search_all_memory_sync` returns a
:class:`~agentic_memory.server.result_types.UnifiedSearchResponse` that the app
layer formats for the LLM.

Flow (high level):
    1. **Module selection** — optional filter (``code``, ``web``, ``conversation``);
       default is all three.
    2. **Per-module retrieval** — each submodule runs with its own try/except so
       one failure becomes an ``errors`` entry instead of failing the whole call.
    3. **Normalization** — every hit becomes a :class:`~agentic_memory.server.result_types.UnifiedMemoryHit`
       with a common score and excerpt field.
    4. **Global sort** — :func:`_sort_hits` orders by score, then applies stable
       tie-breakers (temporal vs non-temporal, module name, source id).

Code search uses :func:`~agentic_memory.server.code_search.search_code` with
``SAFE_RETRIEVAL_POLICY`` so unified search stays on the agent-safe semantic
path (no graph rerank) unless that policy is changed deliberately elsewhere.

Web (research) search mirrors the temporal-first strategy in ``search_web_memory``:
vector baseline, optional temporal bridge rerank when seeds and project id exist.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from agentic_memory.chat.pipeline import ConversationIngestionPipeline
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder
from agentic_memory.server.code_search import SAFE_RETRIEVAL_POLICY, search_code
from agentic_memory.server.research_search import search_research
from agentic_memory.server.result_types import UnifiedMemoryHit, UnifiedSearchResponse
from agentic_memory.server.tools import search_conversation_turns_sync
from agentic_memory.web.pipeline import ResearchIngestionPipeline

logger = logging.getLogger(__name__)

# Subset strings accepted in the ``modules`` comma-list from the MCP tool layer.
VALID_MODULES = {"code", "web", "conversation"}


def _clip_excerpt(text: str | None, *, length: int = 300) -> str:
    """Return a compact excerpt for display."""
    return (text or "")[:length]


def _normalize_modules(modules: Iterable[str] | None) -> list[str]:
    """Normalize requested module filters."""
    if modules is None:
        return ["code", "web", "conversation"]
    normalized: list[str] = []
    for module in modules:
        lowered = module.strip().lower()
        if lowered in VALID_MODULES and lowered not in normalized:
            normalized.append(lowered)
    return normalized or ["code", "web", "conversation"]


def _normalize_code_results(
    graph: KnowledgeGraphBuilder,
    *,
    query: str,
    limit: int,
    repo_id: str | None = None,
) -> list[UnifiedMemoryHit]:
    """Run code semantic search and normalize the result shape."""
    rows = search_code(
        graph,
        query=query,
        limit=limit,
        repo_id=repo_id,
        retrieval_policy=SAFE_RETRIEVAL_POLICY,
    )
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)
        sig = str(row.get("sig") or row.get("name") or "")
        hits.append(
            UnifiedMemoryHit(
                module="code",
                source_kind="code_entity",
                source_id=sig,
                title=str(row.get("name") or sig or "Unknown"),
                excerpt=_clip_excerpt(str(row.get("text") or "")),
                score=score,
                baseline_score=score,
                temporal_applied=False,
                rerank_score=(
                    float(row.get("rerank_score", 0.0))
                    if row.get("rerank_score") is not None
                    else None
                ),
                retrieval_provenance=dict(row.get("retrieval_provenance") or {}),
                metadata={
                    "signature": row.get("sig"),
                    "name": row.get("name"),
                    "path": row.get("path"),
                    "repo_id": row.get("repo_id"),
                    "labels": row.get("labels"),
                    "retrieval_provenance": row.get("retrieval_provenance") or {},
                },
            )
        )
    return hits


def _normalize_research_temporal_results(
    rows: list[dict[str, Any]],
) -> list[UnifiedMemoryHit]:
    """Normalize temporal research hits into the unified shape."""
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        confidence = float(row.get("confidence", 0.0) or 0.0)
        relevance = float(row.get("relevance", 0.0) or 0.0)
        subject = (row.get("subject") or {}).get("name", "unknown")
        predicate = row.get("predicate", "RELATED_TO")
        obj = (row.get("object") or {}).get("name", "unknown")
        source_kind = str(row.get("source_kind") or "research")
        source_id = str(row.get("source_id") or f"{subject}:{predicate}:{obj}")
        hits.append(
            UnifiedMemoryHit(
                module="web",
                source_kind=source_kind,
                source_id=source_id,
                title=f"{subject} -[{predicate}]-> {obj}",
                excerpt=_clip_excerpt(str(row.get("text") or "")),
                score=confidence * relevance,
                temporal_score=confidence * relevance,
                temporal_applied=True,
                rerank_score=(
                    float(row.get("rerank_score", 0.0))
                    if row.get("rerank_score") is not None
                    else None
                ),
                retrieval_provenance=dict(row.get("retrieval_provenance") or {}),
                metadata={
                    "subject": row.get("subject"),
                    "predicate": predicate,
                    "object": row.get("object"),
                    "confidence": confidence,
                    "relevance": relevance,
                    "source_id": source_id,
                    "source_kind": source_kind,
                },
            )
        )
    return hits


def _normalize_research_baseline_results(
    rows: list[dict[str, Any]],
) -> list[UnifiedMemoryHit]:
    """Normalize baseline research rows into the unified shape."""
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        labels = row.get("node_labels", []) or []
        source_kind = (
            "research_finding" if "Finding" in labels else "research_chunk" if "Chunk" in labels else "research"
        )
        score = float(row.get("score", 0.0) or 0.0)
        source_id = str(
            row.get("source_id") or row.get("content_hash") or row.get("text") or row.get("research_question") or ""
        )
        hits.append(
            UnifiedMemoryHit(
                module="web",
                source_kind=source_kind,
                source_id=source_id,
                title=row.get("research_question"),
                excerpt=_clip_excerpt(str(row.get("text") or "")),
                score=score,
                baseline_score=score,
                temporal_applied=False,
                rerank_score=(
                    float(row.get("rerank_score", 0.0))
                    if row.get("rerank_score") is not None
                    else None
                ),
                retrieval_provenance=dict(row.get("retrieval_provenance") or {}),
                metadata={
                    "source_agent": row.get("source_agent"),
                    "confidence": row.get("confidence"),
                    "source_key": row.get("source_key"),
                    "project_id": row.get("project_id"),
                    "node_labels": labels,
                },
            )
        )
    return hits


def _normalize_conversation_results(
    rows: list[dict[str, Any]],
    *,
    temporal_applied: bool,
) -> list[UnifiedMemoryHit]:
    """Normalize conversation rows into the unified shape."""
    hits: list[UnifiedMemoryHit] = []
    for row in rows:
        score = float(row.get("score", 0.0) or 0.0)
        session_id = str(row.get("session_id") or "")
        turn_index = int(row.get("turn_index") or 0)
        hits.append(
            UnifiedMemoryHit(
                module="conversation",
                source_kind="conversation_turn",
                source_id=f"{session_id}:{turn_index}",
                title=f"{row.get('role', 'unknown')} turn",
                excerpt=_clip_excerpt(str(row.get("content") or "")),
                score=score,
                baseline_score=None if temporal_applied else score,
                temporal_score=score if temporal_applied else None,
                temporal_applied=temporal_applied,
                rerank_score=(
                    float(row.get("rerank_score", 0.0))
                    if row.get("rerank_score") is not None
                    else None
                ),
                retrieval_provenance=dict(row.get("retrieval_provenance") or {}),
                metadata={
                    "session_id": session_id,
                    "turn_index": turn_index,
                    "role": row.get("role"),
                    "source_agent": row.get("source_agent"),
                    "timestamp": row.get("timestamp"),
                    "ingested_at": row.get("ingested_at"),
                    "entities": row.get("entities") or [],
                    "entity_types": row.get("entity_types") or [],
                },
            )
        )
    return hits


def _search_research_structured(
    pipeline: ResearchIngestionPipeline,
    *,
    query: str,
    limit: int,
    as_of: str | None,
) -> list[UnifiedMemoryHit]:
    """Run structured research search with temporal/rerank behavior."""

    rows = search_research(
        pipeline,
        query=query,
        limit=limit,
        as_of=as_of,
    )
    if not rows:
        return []
    if rows[0].get("temporal_applied"):
        return _normalize_research_temporal_results(rows)[:limit]
    return _normalize_research_baseline_results(rows)[:limit]


def _search_conversation_structured(
    pipeline: ConversationIngestionPipeline,
    *,
    query: str,
    project_id: str | None,
    limit: int,
    as_of: str | None,
) -> list[UnifiedMemoryHit]:
    """Run structured conversation search and infer whether temporal reranking applied."""
    results = search_conversation_turns_sync(
        pipeline,
        query=query,
        project_id=project_id,
        role=None,
        limit=limit,
        as_of=as_of,
        log_prefix="search_all_memory.conversation",
    )
    provenance = dict((results[0].get("retrieval_provenance") or {})) if results else {}
    temporal_applied = bool(provenance.get("temporal_applied", False))
    return _normalize_conversation_results(results, temporal_applied=temporal_applied)


def _sort_hits(hits: list[UnifiedMemoryHit], limit: int) -> list[UnifiedMemoryHit]:
    """Sort normalized hits by score with stable module-aware tie-breaking.

    Tie-break order (after descending score): prefer temporal-enhanced hits,
    then deterministic ``module`` and ``source_id`` so ordering is stable
    across runs for the same inputs.
    """
    ordered = sorted(
        hits,
        key=lambda hit: (
            -float(hit.score),
            0 if hit.temporal_applied else 1,
            hit.module,
            hit.source_id,
        ),
    )
    return ordered[:limit]


def search_all_memory_sync(
    *,
    query: str,
    limit: int = 10,
    project_id: str | None = None,
    repo_id: str | None = None,
    as_of: str | None = None,
    modules: Iterable[str] | None = None,
    graph: KnowledgeGraphBuilder | None = None,
    research_pipeline: ResearchIngestionPipeline | None = None,
    conversation_pipeline: ConversationIngestionPipeline | None = None,
) -> UnifiedSearchResponse:
    """Search code, web, and conversation memory; return one normalized response.

    This is the synchronous core used by the MCP ``search_all_memory`` tool.
    Pass ``None`` for any unavailable dependency (for example no graph or no
    research pipeline); that module is skipped without raising.

    Args:
        query: Natural-language query shared across enabled modules.
        limit: Maximum number of hits after global merge and sort.
        project_id: Conversation (and temporal web) project scope when applicable.
        repo_id: Optional explicit code-graph repository scope.
        as_of: Optional ISO-8601 cutoff string for ingested-at filtering.
        modules: Iterable of submodule names or ``None`` for all.
        graph: Live :class:`~agentic_memory.ingestion.graph.KnowledgeGraphBuilder`
            for code search; if ``None``, code results are omitted.
        research_pipeline: Ingestion pipeline with embedder and Neo4j connection.
        conversation_pipeline: Conversation pipeline for turn search.

    Returns:
        :class:`~agentic_memory.server.result_types.UnifiedSearchResponse` with
        merged ``results`` and per-module ``errors`` for non-fatal failures.
    """
    safe_limit = max(1, int(limit))
    selected_modules = _normalize_modules(modules)
    hits: list[UnifiedMemoryHit] = []
    errors: list[dict[str, str]] = []

    if "code" in selected_modules and graph is not None:
        try:
            if repo_id is None:
                hits.extend(
                    _normalize_code_results(
                        graph,
                        query=query,
                        limit=safe_limit,
                    )
                )
            else:
                hits.extend(
                    _normalize_code_results(
                        graph,
                        query=query,
                        limit=safe_limit,
                        repo_id=repo_id,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_all_memory code module failed: %s", exc)
            errors.append({"module": "code", "message": str(exc)})

    if "web" in selected_modules and research_pipeline is not None:
        try:
            hits.extend(
                _search_research_structured(
                    research_pipeline,
                    query=query,
                    limit=safe_limit,
                    as_of=as_of,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_all_memory web module failed: %s", exc)
            errors.append({"module": "web", "message": str(exc)})

    if "conversation" in selected_modules and conversation_pipeline is not None:
        try:
            hits.extend(
                _search_conversation_structured(
                    conversation_pipeline,
                    query=query,
                    project_id=project_id,
                    limit=safe_limit,
                    as_of=as_of,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("search_all_memory conversation module failed: %s", exc)
            errors.append({"module": "conversation", "message": str(exc)})

    return UnifiedSearchResponse(results=_sort_hits(hits, safe_limit), errors=errors)
