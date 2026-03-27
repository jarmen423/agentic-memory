from typing import Any, Dict, List, Optional
import asyncio
import json
import logging
import os
from functools import lru_cache

import neo4j
from codememory.chat.pipeline import ConversationIngestionPipeline
from codememory.core.connection import ConnectionManager
from codememory.core.embedding import EmbeddingService
from codememory.core.entity_extraction import EntityExtractionService
from codememory.core.scheduler import ResearchScheduler
from codememory.temporal.bridge import get_temporal_bridge
from codememory.temporal.seeds import (
    collect_seed_entities,
    extract_query_seed_entities,
    parse_as_of_to_micros,
    parse_conversation_source_id,
)
from codememory.web.pipeline import ResearchIngestionPipeline
from codememory.ingestion.graph import KnowledgeGraphBuilder

logger = logging.getLogger(__name__)


def _filter_rows_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """Apply the Phase 7 ingested_at cutoff when provided."""
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
    """Baseline conversation vector search with seed metadata."""
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
    """Existing deterministic text fallback for conversation search."""
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
    """Hydrate one conversation turn by stable session/turn identity."""
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
    """Fetch the immediate surrounding turns for one matched turn."""
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
    """Resolve temporal evidence back to conversation turns."""
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
    """Temporal-first conversation search with deterministic fallback."""
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
        logger.warning("%s falling back to text search after vector failure: %s", log_prefix, exc)
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
        logger.info("%s falling back to baseline conversation search: temporal bridge unavailable", log_prefix)
        return filtered_baseline

    seeds = collect_seed_entities(filtered_baseline, limit=5)
    if not seeds:
        try:
            seeds = extract_query_seed_entities(query, extractor)
        except Exception as exc:
            logger.warning("%s query seed extraction failed: %s", log_prefix, exc)
            seeds = []

    if not seeds:
        logger.info("%s falling back to baseline conversation search: no temporal seeds", log_prefix)
        return filtered_baseline

    try:
        temporal_payload = bridge.retrieve(
            project_id=project_id,
            seed_entities=seeds,
            as_of_us=parse_as_of_to_micros(as_of),
            max_edges=max(limit * 2, limit),
        )
    except Exception as exc:
        logger.warning("%s falling back to baseline conversation search: %s", log_prefix, exc)
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

    logger.info("%s falling back to baseline conversation search: empty temporal result", log_prefix)
    return filtered_baseline


@lru_cache(maxsize=1)
def _get_mcp_conversation_pipeline() -> ConversationIngestionPipeline:
    """Cached ConversationIngestionPipeline for MCP tool layer.

    Reads from environment variables. Separate singleton from am-server's
    get_conversation_pipeline() — MCP server and am-server are distinct processes.
    """
    conn = ConnectionManager(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    embedder = EmbeddingService(provider="gemini", api_key=os.environ["GEMINI_API_KEY"])
    extractor = EntityExtractionService(api_key=os.environ["GROQ_API_KEY"])
    return ConversationIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def _get_mcp_research_pipeline() -> ResearchIngestionPipeline | None:
    """Cached ResearchIngestionPipeline for MCP tool registration."""
    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not google_api_key or not groq_api_key:
        logger.warning("Research MCP pipeline unavailable: missing Google/Groq API key.")
        return None

    conn = ConnectionManager(
        uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        user=os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j"),
        password=os.getenv("NEO4J_PASSWORD", "password"),
    )
    embedder = EmbeddingService(provider="gemini", api_key=google_api_key)
    extractor = EntityExtractionService(api_key=groq_api_key)
    return ResearchIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def _get_mcp_research_scheduler() -> ResearchScheduler | None:
    """Cached ResearchScheduler started alongside the MCP tool layer."""
    pipeline = _get_mcp_research_pipeline()
    groq_api_key = os.getenv("GROQ_API_KEY")
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
    if pipeline is None or not groq_api_key or not brave_api_key:
        logger.warning("Research scheduler unavailable: missing pipeline or API keys.")
        return None

    return ResearchScheduler(
        connection_manager=pipeline._conn,  # type: ignore[attr-defined]
        groq_api_key=groq_api_key,
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        brave_api_key=brave_api_key,
        pipeline=pipeline,
    )

class Toolkit:
    """
    The 'Brain' logic.
    Separated from the Server so it can be tested or used in CLI/Scripts directly.
    """
    def __init__(self, graph: KnowledgeGraphBuilder):
        self.graph = graph

    def semantic_search(self, query: str, limit: int = 5) -> str:
        """
        Performs hybrid search and formats the result as a readable string for the Agent.
        """
        try:
            results = self.graph.semantic_search(query, limit)
            if not results:
                return "No relevant code found in the graph."

            # Format for LLM consumption (Markdown)
            report = f"### Found {len(results)} relevant code snippets for '{query}':\n\n"
            for r in results:
                report += f"#### 📄 {r['name']} (Score: {r['score']:.2f})\n"
                report += f"**Signature:** `{r['sig']}`\n"
            return report
        except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
            logger.error(f"search failed:{e}")
            return f"Error executing search: {str(e)}"
    
    def get_file_dependencies(self, file_path: str) -> str:
        """
        Returns what this file imports and what calls it.
        """
        try:
            deps = self.graph.get_file_dependencies(file_path)
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
        """
        Return git commit history for a specific file.
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
        """
        Return metadata and optional diff stats for a commit.
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


def register_conversation_tools(mcp: object) -> None:  # type: ignore[type-arg]
    """Register Phase 4 conversation tools on the provided MCP instance.

    Call this from the MCP server startup (codememory/server/app.py) after
    the mcp instance is created.

    Args:
        mcp: The FastMCP instance to register tools on.
    """

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "Search past conversations for relevant exchanges. Use when you need to find "
            "prior context, check what was discussed about a topic, or retrieve conversation "
            "history by semantic similarity."
        )
    )
    async def search_conversations(
        query: str,
        project_id: str | None = None,
        role: str | None = None,
        limit: int = 10,
        as_of: str | None = None,
    ) -> list[dict]:
        """Semantic search over conversation turn embeddings.

        Args:
            query: Natural language search query.
            project_id: Optional project filter. Searches all projects if None.
            role: Optional role filter ("user" or "assistant"). All roles if None.
            limit: Maximum number of results to return (1-50).

        Returns:
            List of dicts: [{session_id, turn_index, role, content,
                source_agent, timestamp, ingested_at, entities, score}]
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

        return await loop.run_in_executor(None, _run)

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "Retrieve the most relevant past conversation context for a given query or task. "
            "Returns a compact, structured bundle of prior exchanges ranked by relevance. "
            "Use this to ground responses in prior conversation history before answering a "
            "user's question."
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

        Performs vector search over chat_embeddings filtered to project_id.
        If include_session_context=True, fetches the previous and next turn
        from the same session for each matched turn to provide conversational
        framing.

        Args:
            query: Natural language query describing what context is needed.
            project_id: Project scope (required — context is always project-scoped).
            limit: Number of turns to return (keep small for context window, 1-10).
            include_session_context: If True, fetch +/-1 surrounding turns per match.

        Returns:
            Dict: {query, turns: [{session_id, turn_index, role, content, score,
                context_window: [{turn_index, role, content}]}]}
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

        return await loop.run_in_executor(None, _run)

    @mcp.tool(  # type: ignore[attr-defined]
        description=(
            "Explicitly save a conversation turn to memory. Use this when you want to ensure "
            "a specific message is persisted, or when passive capture is not configured. "
            "Provide turn_index=0 for single messages; use sequential indexes for multi-turn writes."
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

        source_key is always 'chat_mcp' for this path (explicit agent write).
        ingestion_mode is always 'active'.

        Args:
            role: Turn role: "user" | "assistant" | "system" | "tool".
            content: Turn text content.
            session_id: Caller-owned session boundary identifier.
            project_id: Project this conversation belongs to.
            turn_index: 0-based position within the session (default 0).
            source_agent: AI that produced this turn (e.g. "claude").
            model: Specific model variant (e.g. "claude-opus-4-6").
            tool_name: For role="tool": the tool that was called.
            tool_call_id: For request/response pairing in tool turns.
            tokens_input: Input token count if known.
            tokens_output: Output token count if known.
            timestamp: ISO-8601 turn timestamp; uses ingested_at if not provided.

        Returns:
            Dict with ingestion result: {role, session_id, turn_index,
                content_hash, embedded, entities_count, project_id}.
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
    """Register recurring research scheduling tools on the provided MCP instance."""

    scheduler_singleton: ResearchScheduler | None = None

    def _get_scheduler():
        nonlocal scheduler_singleton
        if scheduler_singleton is not None:
            return scheduler_singleton

        if connection_manager and pipeline and groq_api_key and brave_api_key:
            scheduler_singleton = ResearchScheduler(
                connection_manager=connection_manager,
                groq_api_key=groq_api_key,
                groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                brave_api_key=brave_api_key,
                pipeline=pipeline,
            )
            return scheduler_singleton

        scheduler_singleton = _get_mcp_research_scheduler()
        return scheduler_singleton

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
        """Create and persist a recurring research schedule."""
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
        """Trigger one scheduled or ad hoc research session."""
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
        """List recurring research schedules for a project."""
        scheduler = _get_scheduler()
        if scheduler is None:
            return json.dumps(
                {"status": "error", "error": "Research scheduler is not configured."}
            )

        loop = asyncio.get_event_loop()
        schedules = await loop.run_in_executor(None, scheduler.list_schedules, project_id)
        return json.dumps({"status": "ok", "schedules": schedules})
