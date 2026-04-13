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
from agentic_memory.server.result_types import UnifiedMemoryHit, UnifiedSearchResponse
from agentic_memory.server.tools import search_conversation_turns_sync
from agentic_memory.temporal.seeds import (
    collect_seed_entities,
    extract_query_seed_entities,
    parse_as_of_to_micros,
)
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


def _filter_rows_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """Apply current string-based ingested_at cutoff when present."""
    if as_of is None:
        return rows
    return [row for row in rows if (row.get("ingested_at") or "") <= as_of]


def _dominant_project_id(rows: list[dict[str, Any]]) -> str | None:
    """Pick the project_id with the strongest cumulative baseline score."""
    project_scores: dict[str, float] = {}
    for row in rows:
        project_id = row.get("project_id")
        if not project_id:
            continue
        project_scores[str(project_id)] = project_scores.get(str(project_id), 0.0) + float(
            row.get("score", 1.0) or 1.0
        )
    if not project_scores:
        return None
    return max(project_scores.items(), key=lambda item: item[1])[0]


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
        evidence = (row.get("evidence") or [{}])[0]
        subject = (row.get("subject") or {}).get("name", "unknown")
        predicate = row.get("predicate", "RELATED_TO")
        obj = (row.get("object") or {}).get("name", "unknown")
        hits.append(
            UnifiedMemoryHit(
                module="web",
                source_kind=str(evidence.get("sourceKind") or "research"),
                source_id=str(evidence.get("sourceId") or f"{subject}:{predicate}:{obj}"),
                title=f"{subject} -[{predicate}]-> {obj}",
                excerpt=_clip_excerpt(str(evidence.get("rawExcerpt") or "")),
                score=confidence * relevance,
                temporal_score=confidence * relevance,
                temporal_applied=True,
                metadata={
                    "subject": row.get("subject"),
                    "predicate": predicate,
                    "object": row.get("object"),
                    "confidence": confidence,
                    "relevance": relevance,
                    "evidence": row.get("evidence") or [],
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
        source_id = str(row.get("content_hash") or row.get("text") or row.get("research_question") or "")
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
    """Run structured research search with temporal-first fallback behavior."""
    embedding = pipeline._embedder.embed(query)
    with pipeline._conn.session() as session:  # type: ignore[attr-defined]
        baseline_results = session.run(
            """
            CALL db.index.vector.queryNodes('research_embeddings', $limit, $embedding)
            YIELD node, score
            RETURN
                node.text AS text,
                node.source_agent AS source_agent,
                node.research_question AS research_question,
                node.confidence AS confidence,
                node.source_key AS source_key,
                node.content_hash AS content_hash,
                node.project_id AS project_id,
                node.ingested_at AS ingested_at,
                node.entities AS entities,
                node.entity_types AS entity_types,
                labels(node) AS node_labels,
                score
            ORDER BY score DESC
            """,
            limit=max(1, int(limit)),
            embedding=embedding,
        ).data()

    baseline_results = _filter_rows_as_of(baseline_results, as_of)
    if not baseline_results:
        return []

    # Same temporal bridge pattern as app.search_web_memory: baseline seeds the graph walk.
    bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None
    project_id = _dominant_project_id(baseline_results)
    if bridge is not None and bridge.is_available() and project_id is not None:
        seeds = collect_seed_entities(baseline_results, limit=5)
        if not seeds:
            try:
                seeds = extract_query_seed_entities(query, pipeline._extractor)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.warning("search_all_memory web query seed extraction failed: %s", exc)
                seeds = []
        if seeds:
            try:
                temporal_payload = bridge.retrieve(
                    project_id=project_id,
                    seed_entities=seeds,
                    as_of_us=parse_as_of_to_micros(as_of),
                    max_edges=max(limit * 2, limit),
                )
                temporal_results = temporal_payload.get("results") or []
                if temporal_results:
                    return _normalize_research_temporal_results(temporal_results)[:limit]
            except Exception as exc:  # noqa: BLE001
                logger.warning("search_all_memory web module falling back after temporal failure: %s", exc)

    return _normalize_research_baseline_results(baseline_results)[:limit]


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
    bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None
    temporal_applied = bool(project_id and bridge is not None and bridge.is_available())
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
