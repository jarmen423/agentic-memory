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
from codememory.web.pipeline import ResearchIngestionPipeline
from codememory.ingestion.graph import KnowledgeGraphBuilder

logger = logging.getLogger(__name__)


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
    return ConversationIngestionPipeline(conn, embedder, extractor)


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
    return ResearchIngestionPipeline(conn, embedder, extractor)


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
        embedder = pipeline._embedder  # type: ignore[attr-defined]

        loop = asyncio.get_event_loop()

        def _run() -> dict:
            try:
                query_embedding = embedder.embed(query)

                with conn.session() as session:
                    # Primary vector search, filtered to project_id
                    cypher = (
                        "CALL db.index.vector.queryNodes("
                        "  'chat_embeddings', $limit, $embedding"
                        ") YIELD node, score "
                        "WHERE node.project_id = $project_id "
                        "RETURN "
                        "    node.session_id AS session_id, "
                        "    node.turn_index AS turn_index, "
                        "    node.role       AS role, "
                        "    node.content    AS content, "
                        "    node.ingested_at AS ingested_at, "
                        "    score "
                        "ORDER BY score DESC "
                        "LIMIT $limit"
                    )
                    result = session.run(
                        cypher,
                        embedding=query_embedding,
                        project_id=project_id,
                        limit=limit,
                    )
                    matched_turns = [dict(r) for r in result]
                    if as_of is not None:
                        matched_turns = [
                            turn
                            for turn in matched_turns
                            if (turn.get("ingested_at") or "") <= as_of
                        ]

                turns_with_context = []
                for turn in matched_turns:
                    turn_data = dict(turn)
                    context_window: list[dict] = []

                    if include_session_context:
                        sess_id = turn["session_id"]
                        t_idx = turn["turn_index"]
                        # +/-1 surrounding turns; use -1 as prev guard (never matches)
                        prev_idx = t_idx - 1
                        next_idx = t_idx + 1

                        with conn.session() as session:
                            # Fetch surrounding turns, exclude the matched turn itself
                            ctx_cypher = (
                                "MATCH (t:Memory:Conversation:Turn {session_id: $session_id}) "
                                "WHERE t.turn_index IN [$prev_index, $next_index] "
                                "  AND t.turn_index <> $matched_turn_index "
                                "RETURN "
                                "    t.turn_index AS turn_index, "
                                "    t.role       AS role, "
                                "    t.content    AS content, "
                                "    t.ingested_at AS ingested_at "
                                "ORDER BY t.turn_index"
                            )
                            ctx_result = session.run(
                                ctx_cypher,
                                session_id=sess_id,
                                prev_index=prev_idx,
                                next_index=next_idx,
                                matched_turn_index=t_idx,
                            )
                            context_window = [dict(r) for r in ctx_result]
                            if as_of is not None:
                                context_window = [
                                    row
                                    for row in context_window
                                    if (row.get("ingested_at") or "") <= as_of
                                ]

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
