"""MCP tool registration, conversation/research pipelines, and the code ``Toolkit``.

This module is the main bridge between **Model Context Protocol (MCP) tool handlers**
and Agentic Memory backends (Neo4j, embedding providers, optional temporal graph).
It is organized in three layers:

1. **Private helpers** — ``_vector_conversation_search``,
   ``_text_conversation_search``, ``_fetch_conversation_*``,
   ``search_conversation_turns_sync``, etc. Implement retrieval strategies (vector
   index → optional temporal enrichment → deterministic text fallback) and shared
   hydration logic used by MCP tools and tests.

2. **Registration entrypoints** — ``register_conversation_tools`` and
   ``register_schedule_tools`` attach async handlers to a FastMCP instance at
   server startup. Handlers **offload blocking work** (Neo4j sessions, embedders,
   schedulers) via ``asyncio.get_event_loop().run_in_executor`` so the MCP event
   loop is not blocked.

3. **Toolkit** — Synchronous, framework-agnostic wrappers around
   ``KnowledgeGraphBuilder`` and ``search_code`` that return **Markdown reports**
   for LLM consumption. Used by the internal MCP app and scripts; conversation
   memory is **not** routed through ``Toolkit`` (see registration functions).

Integration:
    Imported by ``agentic_memory.server.app``, which calls ``register_*`` during
    startup and constructs ``Toolkit`` with a shared ``KnowledgeGraphBuilder``.
    Cached helpers ``_get_mcp_conversation_pipeline``,
    ``_get_mcp_research_pipeline``, and ``_get_mcp_research_scheduler`` read
    environment configuration and are **separate** from ``am_server`` process
    singletons when the MCP server runs standalone.

Error paths (conversation tools):
    * Vector search failures in ``search_conversation_turns_sync`` trigger
      structured log event ``conversation_search_fallback`` and fall back to
      substring search; ``as_of`` filtering still applies.
    * Missing temporal bridge, missing seeds, or temporal retrieve errors fall
      back to vector (or text) baselines with the same log event.
    * MCP wrappers ``search_conversations`` and ``get_conversation_context`` log
      errors and return ``[]`` / ``{"turns": []}`` rather than raising.
    * ``add_message`` logs failures and returns ``{"error": "<message>"}``.

Error paths (Toolkit):
    Neo4j ``DatabaseError`` / ``ClientError`` are caught, logged where applicable,
    and surfaced as **error strings** in the returned report (no exceptions to
    the caller).

Error paths (research schedule tools):
    If the scheduler cannot be configured (missing pipeline, keys, etc.), tools
    return JSON strings with ``status: "error"``. ``run_research_session``
    validates inputs before touching the scheduler.

Dependencies:
    Neo4j labels/indexes (e.g. ``Memory:Conversation:Turn``, vector index
    ``chat_embeddings``), ``EmbeddingService`` / ``build_embedding_service``,
    optional ``TemporalBridge``, ``ResearchScheduler`` + Brave Search for web
    schedules.
"""

from collections.abc import Callable
from typing import Any, Dict, List, Optional
import asyncio
import json
import logging
import os
from functools import lru_cache

import neo4j
from mcp.types import ToolAnnotations
from agentic_memory.chat.pipeline import ConversationIngestionPipeline
from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.embedding import EmbeddingService
from agentic_memory.core.entity_extraction import EntityExtractionService
from agentic_memory.core.extraction_llm import resolve_extraction_llm_config
from agentic_memory.core.request_context import get_request_id
from agentic_memory.core.retry import retry_transient
from agentic_memory.core.runtime_embedding import build_embedding_service
from agentic_memory.core.scheduler import ResearchScheduler
from agentic_memory.temporal.bridge import get_temporal_bridge
from agentic_memory.temporal.seeds import (
    collect_seed_entities,
    extract_query_seed_entities,
    parse_as_of_to_micros,
    parse_conversation_source_id,
)
from agentic_memory.web.pipeline import ResearchIngestionPipeline
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder
from agentic_memory.server.code_search import SAFE_RETRIEVAL_POLICY, search_code

logger = logging.getLogger(__name__)
ToolAnnotationResolver = Callable[[str], ToolAnnotations | None]


def _tool_registration_kwargs(
    tool_name: str,
    description: str,
    annotation_resolver: ToolAnnotationResolver | None,
) -> dict[str, Any]:
    """Build keyword arguments for ``@mcp.tool`` registration.

    Merges the MCP-visible ``name`` and ``description`` with optional
    ``ToolAnnotations`` when ``annotation_resolver`` returns a value. Used so
    the same handler can be registered on multiple MCP apps (internal vs public)
    with different annotation policies without duplicating handler code.

    Args:
        tool_name: Stable MCP tool identifier.
        description: MCP tool description string passed through to clients.
        annotation_resolver: Optional callback ``(name) -> annotations | None``.

    Returns:
        Dict suitable for unpacking into ``FastMCP.tool(...)``.
    """

    kwargs: dict[str, Any] = {
        "name": tool_name,
        "description": description,
    }
    if annotation_resolver is not None:
        annotations = annotation_resolver(tool_name)
        if annotations is not None:
            kwargs["annotations"] = annotations
    return kwargs


def _filter_rows_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """Filter conversation rows to those ingested on or before ``as_of``.

    Compares lexicographically on ISO-8601 ``ingested_at`` strings when ``as_of``
    is set; no-op when ``as_of`` is ``None``.

    Args:
        rows: Turn-shaped dicts containing optional ``ingested_at``.
        as_of: Inclusive upper bound for ``ingested_at``, or ``None``.

    Returns:
        Filtered list (may be shorter than ``rows``).
    """
    if as_of is None:
        return rows
    return [row for row in rows if (row.get("ingested_at") or "") <= as_of]


def _vector_conversation_search(
    conn: ConnectionManager,
    embedder: EmbeddingService,
    *,
    query: str,
    project_id: str | None,
    role: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Run vector retrieval over indexed conversation turns.

    Queries Neo4j index ``chat_embeddings`` via ``db.index.vector.queryNodes`` and
    applies optional ``project_id`` / ``role`` filters.

    Args:
        conn: Shared connection manager for Neo4j sessions.
        embedder: Provider used to embed ``query``.
        query: Natural language query text.
        project_id: If set, restrict to turns for this project.
        role: If set, restrict to this speaker role (e.g. ``user``).
        limit: Maximum rows to return from the index call.

    Returns:
        List of turn dicts plus a ``score`` field from vector similarity.
    """
    query_embedding = embedder.embed(query)
    with conn.session() as session:
        cypher = (
            "CALL db.index.vector.queryNodes("
            "  'chat_embeddings', $limit, $embedding"
            ") YIELD node, score "
            "WHERE ($project_id IS NULL OR node.project_id = $project_id)"
            "  AND ($role IS NULL OR node.role = $role) "
            "RETURN "
            "    node.session_id     AS session_id, "
            "    node.turn_index     AS turn_index, "
            "    node.role           AS role, "
            "    node.content        AS content, "
            "    node.source_agent   AS source_agent, "
            "    node.timestamp      AS timestamp, "
            "    node.ingested_at    AS ingested_at, "
            "    node.entities       AS entities, "
            "    node.entity_types   AS entity_types, "
            "    score "
            "ORDER BY score DESC "
            "LIMIT $limit"
        )
        return [dict(r) for r in session.run(
            cypher,
            embedding=query_embedding,
            project_id=project_id,
            role=role,
            limit=limit,
        )]


def _text_conversation_search(
    conn: ConnectionManager,
    *,
    query: str,
    project_id: str | None,
    role: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Substring fallback search over conversation content.

    Used when embedding or vector index access fails so callers still get
    deterministic matches. Assigns a constant ``score`` of ``1.0`` (no ranking
    beyond Neo4j row order / limit).

    Args:
        conn: Neo4j connection manager.
        query: Substring matched case-insensitively against ``n.content``.
        project_id: Optional project filter.
        role: Optional role filter.
        limit: Maximum number of turns.

    Returns:
        Matching turn dicts with synthetic ``score``.
    """
    with conn.session() as session:
        text_cypher = (
            "MATCH (n:Memory:Conversation:Turn) "
            "WHERE toLower(n.content) CONTAINS toLower($q) "
            "  AND ($project_id IS NULL OR n.project_id = $project_id) "
            "  AND ($role IS NULL OR n.role = $role) "
            "RETURN "
            "    n.session_id    AS session_id, "
            "    n.turn_index    AS turn_index, "
            "    n.role          AS role, "
            "    n.content       AS content, "
            "    n.source_agent  AS source_agent, "
            "    n.timestamp     AS timestamp, "
            "    n.ingested_at   AS ingested_at, "
            "    n.entities      AS entities, "
            "    n.entity_types  AS entity_types, "
            "    1.0 AS score "
            "LIMIT $limit"
        )
        return [dict(record) for record in session.run(
            text_cypher,
            q=query,
            project_id=project_id,
            role=role,
            limit=limit,
        )]


def _fetch_conversation_turn(
    conn: ConnectionManager,
    *,
    session_id: str,
    turn_index: int,
) -> dict[str, Any] | None:
    """Load a single turn by ``session_id`` and ``turn_index``.

    Args:
        conn: Neo4j connection manager.
        session_id: Conversation session identifier.
        turn_index: Zero-based turn index within the session.

    Returns:
        Turn fields as a dict, or ``None`` if no node matches.
    """
    with conn.session() as session:
        result = session.run(
            (
                "MATCH (t:Memory:Conversation:Turn {session_id: $session_id, turn_index: $turn_index}) "
                "RETURN "
                "    t.session_id AS session_id, "
                "    t.turn_index AS turn_index, "
                "    t.role AS role, "
                "    t.content AS content, "
                "    t.source_agent AS source_agent, "
                "    t.timestamp AS timestamp, "
                "    t.ingested_at AS ingested_at, "
                "    t.entities AS entities"
            ),
            session_id=session_id,
            turn_index=turn_index,
        ).single()
    return dict(result) if result else None


def _fetch_conversation_context_window(
    conn: ConnectionManager,
    *,
    session_id: str,
    turn_index: int,
    as_of: str | None,
) -> list[dict[str, Any]]:
    """Fetch neighboring turns at ``turn_index - 1`` and ``turn_index + 1``.

    Used to supply local dialog context around a hit. Results respect ``as_of``
    via :func:`_filter_rows_as_of` (neighbor turns after the cutoff are dropped).

    Args:
        conn: Neo4j connection manager.
        session_id: Session containing the matched turn.
        turn_index: Index of the matched turn (neighbors are ±1).
        as_of: Optional ingested-at ceiling for context rows.

    Returns:
        Up to two turn dicts ordered by ``turn_index``.
    """
    with conn.session() as session:
        ctx_result = session.run(
            (
                "MATCH (t:Memory:Conversation:Turn {session_id: $session_id}) "
                "WHERE t.turn_index IN [$prev_index, $next_index] "
                "  AND t.turn_index <> $matched_turn_index "
                "RETURN "
                "    t.turn_index AS turn_index, "
                "    t.role AS role, "
                "    t.content AS content, "
                "    t.ingested_at AS ingested_at "
                "ORDER BY t.turn_index"
            ),
            session_id=session_id,
            prev_index=turn_index - 1,
            next_index=turn_index + 1,
            matched_turn_index=turn_index,
        )
        window = [dict(r) for r in ctx_result]
    return _filter_rows_as_of(window, as_of)


def _hydrate_temporal_conversation_results(
    conn: ConnectionManager,
    temporal_results: list[dict[str, Any]],
    *,
    limit: int,
    role: str | None,
    as_of: str | None,
) -> list[dict[str, Any]]:
    """Turn temporal bridge ``evidence`` entries into hydrated turn dicts.

    Skips non-conversation evidence, malformed ``sourceId`` values, duplicates,
    role mismatches, and turns after ``as_of``. Scores are derived from temporal
    ``confidence`` and ``relevance`` on the parent ranked result.

    Args:
        conn: Neo4j connection manager.
        temporal_results: ``results`` list from ``TemporalBridge.retrieve``.
        limit: Maximum hydrated turns to return.
        role: If set, exclude turns whose ``role`` differs.
        as_of: Optional ingested-at ceiling.

    Returns:
        Hydrated turns (with ``score``), newest-first by processing order, capped
        at ``limit``.
    """
    hydrated: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    for ranked in temporal_results:
        temporal_score = float(ranked.get("confidence", 0.0) or 0.0) * float(
            ranked.get("relevance", 1.0) or 1.0
        )
        for evidence in ranked.get("evidence") or []:
            if evidence.get("sourceKind") != "conversation_turn":
                continue
            try:
                session_id, turn_index = parse_conversation_source_id(
                    str(evidence.get("sourceId", ""))
                )
            except (ValueError, TypeError):
                continue
            key = (session_id, turn_index)
            if key in seen:
                continue
            turn = _fetch_conversation_turn(
                conn,
                session_id=session_id,
                turn_index=turn_index,
            )
            if turn is None:
                continue
            if role is not None and turn.get("role") != role:
                continue
            if as_of is not None and (turn.get("ingested_at") or "") > as_of:
                continue
            turn["score"] = temporal_score
            hydrated.append(turn)
            seen.add(key)
            if len(hydrated) >= limit:
                return hydrated

    return hydrated


def search_conversation_turns_sync(
    pipeline: ConversationIngestionPipeline,
    *,
    query: str,
    project_id: str | None,
    role: str | None,
    limit: int,
    as_of: str | None,
    log_prefix: str,
) -> list[dict[str, Any]]:
    """Temporal-first conversation search with deterministic text fallback.

    Implements a three-tier retrieval strategy:
    1. Vector search via ``chat_embeddings`` Neo4j index.
    2. Temporal graph enrichment via ``TemporalBridge`` (if available and
       ``project_id`` is provided), which resolves entity-relationship paths
       through the knowledge graph for more contextually relevant results.
    3. Full-text keyword fallback if vector search fails completely.

    The ``as_of`` cutoff is applied at each tier to support time-bounded
    memory retrieval (e.g., "what did we know before this date?").

    Error handling:
        Any exception from the initial vector search triggers a warning log
        (``conversation_search_fallback`` / ``fallback: text_search_after_vector_failure``)
        and switches to :func:`_text_conversation_search`. When ``project_id`` is
        set, temporal retrieval failures are non-fatal: the caller receives the
        baseline vector results (already ``as_of``-filtered) after logging.

    Args:
        pipeline: A ``ConversationIngestionPipeline`` instance that provides
            ``_conn`` (ConnectionManager), ``_embedder`` (EmbeddingService),
            and ``_extractor`` (EntityExtractionService) attributes.
        query: Natural language search string.
        project_id: If provided, restricts search to this project and enables
            temporal graph enrichment.  Pass ``None`` to search all projects
            (temporal enrichment is skipped when project_id is absent).
        role: Optional speaker role filter ("user" | "assistant").
        limit: Maximum number of turns to return.
        as_of: Optional ISO-8601 timestamp ceiling for ``ingested_at`` filtering.
        log_prefix: Label for log messages (caller identity, e.g. tool name).

    Returns:
        List of conversation turn dicts ordered by relevance score descending.
        Each dict contains: session_id, turn_index, role, content, source_agent,
        timestamp, ingested_at, entities, score.
    """
    conn = pipeline._conn  # type: ignore[attr-defined]
    embedder = pipeline._embedder  # type: ignore[attr-defined]
    extractor = pipeline._extractor  # type: ignore[attr-defined]
    bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None

    try:
        baseline_rows = _vector_conversation_search(
            conn,
            embedder,
            query=query,
            project_id=project_id,
            role=role,
            limit=limit,
        )
    except Exception as exc:
        # Embedding or vector index failure: deterministic text search still works.
        logger.warning(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "text_search_after_vector_failure",
                "error_type": type(exc).__name__,
            },
        )
        return _filter_rows_as_of(
            _text_conversation_search(
                conn,
                query=query,
                project_id=project_id,
                role=role,
                limit=limit,
            ),
            as_of,
        )

    filtered_baseline = _filter_rows_as_of(baseline_rows, as_of)
    if project_id is None:
        return filtered_baseline
    if bridge is None or not bridge.is_available():
        logger.info(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "temporal_bridge_unavailable",
                "error_type": None,
            },
        )
        return filtered_baseline

    seeds = collect_seed_entities(filtered_baseline, limit=5)
    if not seeds:
        try:
            seeds = extract_query_seed_entities(query, extractor)
        except Exception as exc:
            logger.warning("%s query seed extraction failed: %s", log_prefix, exc)
            seeds = []

    if not seeds:
        logger.info(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "no_temporal_seeds",
                "error_type": None,
            },
        )
        return filtered_baseline

    try:
        temporal_payload = retry_transient(
            lambda: bridge.retrieve(
                project_id=project_id,
                seed_entities=seeds,
                as_of_us=parse_as_of_to_micros(as_of),
                max_edges=max(limit * 2, limit),
            )
        )
    except Exception as exc:
        logger.warning(
            "conversation_search_fallback",
            extra={
                "event": "temporal_fallback",
                "request_id": get_request_id(),
                "memory_module": "conversation",
                "provider": getattr(embedder, "provider", None),
                "fallback": "temporal_retrieve_failed",
                "error_type": type(exc).__name__,
            },
        )
        return filtered_baseline

    temporal_hits = _hydrate_temporal_conversation_results(
        conn,
        temporal_payload.get("results") or [],
        limit=limit,
        role=role,
        as_of=as_of,
    )
    if temporal_hits:
        return temporal_hits

    logger.info(
        "conversation_search_fallback",
        extra={
            "event": "temporal_fallback",
            "request_id": get_request_id(),
            "memory_module": "conversation",
            "provider": getattr(embedder, "provider", None),
            "fallback": "empty_temporal_result",
            "error_type": None,
        },
    )
    return filtered_baseline


@lru_cache(maxsize=1)
def _get_mcp_conversation_pipeline() -> ConversationIngestionPipeline:
    """Return a process-local singleton ``ConversationIngestionPipeline`` for MCP.

    Configuration is read from environment variables (Neo4j URI, credentials,
    chat embedding profile via :func:`build_embedding_service`, extraction
    service, optional temporal bridge). Cached with ``lru_cache`` so every MCP
    tool shares one pipeline per process.

    Note:
        This is intentionally **not** the same object as ``am_server`` pipeline
        helpers when those run in another process; each runtime constructs its own
        cached instance.

    Returns:
        Shared pipeline used by conversation MCP tools.
    """
    conn = ConnectionManager(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    embedder = build_embedding_service("chat")
    extractor = EntityExtractionService.from_env()
    return ConversationIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def _get_mcp_research_pipeline() -> ResearchIngestionPipeline | None:
    """Return a cached web research pipeline, or ``None`` if misconfigured.

    Requires a working ``web`` embedding service **and** extraction LLM API
    credentials. When prerequisites are missing, logs a warning and returns
    ``None`` so schedule tools can degrade without raising at import time.

    Returns:
        Shared :class:`ResearchIngestionPipeline`, or ``None`` if unavailable.
    """
    extraction_llm = resolve_extraction_llm_config()
    try:
        embedder = build_embedding_service("web")
    except ValueError:
        embedder = None
    if embedder is None or not extraction_llm.api_key:
        logger.warning(
            "Research MCP pipeline unavailable: missing embedding or extraction LLM API key."
        )
        return None

    conn = ConnectionManager(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key,
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    return ResearchIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def _get_mcp_research_scheduler() -> ResearchScheduler | None:
    """Return a cached :class:`ResearchScheduler` for MCP, or ``None``.

    Depends on :func:`_get_mcp_research_pipeline`, extraction LLM configuration,
    and a Brave Search API key (``BRAVE_SEARCH_API_KEY`` or ``BRAVE_API_KEY``).
    Logs and returns ``None`` when any dependency is absent.

    Returns:
        Scheduler instance, or ``None`` if research automation cannot start.
    """
    pipeline = _get_mcp_research_pipeline()
    extraction_llm = resolve_extraction_llm_config()
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
    if pipeline is None or not extraction_llm.api_key or not brave_api_key:
        logger.warning("Research scheduler unavailable: missing pipeline or API keys.")
        return None

    return ResearchScheduler(
        connection_manager=pipeline._conn,  # type: ignore[attr-defined]
        extraction_llm_api_key=extraction_llm.api_key,
        extraction_llm_model=extraction_llm.model,
        extraction_llm_provider=extraction_llm.provider,
        extraction_llm_base_url=extraction_llm.base_url,
        brave_api_key=brave_api_key,
        pipeline=pipeline,
    )

class Toolkit:
    """Synchronous code-graph and git reporting for MCP tools and scripts.

    Wraps :class:`KnowledgeGraphBuilder` and :func:`search_code` to produce
    Markdown strings suitable for LLM context. Callers include the internal MCP
    server and tests; this class does **not** perform async I/O and does **not**
    implement conversation memory (those tools use
    :func:`register_conversation_tools`).

    Error contract:
        Neo4j client/database errors are caught and returned as human-readable
        error lines inside the Markdown string so MCP layers can forward them
        without stack traces.

    Attributes:
        graph: Shared graph builder (driver lifecycle owned by the caller).
    """

    def __init__(self, graph: KnowledgeGraphBuilder):
        """Initialize Toolkit with a pre-connected graph builder.

        Args:
            graph: An initialized ``KnowledgeGraphBuilder`` instance.  The caller
                is responsible for its lifecycle (``graph.close()`` on shutdown).
        """
        self.graph = graph

    def semantic_search(
        self,
        query: str,
        limit: int = 5,
        repo_id: str | None = None,
        retrieval_policy: str = SAFE_RETRIEVAL_POLICY,
    ) -> str:
        """Search the code graph and format hits as a Markdown report.

        Delegates retrieval to :func:`agentic_memory.server.code_search.search_code`,
        then appends **provenance** lines (policy, mode, structural edges used)
        so agents understand how results were produced. Default ``retrieval_policy``
        is ``safe`` to keep callers on the supported path unless they opt into
        graph reranking.

        Args:
            query: Natural-language code search request.
            limit: Maximum number of code results to return.
            repo_id: Optional repo scope override.
            retrieval_policy: ``safe`` by default; ``graph_reranked`` enables
                structural reranking without ``CALLS`` edges.

        Returns:
            Markdown report, ``No relevant code found...`` when empty, or
            ``Error executing search: ...`` on Neo4j ``DatabaseError`` /
            ``ClientError``.
        """
        try:
            results = search_code(
                self.graph,
                query=query,
                limit=limit,
                repo_id=repo_id,
                retrieval_policy=retrieval_policy,
            )
            if not results:
                return "No relevant code found in the graph."

            report = f"### Found {len(results)} relevant code snippets for '{query}':\n\n"
            provenance = dict((results[0].get("retrieval_provenance") or {}))
            if provenance:
                graph_edges = provenance.get("graph_edge_types_used") or []
                report += f"**Retrieval policy:** `{provenance.get('policy', 'unknown')}`\n"
                report += f"**Mode:** `{provenance.get('mode', 'unknown')}`\n"
                report += (
                    f"**Graph reranking applied:** "
                    f"`{bool(provenance.get('graph_reranking_applied', False))}`\n"
                )
                report += (
                    f"**Structural edges used:** "
                    f"{', '.join(f'`{edge}`' for edge in graph_edges) if graph_edges else '`none`'}\n"
                )
                report += "**CALLS used for ranking:** `False`\n"
                for note in provenance.get("notes") or []:
                    report += f"**Note:** {note}\n"
                report += "\n"
            for r in results:
                report += f"#### 📄 {r['name']} (Score: {r['score']:.2f})\n"
                report += f"**Signature:** `{r['sig']}`\n"
                if r.get("path"):
                    report += f"**Path:** `{r['path']}`\n"
            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            logger.error(f"search failed:{e}")
            return f"Error executing search: {str(e)}"
    
    def get_file_dependencies(self, file_path: str, repo_id: str | None = None) -> str:
        """Summarize import edges for a single file.

        Calls :meth:`KnowledgeGraphBuilder.get_file_dependencies` and formats
        outgoing imports and incoming ``imported_by`` paths for the model.

        Args:
            file_path: Repository-relative path of the file to analyze.
            repo_id: Optional multi-repo scope.

        Returns:
            Markdown dependency report, or ``Error analyzing dependencies: ...``
            when Neo4j raises ``DatabaseError`` / ``ClientError``.
        """
        try:
            deps = self.graph.get_file_dependencies(
                file_path,
                repo_id=repo_id,
            )
            dep_list = deps.get("imports", [])
            caller_list = deps.get("imported_by", [])

            return (
                f"### Dependency Report for `{file_path}`\n"
                f"**Imports (outgoing):** {dep_list if dep_list else 'None'}\n"
                f"**Used By (incoming):** {caller_list if caller_list else 'None'}"
            )
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error analyzing dependencies: {str(e)}"

    def get_git_file_history(self, file_path: str, limit: int = 20) -> str:
        """List recent commits touching ``file_path`` using ingested git graph data.

        Args:
            file_path: Path as stored in the git graph.
            limit: Maximum commits to include.

        Returns:
            Markdown bullet list of short SHAs and subjects, a message when no
            git graph exists, ``No git history found...`` when the query is empty,
            or ``Error getting git file history: ...`` on Neo4j errors.
        """
        try:
            if not self.graph.has_git_graph_data():
                return "No git graph data found. Run git ingestion first."

            history = self.graph.get_git_file_history(file_path, limit=limit)
            if not history:
                return f"No git history found for `{file_path}`."

            report = f"### Git History for `{file_path}`\n"
            report += f"Found {len(history)} commit(s):\n"
            for row in history:
                sha = row.get("sha", "unknown")
                short_sha = sha[:12] if isinstance(sha, str) else "unknown"
                subject = row.get("message_subject", "(no subject)")
                report += f"- `{short_sha}` {subject}\n"
            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error getting git file history: {str(e)}"

    def get_commit_context(self, sha: str, include_diff_stats: bool = True) -> str:
        """Show metadata (and optional diff stats) for one commit SHA.

        Args:
            sha: Commit identifier as stored in the graph (prefixes are resolved
                by the graph layer).
            include_diff_stats: When ``True``, append file/addition/deletion counts.

        Returns:
            Markdown summary, guidance when git data is missing, ``No commit found``
            when unknown, or ``Error getting commit context: ...`` on Neo4j errors.
        """
        try:
            if not self.graph.has_git_graph_data():
                return "No git graph data found. Run git ingestion first."

            context: Optional[Dict[str, Any]] = self.graph.get_commit_context(
                sha, include_diff_stats=include_diff_stats
            )
            if not context:
                return f"No commit found for `{sha}`."

            report = f"### Commit `{context.get('sha', sha)}`\n"
            report += f"Subject: {context.get('message_subject', '(no subject)')}\n"
            report += f"Author: {context.get('author_name', 'unknown')}\n"
            report += f"Committed: {context.get('committed_at', 'unknown')}\n"

            if include_diff_stats:
                stats = context.get("stats", {})
                report += (
                    f"Files Changed: {stats.get('files_changed', 0)}, "
                    f"Additions: {stats.get('additions', 0)}, "
                    f"Deletions: {stats.get('deletions', 0)}\n"
                )

            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            return f"Error getting commit context: {str(e)}"


# ---------------------------------------------------------------------------
# Phase 4: Conversation MCP Tools
# ---------------------------------------------------------------------------


def register_conversation_tools(
    mcp: object,  # type: ignore[type-arg]
    *,
    annotation_resolver: ToolAnnotationResolver | None = None,
) -> None:
    """Attach conversation search, context, and ingestion tools to ``mcp``.

    Registers ``search_conversations``, ``get_conversation_context``, and
    ``add_message``. Each async handler resolves the cached pipeline then runs
    blocking Neo4j / embedding work in the default thread pool executor so the
    MCP server remains responsive.

    Args:
        mcp: FastMCP application instance (supports ``@mcp.tool``).
        annotation_resolver: Optional callback passed to
            :func:`_tool_registration_kwargs` to attach per-tool
            ``ToolAnnotations`` (used by the public MCP profile).

    Note:
        MCP-visible ``description`` strings are defined at registration sites
        below; Python docstrings document runtime behavior for maintainers.
    """

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "search_conversations",
            "Search past conversations for relevant exchanges. Use when you need to find "
            "prior context, check what was discussed about a topic, or retrieve conversation "
            "history by semantic similarity.",
            annotation_resolver,
        )
    )
    async def search_conversations(
        query: str,
        project_id: str | None = None,
        role: str | None = None,
        limit: int = 10,
        as_of: str | None = None,
    ) -> list[dict]:
        """Semantic search over conversation turn embeddings (vector index path).

        Unlike :func:`get_conversation_context`, this tool queries the
        ``chat_embeddings`` index directly inside the executor and does **not**
        run the temporal fusion path in :func:`search_conversation_turns_sync`.
        On any failure in the synchronous closure, logs and returns an empty
        list (no exception propagates to MCP).

        Args:
            query: Natural language search query.
            project_id: Optional project filter; ``None`` searches all projects.
            role: Optional role filter (``user`` / ``assistant``); ``None`` keeps
                all roles.
            limit: Maximum number of results to return (bounded by the Cypher
                ``LIMIT``).
            as_of: Optional ISO-8601 ceiling on ``ingested_at`` applied to rows
                after the query returns.

        Returns:
            List of turn dicts with vector ``score``, or ``[]`` on error.
        """
        pipeline = _get_mcp_conversation_pipeline()
        conn = pipeline._conn  # type: ignore[attr-defined]
        embedder = pipeline._embedder  # type: ignore[attr-defined]

        loop = asyncio.get_event_loop()

        def _run() -> list[dict]:
            try:
                query_embedding = embedder.embed(query)
                with conn.session() as session:
                    cypher = (
                        "CALL db.index.vector.queryNodes("
                        "  'chat_embeddings', $limit, $embedding"
                        ") YIELD node, score "
                        "WHERE ($project_id IS NULL OR node.project_id = $project_id)"
                        "  AND ($role IS NULL OR node.role = $role) "
                        "RETURN "
                        "    node.session_id     AS session_id, "
                        "    node.turn_index     AS turn_index, "
                        "    node.role           AS role, "
                        "    node.content        AS content, "
                        "    node.source_agent   AS source_agent, "
                        "    node.timestamp      AS timestamp, "
                        "    node.ingested_at    AS ingested_at, "
                        "    node.entities       AS entities, "
                        "    score "
                        "ORDER BY score DESC "
                        "LIMIT $limit"
                    )
                    result = session.run(
                        cypher,
                        embedding=query_embedding,
                        project_id=project_id,
                        role=role,
                        limit=limit,
                    )
                    rows = [dict(r) for r in result]
                    if as_of is not None:
                        rows = [
                            row
                            for row in rows
                            if (row.get("ingested_at") or "") <= as_of
                        ]
                    return rows
            except Exception as exc:
                logger.error("search_conversations failed: %s", exc)
                return []

        # Blocking embed + Neo4j session: keep off the asyncio event loop.
        return await loop.run_in_executor(None, _run)

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "get_conversation_context",
            "Retrieve the most relevant past conversation context for a given query or task. "
            "Returns a compact, structured bundle of prior exchanges ranked by relevance. "
            "Use this to ground responses in prior conversation history before answering a "
            "user's question.",
            annotation_resolver,
        )
    )
    async def get_conversation_context(
        query: str,
        project_id: str,
        limit: int = 5,
        include_session_context: bool = True,
        as_of: str | None = None,
    ) -> dict:
        """Retrieve structured conversation context for LLM grounding.

        Uses :func:`search_conversation_turns_sync`, so results may include
        **temporal graph reranking** when a bridge is available (contrast with
        :func:`search_conversations`). Optionally hydrates a ±1 **context
        window** per hit via :func:`_fetch_conversation_context_window`. On
        failure, logs and returns ``{"query": query, "turns": []}``.

        Args:
            query: Natural language query describing what context is needed.
            project_id: Required project scope (temporal path needs a project).
            limit: Number of primary turns to return (keep small for LLM windows).
            include_session_context: When ``True``, attach neighboring turns
                (respecting ``as_of``) for each match.
            as_of: Optional ingested-at ceiling forwarded to search and window
                hydration.

        Returns:
            Dict with ``query`` and ``turns`` (each turn may include
            ``context_window``).
        """
        pipeline = _get_mcp_conversation_pipeline()
        conn = pipeline._conn  # type: ignore[attr-defined]

        loop = asyncio.get_event_loop()

        def _run() -> dict:
            try:
                matched_turns = search_conversation_turns_sync(
                    pipeline,
                    query=query,
                    project_id=project_id,
                    role=None,
                    limit=limit,
                    as_of=as_of,
                    log_prefix="get_conversation_context",
                )
                turns_with_context = []
                for turn in matched_turns:
                    turn_data = dict(turn)
                    context_window: list[dict] = []

                    if include_session_context:
                        context_window = _fetch_conversation_context_window(
                            conn,
                            session_id=turn["session_id"],
                            turn_index=turn["turn_index"],
                            as_of=as_of,
                        )

                    turn_data["context_window"] = context_window
                    turns_with_context.append(turn_data)

                return {"query": query, "turns": turns_with_context}

            except Exception as exc:
                logger.error("get_conversation_context failed: %s", exc)
                return {"query": query, "turns": []}

        # search_conversation_turns_sync + Neo4j window reads are synchronous.
        return await loop.run_in_executor(None, _run)

    @mcp.tool(  # type: ignore[attr-defined]
        **_tool_registration_kwargs(
            "add_message",
            "Explicitly save a conversation turn to memory. Use this when you want to ensure "
            "a specific message is persisted, or when passive capture is not configured. "
            "Provide turn_index=0 for single messages; use sequential indexes for multi-turn writes.",
            annotation_resolver,
        )
    )
    async def add_message(
        role: str,
        content: str,
        session_id: str,
        project_id: str,
        turn_index: int = 0,
        source_agent: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        timestamp: str | None = None,
    ) -> dict:
        """Persist a single conversation turn to the memory graph.

        Builds a turn payload with fixed ``source_key="chat_mcp"`` and
        ``ingestion_mode="active"`` so downstream ingestion can distinguish
        explicit MCP writes from passive capture. Executes
        :meth:`ConversationIngestionPipeline.ingest` in a worker thread.

        Args:
            role: Turn role: ``user`` | ``assistant`` | ``system`` | ``tool``.
            content: Turn text content.
            session_id: Caller-owned session boundary identifier.
            project_id: Project this conversation belongs to.
            turn_index: 0-based position within the session (default ``0``).
            source_agent: AI that produced this turn (e.g. ``claude``).
            model: Specific model variant (e.g. ``claude-opus-4-6``).
            tool_name: For ``role="tool"``: the tool that was called.
            tool_call_id: Request/response pairing for tool turns.
            tokens_input: Input token count if known.
            tokens_output: Output token count if known.
            timestamp: ISO-8601 turn timestamp; ingestion fills timing if omitted.

        Returns:
            Ingestion summary dict (hashes, embedding/entity counts, ids) on
            success, or ``{"error": "<message>"}`` if ingestion raises.
        """
        pipeline = _get_mcp_conversation_pipeline()
        loop = asyncio.get_event_loop()

        turn = {
            "role": role,
            "content": content,
            "session_id": session_id,
            "project_id": project_id,
            "turn_index": turn_index,
            "source_agent": source_agent,
            "model": model,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "timestamp": timestamp,
            "ingestion_mode": "active",
            "source_key": "chat_mcp",
        }

        try:
            # Ingestion performs Neo4j writes and embedding work; keep it off the loop.
            result: dict = await loop.run_in_executor(None, pipeline.ingest, turn)
            return result
        except Exception as exc:
            logger.error("add_message failed: %s", exc)
            return {"error": str(exc)}


def register_schedule_tools(
    mcp: object,  # type: ignore[type-arg]
    connection_manager: ConnectionManager | None = None,
    groq_api_key: str | None = None,
    brave_api_key: str | None = None,
    pipeline: ResearchIngestionPipeline | None = None,
) -> None:
    """Register recurring web-research scheduling tools on the MCP instance.

    Registers three MCP tools: ``schedule_research``, ``run_research_session``,
    and ``list_research_schedules``.  These allow AI agents to create persistent
    research schedules backed by APScheduler and Neo4j, trigger ad hoc research
    sessions, and inspect what schedules are active.

    A lazy scheduler singleton is created on first tool invocation.  If the
    caller provides explicit ``connection_manager``, ``groq_api_key``,
    ``brave_api_key``, and ``pipeline``, those are used; otherwise the function
    falls back to ``_get_mcp_research_scheduler()`` which reads from environment
    variables.  If either the embedding service or Brave Search API key is
    unavailable, all three tools return an error string rather than raising.

    Call this once during MCP server startup, after the FastMCP instance is created.

    Args:
        mcp: The FastMCP instance to register tools on.
        connection_manager: Optional pre-built Neo4j ConnectionManager.
        groq_api_key: Optional Groq API key for the extraction LLM.
        brave_api_key: Optional Brave Search API key for web research.
        pipeline: Optional pre-built ResearchIngestionPipeline.

    Note:
        Tool ``description=`` strings are defined on decorators below; they are
        the MCP-facing summaries. Python docstrings describe return contracts
        and validation behavior.
    """

    scheduler_singleton: ResearchScheduler | None = None

    def _get_scheduler():
        """Lazily construct or return the shared :class:`ResearchScheduler`."""
        nonlocal scheduler_singleton
        if scheduler_singleton is not None:
            return scheduler_singleton

        if connection_manager and pipeline and groq_api_key and brave_api_key:
            extraction_llm = resolve_extraction_llm_config(api_key=groq_api_key)
            scheduler_singleton = ResearchScheduler(
                connection_manager=connection_manager,
                extraction_llm_api_key=extraction_llm.api_key,
                extraction_llm_model=extraction_llm.model,
                extraction_llm_provider=extraction_llm.provider,
                extraction_llm_base_url=extraction_llm.base_url,
                brave_api_key=brave_api_key,
                pipeline=pipeline,
            )
            return scheduler_singleton

        scheduler_singleton = _get_mcp_research_scheduler()
        return scheduler_singleton

    # Resolve scheduler once at import/registration time when possible so logs
    # appear early; tools call _get_scheduler() again idempotently.
    _get_scheduler()

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "Create a recurring research schedule backed by APScheduler and Neo4j. "
            "Use this when you want ongoing automated research for a project."
        )
    )
    async def schedule_research(
        template: str,
        variables: list[str],
        cron_expr: str,
        project_id: str,
        max_runs_per_day: int = 5,
    ) -> str:
        """Create and persist a recurring research schedule.

        Args:
            template: Prompt / URL pattern template for scheduled runs.
            variables: Template variable names or values as required by scheduler.
            cron_expr: Cron expression consumed by APScheduler.
            project_id: Owning project identifier in Neo4j.
            max_runs_per_day: Safety cap forwarded to the scheduler.

        Returns:
            JSON string ``{"status": "ok", "schedule_id": ...}`` on success, or
            ``{"status": "error", "error": "Research scheduler is not configured."}``
            when dependencies are missing.
        """
        scheduler = _get_scheduler()
        if scheduler is None:
            return json.dumps(
                {"status": "error", "error": "Research scheduler is not configured."}
            )

        loop = asyncio.get_event_loop()

        def _run() -> str:
            return scheduler.create_schedule(
                template=template,
                variables=variables,
                cron_expr=cron_expr,
                project_id=project_id,
                max_runs_per_day=max_runs_per_day,
            )

        schedule_id = await loop.run_in_executor(None, _run)
        return json.dumps({"status": "ok", "schedule_id": schedule_id})

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "Run a recurring research session now. Use an existing schedule_id or provide "
            "an ad hoc project/template/variables tuple."
        )
    )
    async def run_research_session(
        schedule_id: str | None = None,
        project_id: str | None = None,
        template: str | None = None,
        variables: list[str] | None = None,
    ) -> str:
        """Trigger one scheduled or ad hoc research session.

        Validates inputs before touching the scheduler: callers must supply either
        ``schedule_id`` **or** both ``project_id`` and ``template`` for ad hoc
        runs. Delegates to :meth:`ResearchScheduler.run_research_session` inside
        a worker thread.

        Args:
            schedule_id: Existing schedule to run, if any.
            project_id: Required for ad hoc runs together with ``template``.
            template: Ad hoc template when no ``schedule_id`` is provided.
            variables: Optional template variables for ad hoc execution.

        Returns:
            JSON-encoded dict from the scheduler (structure defined by
            ``ResearchScheduler``), or a JSON error object when validation fails
            or the scheduler is unavailable.
        """
        if not schedule_id and not (project_id and template):
            return json.dumps(
                {
                    "status": "error",
                    "error": "Provide schedule_id or (project_id + template).",
                }
            )

        scheduler = _get_scheduler()
        if scheduler is None:
            return json.dumps(
                {"status": "error", "error": "Research scheduler is not configured."}
            )

        loop = asyncio.get_event_loop()

        def _run() -> dict[str, Any]:
            return scheduler.run_research_session(
                schedule_id=schedule_id,
                ad_hoc_template=template,
                ad_hoc_variables=variables,
                project_id=project_id,
            )

        result = await loop.run_in_executor(None, _run)
        return json.dumps(result)

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "List the stored recurring research schedules for a project."
        )
    )
    async def list_research_schedules(project_id: str) -> str:
        """List recurring research schedules for a project.

        Args:
            project_id: Project key whose schedules are loaded from Neo4j.

        Returns:
            JSON ``{"status": "ok", "schedules": [...]}`` on success, or a JSON
            error payload when the scheduler is not configured.
        """
        scheduler = _get_scheduler()
        if scheduler is None:
            return json.dumps(
                {"status": "error", "error": "Research scheduler is not configured."}
            )

        loop = asyncio.get_event_loop()
        schedules = await loop.run_in_executor(None, scheduler.list_schedules, project_id)
        return json.dumps({"status": "ok", "schedules": schedules})
