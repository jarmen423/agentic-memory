"""Public, review-friendly FastMCP app that reuses internal tool implementations.

This module defines ``public_mcp``, a :class:`mcp.server.fastmcp.FastMCP` instance
intended for **plugin marketplaces, hosted bridges, or other external clients**
that should see a smaller, annotated tool surface than the full developer
server in ``agentic_memory.server.app``.

Integration pattern:
    Each tool function uses a **lazy import** of ``agentic_memory.server.app as
    internal_app`` inside the function body. That defers importing the heavy
    application module until a tool is invoked, which reduces the risk of import
    cycles during package initialization and matches how optional surfaces are
    loaded.

    The tool **names** and **annotations** are the public contract:
    ``@_public_tool("...")`` registers an explicit MCP name and attaches
    ``ToolAnnotations`` from :func:`am_server.mcp_profiles.public_tool_annotations`.
    The **behavior** is delegated to the matching handler on ``internal_app`` so
    there is a single implementation path for Neo4j, embeddings, and policies.

Conversation tools:
    :func:`agentic_memory.server.tools.register_conversation_tools` is called
    with ``annotation_resolver=public_tool_annotations`` so conversation search,
    context retrieval, and ``add_message`` share the same annotation policy as
    code-facing tools.

Error behavior:
    Return values are whatever the internal app returns (typically Markdown or
    JSON strings). Exceptions are handled inside ``internal_app`` handlers;
    this module does not add a second error layer.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from am_server.mcp_profiles import public_tool_annotations
from agentic_memory.server.tools import list_project_and_repo_ids, register_conversation_tools

public_mcp = FastMCP("Agentic Memory Public")


def _public_tool(name: str):
    """Decorate a function as a named public MCP tool with shared annotations.

    Wraps :meth:`FastMCP.tool` so each exported tool uses a **stable MCP name**
    (the ``name`` argument) independent of the Python function identifier, and
    receives frozen ``ToolAnnotations`` for safety/read-only hints to clients.

    Args:
        name: Public tool identifier exposed over MCP.

    Returns:
        A decorator that registers the wrapped callable on ``public_mcp``.
    """

    return public_mcp.tool(name=name, annotations=public_tool_annotations(name))


@_public_tool("search_codebase")
def search_codebase(
    query: str,
    limit: int = 5,
    domain: str = "code",
    repo_id: str | None = None,
    retrieval_policy: str = "safe",
) -> str:
    """Search indexed code for snippets and symbols relevant to ``query``.

    Delegates to ``internal_app.search_codebase`` (hybrid retrieval, domain and
    policy aware). See that handler for full semantics and error strings.

    Args:
        query: Natural-language or keyword code search string.
        limit: Maximum hits to return.
        domain: Search domain forwarded to the internal implementation.
        repo_id: Optional repository scope.
        retrieval_policy: Retrieval policy (e.g. ``safe``); forwarded unchanged.

    Returns:
        Formatted result string from the internal MCP implementation.
    """
    from agentic_memory.server import app as internal_app

    return internal_app.search_codebase(
        query=query,
        limit=limit,
        domain=domain,
        repo_id=repo_id,
        retrieval_policy=retrieval_policy,
    )


@_public_tool("get_file_dependencies")
def get_file_dependencies(file_path: str, repo_id: str | None = None) -> str:
    """Describe import relationships for ``file_path`` in the code graph.

    Args:
        file_path: Repository-relative path to analyze.
        repo_id: Optional repo scope for multi-repo graphs.

    Returns:
        Markdown or error text from ``internal_app.get_file_dependencies``.
    """
    from agentic_memory.server import app as internal_app

    return internal_app.get_file_dependencies(file_path=file_path, repo_id=repo_id)


@_public_tool("trace_execution_path")
def trace_execution_path(
    start_symbol: str,
    max_depth: int = 2,
    force_refresh: bool = False,
    repo_id: str | None = None,
) -> str:
    """Explore likely call/import neighborhoods around ``start_symbol``.

    Args:
        start_symbol: Seed symbol or identifier as accepted by the internal tool.
        max_depth: Graph traversal depth cap.
        force_refresh: When ``True``, bypass any cached path materialization.
        repo_id: Optional repository scope.

    Returns:
        Trace report string from ``internal_app.trace_execution_path``.
    """
    from agentic_memory.server import app as internal_app

    return internal_app.trace_execution_path(
        start_symbol=start_symbol,
        max_depth=max_depth,
        force_refresh=force_refresh,
        repo_id=repo_id,
    )


@_public_tool("search_all_memory")
def search_all_memory(
    query: str,
    limit: int = 10,
    project_id: str | None = None,
    repo_id: str | None = None,
    as_of: str | None = None,
    modules: str | None = None,
) -> str:
    """Run a unified search across code, research, and conversation memory.

    Args:
        query: User or agent query spanning multiple memory kinds.
        limit: Global or per-module limit depending on internal handler rules.
        project_id: Conversation / project-scoped memory selector.
        repo_id: Code graph repository scope.
        as_of: Optional temporal cutoff for time-bounded memory.
        modules: Optional comma-separated or structured module filter string.

    Returns:
        Combined result string from ``internal_app.search_all_memory``.
    """
    from agentic_memory.server import app as internal_app

    return internal_app.search_all_memory(
        query=query,
        limit=limit,
        project_id=project_id,
        repo_id=repo_id,
        as_of=as_of,
        modules=modules,
    )


@_public_tool("list_project_and_repo_ids")
def list_project_and_repo_ids_tool() -> dict:
    """List the currently known project ids and outward-facing repo ids."""

    return list_project_and_repo_ids()


@_public_tool("search_web_memory")
def search_web_memory(query: str, limit: int = 5, as_of: str | None = None) -> str:
    """Search ingested web research artifacts and summaries.

    Args:
        query: Research question or keywords.
        limit: Maximum number of web-memory hits.
        as_of: Optional ingested-at ceiling for historical queries.

    Returns:
        Result string from ``internal_app.search_web_memory``.
    """
    from agentic_memory.server import app as internal_app

    return internal_app.search_web_memory(query=query, limit=limit, as_of=as_of)


@_public_tool("memory_ingest_research")
def memory_ingest_research(
    type: str,
    content: str,
    project_id: str,
    session_id: str,
    source_agent: str,
    title: str | None = None,
    research_question: str | None = None,
    confidence: str | None = None,
    findings: list | None = None,
    citations: list | None = None,
) -> str:
    """Persist structured research content into the memory graph.

    The parameter ``type`` (Python name) carries the document or ingest kind
    expected by the internal pipeline; it shadows the builtin ``type`` name
    intentionally to match the MCP tool schema.

    Args:
        type: Research record type / category string.
        content: Main body text or serialized findings.
        project_id: Project namespace for the research record.
        session_id: Logical session or run identifier.
        source_agent: Agent or integration name for provenance.
        title: Optional display title.
        research_question: Optional originating question.
        confidence: Optional qualitative or encoded confidence label.
        findings: Optional structured finding list.
        citations: Optional citation list.

    Returns:
        Status or confirmation string from ``internal_app.memory_ingest_research``.
    """
    from agentic_memory.server import app as internal_app

    return internal_app.memory_ingest_research(
        type=type,
        content=content,
        project_id=project_id,
        session_id=session_id,
        source_agent=source_agent,
        title=title,
        research_question=research_question,
        confidence=confidence,
        findings=findings,
        citations=citations,
    )


# Conversation tools reuse tools.register_conversation_tools with the same
# annotation resolver so public clients get identical safety metadata.
register_conversation_tools(public_mcp, annotation_resolver=public_tool_annotations)
