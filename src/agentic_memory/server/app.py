"""
MCP server for Agentic Memory (FastMCP entrypoint and tool surface).

This module is the **runtime hub** for agent-facing capabilities: it constructs a
global :class:`mcp.server.fastmcp.FastMCP` instance, registers tool handlers with
``@mcp.tool()``, wraps them for rate limiting and telemetry, and starts the
server via :func:`run_server`.

**FastMCP / MCP wiring**
    ``mcp = FastMCP("Agentic Memory")`` owns the tool registry. Each public
    function decorated with ``@mcp.tool()`` becomes an MCP-exposed capability.
    Conversation and schedule tools are registered at **import time** through
    late imports at the bottom of this file — that defers loading
    ``agentic_memory.server.tools`` until ``mcp`` exists, which avoids circular
    import cycles.

**Decorator order (per tool)**
    ``@mcp.tool()`` is applied **first** (outermost), then ``@rate_limit``, then
    ``@log_tool_call`` (innermost, closest to the function body). That ordering
    ensures rate-limit rejections short-circuit before telemetry records a
    "failed" tool invocation.

**Search orchestration**
    * **Code / git / hybrid** — :func:`search_codebase` routes by ``domain`` and
      delegates code vector retrieval to :func:`agentic_memory.server.code_search.search_code`.
    * **Unified memory** — :func:`search_all_memory` calls
      :func:`agentic_memory.server.unified_search.search_all_memory_sync` and
      formats :class:`~agentic_memory.server.result_types.UnifiedSearchResponse`
      via :func:`_format_unified_search_results`.

**Result shaping**
    Private ``_format_*`` helpers turn dict rows or structured payloads into
    markdown-flavored strings sized for LLM context windows; :func:`validate_tool_output`
    enforces type and truncates overly long responses.

**Global state**
    ``graph``, ``telemetry_store``, and ``_repo_override`` are process-wide
    singletons initialized from environment, repo config, or :func:`run_server`
    arguments. :func:`atexit.register` ensures the Neo4j driver closes on exit.
"""

import os
import atexit
import logging
import time
import re
import json as json_module
from typing import Optional, Dict, Any, List
from functools import wraps
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP
import neo4j
from agentic_memory.core.extraction_llm import resolve_extraction_llm_config
from agentic_memory.core.request_context import get_request_id
from agentic_memory.core.retry import retry_transient
from agentic_memory.core.runtime_embedding import resolve_embedding_runtime
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder
from agentic_memory.server.code_search import (
    SAFE_RETRIEVAL_POLICY,
    normalize_retrieval_policy,
    search_code,
)
from agentic_memory.server.unified_search import search_all_memory_sync
from agentic_memory.temporal.seeds import (
    collect_seed_entities,
    extract_query_seed_entities,
    parse_as_of_to_micros,
)
from agentic_memory.telemetry import TelemetryStore, resolve_telemetry_db_path
from agentic_memory.trace.service import TraceExecutionService

logger = logging.getLogger(__name__)

# Single FastMCP application: tool names and schemas derive from decorated callables below.
mcp = FastMCP("Agentic Memory")

# Lazily populated by init_graph() / get_graph(); shared across all tool invocations.
graph: Optional[KnowledgeGraphBuilder] = None
_repo_override: Optional[Path] = None
telemetry_store: Optional[TelemetryStore] = None

# Simple in-process sliding-window limiter keyed by Python function name (tool name).
RATE_LIMIT_REQUESTS = 100  # Max requests per window
RATE_LIMIT_WINDOW = 60     # Window in seconds
_request_log: Dict[str, list] = {}
VALID_DOMAINS = {"code", "git", "hybrid"}
GIT_GRAPH_MISSING_MESSAGE = (
    "❌ Git graph data not found. Run git ingestion before using git-aware queries."
)
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")


def rate_limit(func):
    """Sliding-window rate limiter for MCP tool functions (in-process only).

    Tracks timestamps per wrapped function name in ``_request_log``. When the
    count within ``RATE_LIMIT_WINDOW`` seconds reaches ``RATE_LIMIT_REQUESTS``,
    returns a static error string instead of invoking the tool.

    Note:
        This is not distributed — one process, one counter. Sufficient for local
        agent loops; not a substitute for API gateway throttling.

    Args:
        func: Tool function to wrap.

    Returns:
        Wrapped function with the same call signature.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # One deque-like list per tool name; trimmed on each call.
        key = func.__name__
        now = datetime.now()
        
        # Initialize or clean old requests
        if key not in _request_log:
            _request_log[key] = []
        
        # Remove requests outside the window
        window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
        _request_log[key] = [t for t in _request_log[key] if t > window_start]
        
        # Check if rate limit exceeded
        if len(_request_log[key]) >= RATE_LIMIT_REQUESTS:
            logger.warning(f"Rate limit exceeded for {key}")
            return "❌ Rate limit exceeded. Please try again later."
        
        # Log this request
        _request_log[key].append(now)
        
        return func(*args, **kwargs)
    return wrapper


def log_tool_call(func):
    """Decorator that logs timing and records telemetry for every MCP tool call.

    Applied to all ``@mcp.tool`` handler functions in ``app.py``.  On each
    invocation the inner wrapper:
    1. Records the wall-clock start time.
    2. Calls the wrapped tool function.
    3. On success: logs duration and writes a success row to ``TelemetryStore``
       (if telemetry is enabled via ``CODEMEMORY_TELEMETRY_ENABLED``).
    4. On exception: logs the failure, writes a failure row with the exception
       class name as ``error_type``, then re-raises so the MCP framework can
       return an error response.

    Telemetry writes are best-effort — a failure to write to SQLite is logged as
    a warning but does not suppress the tool result.

    The ``rate_limit`` decorator should be applied *outside* this decorator so
    rate-limited rejections are not recorded as tool-call failures.

    Args:
        func: The MCP tool function to wrap.

    Returns:
        The wrapped function with identical signature.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        tool_name = func.__name__
        client_id = os.getenv("CODEMEMORY_CLIENT", "unknown")
        repo_root = str(_repo_override) if _repo_override else None
        
        logger.info(f"🔧 Tool called: {tool_name}")
        logger.debug(f"   Args: {args}, Kwargs: {kwargs}")
        
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            logger.info(f"✅ Tool {tool_name} completed in {duration:.2f}s")
            if telemetry_store:
                try:
                    telemetry_store.record_tool_call(
                        tool_name=tool_name,
                        duration_ms=duration * 1000.0,
                        success=True,
                        error_type=None,
                        client_id=client_id,
                        repo_root=repo_root,
                    )
                except Exception as telemetry_error:
                    logger.warning(f"⚠️ Telemetry write failed for {tool_name}: {telemetry_error}")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"❌ Tool {tool_name} failed after {duration:.2f}s: {e}")
            if telemetry_store:
                try:
                    telemetry_store.record_tool_call(
                        tool_name=tool_name,
                        duration_ms=duration * 1000.0,
                        success=False,
                        error_type=e.__class__.__name__,
                        client_id=client_id,
                        repo_root=repo_root,
                    )
                except Exception as telemetry_error:
                    logger.warning(f"⚠️ Telemetry write failed for {tool_name}: {telemetry_error}")
            raise
    return wrapper


def _is_telemetry_enabled() -> bool:
    """Return False when ``CODEMEMORY_TELEMETRY_ENABLED`` disables SQLite telemetry."""
    raw = os.getenv("CODEMEMORY_TELEMETRY_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _init_telemetry(repo_root: Optional[Path]) -> None:
    """Open (or skip) the :class:`~agentic_memory.telemetry.TelemetryStore` for tool metrics.

    Side effects:
        Sets module-level ``telemetry_store`` to a store instance or ``None``.
    """
    global telemetry_store
    if not _is_telemetry_enabled():
        telemetry_store = None
        logger.info("🧾 Telemetry disabled (CODEMEMORY_TELEMETRY_ENABLED=0).")
        return

    db_path = resolve_telemetry_db_path(repo_root)
    telemetry_store = TelemetryStore(db_path)
    logger.info(f"🧾 Telemetry writing to {db_path}")


def init_graph():
    """Build the global :class:`~agentic_memory.ingestion.graph.KnowledgeGraphBuilder`.

    Resolution order for repo root: ``_repo_override`` (from :func:`run_server`),
    ``CODEMEMORY_REPO``, then :func:`agentic_memory.config.find_repo_root`.
    Neo4j credentials come from per-repo ``Config`` when present, else env vars.

    Returns:
        The connected ``KnowledgeGraphBuilder`` instance assigned to ``graph``.

    Side effects:
        Assigns module-level ``graph`` and logs embedding key warnings when the
        code embedding runtime is not configured.
    """
    global graph

    # Prefer codememory config files when the repo is known — keeps teams on one source of truth.
    from agentic_memory.config import find_repo_root, Config

    repo_root_env = os.getenv("CODEMEMORY_REPO")
    if _repo_override:
        repo_root = _repo_override.resolve()
    elif repo_root_env:
        repo_root = Path(repo_root_env).expanduser().resolve()
    else:
        repo_root = find_repo_root()
    config = Config(repo_root) if repo_root else None

    if config and config.exists():
        # Use per-repo config
        neo4j_cfg = config.get_neo4j_config()
        uri = neo4j_cfg["uri"]
        user = neo4j_cfg["user"]
        password = neo4j_cfg["password"]
        logger.info(f"📂 Using config from: {config.config_file}")
    else:
        # Fall back to environment variables
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        logger.info("🔧 Using environment variables for configuration")

    runtime = resolve_embedding_runtime(
        "code",
        config=config if config and config.exists() else None,
        repo_root=repo_root,
    )
    if not runtime.api_key:
        logger.warning(
            "⚠️ Code embedding API key not set for provider '%s' - semantic code search will not work",
            runtime.provider,
        )

    graph = KnowledgeGraphBuilder(
        uri=uri,
        user=user,
        password=password,
        openai_key=None,
        config=config if config and config.exists() else None,
        repo_root=repo_root,
    )
    logger.info(f"✅ Connected to Neo4j at {uri}")
    return graph


def get_graph() -> Optional[KnowledgeGraphBuilder]:
    """Return ``graph``, calling :func:`init_graph` on first use.

    Returns:
        A live builder, or ``None`` if initialization raised (connection errors
        are logged; tools should surface a friendly message to the agent).
    """
    global graph
    if graph is not None:
        return graph

    try:
        return init_graph()
    except Exception as e:
        logger.error(f"❌ Failed to initialize graph connection: {e}")
        return None


def _close_graph_on_exit():
    """Best-effort Neo4j driver shutdown registered with :func:`atexit.register`."""
    if graph:
        graph.close()


# Register cleanup on exit
atexit.register(_close_graph_on_exit)


def validate_tool_output(output: str, max_length: int = 8000) -> str:
    """Ensure tool return values are non-empty strings and bounded in length.

    MCP transports and clients expect string tool content; this guards against
    accidental non-string returns and appends a truncation notice when over
    ``max_length``.

    Args:
        output: Raw tool result (expected ``str``).
        max_length: Maximum number of characters before truncation.

    Returns:
        The original string, a truncated string with suffix, or a fixed error
        message when ``output`` is missing or not a string.
    """
    if not output or not isinstance(output, str):
        return "❌ Tool returned invalid output"
    
    if len(output) > max_length:
        truncated = output[:max_length]
        truncated += f"\n\n... [Output truncated: {len(output) - max_length} chars omitted]"
        return truncated
    
    return output


def _normalize_domain(domain: str) -> Optional[str]:
    """Return a lowercase domain in ``VALID_DOMAINS``, or ``None`` if invalid."""
    if not isinstance(domain, str):
        return None
    normalized = domain.strip().lower()
    if normalized in VALID_DOMAINS:
        return normalized
    return None


def _validate_git_graph_data(current_graph: KnowledgeGraphBuilder) -> Optional[str]:
    """Return an error message when git ingestion has not populated the graph yet.

    Git-aware tools call this before querying so agents see an actionable hint
    instead of empty results or database errors.
    """
    has_git_data_fn = getattr(current_graph, "has_git_graph_data", None)
    if not callable(has_git_data_fn):
        return GIT_GRAPH_MISSING_MESSAGE

    try:
        if not has_git_data_fn():
            return GIT_GRAPH_MISSING_MESSAGE
    except Exception as e:
        logger.error(f"Git graph availability check failed: {e}")
        return f"❌ Failed to validate git graph data: {str(e)}"

    return None


def _format_code_results(results: List[Dict[str, Any]]) -> str:
    """Render code search rows (with optional ``retrieval_provenance``) for the LLM.

    When the first row includes provenance (policy, mode, graph rerank flags,
    edge types), a short preamble is emitted so agents can interpret scores in
    context — especially that ``CALLS`` is not used for ranking in current
    policies.
    """
    output = f"Found {len(results)} relevant code result(s):\n\n"
    provenance = dict((results[0].get("retrieval_provenance") or {})) if results else {}
    if provenance:
        graph_edges = provenance.get("graph_edge_types_used") or []
        output += "Retrieval provenance:\n"
        output += f"- Policy: `{provenance.get('policy', 'unknown')}`\n"
        output += f"- Mode: `{provenance.get('mode', 'unknown')}`\n"
        output += (
            f"- Graph reranking applied: "
            f"`{bool(provenance.get('graph_reranking_applied', False))}`\n"
        )
        output += (
            f"- Structural edges used: "
            f"{', '.join(f'`{edge}`' for edge in graph_edges) if graph_edges else '`none`'}\n"
        )
        output += f"- `CALLS` edges used for ranking: `False`\n"
        for note in provenance.get("notes") or []:
            output += f"- Note: {note}\n"
        output += "\n"

    for i, r in enumerate(results, 1):
        name = r.get("name", "Unknown")
        score = r.get("score", 0)
        text = r.get("text", "")[:300]
        sig = r.get("sig", "")
        path = r.get("path", "")
        labels = r.get("labels") or []

        output += f"{i}. **{name}**"
        if sig:
            output += f" (`{sig}`)"
        output += f" [Score: {score:.2f}]\n"
        if path:
            output += f"   Path: `{path}`\n"
        if labels:
            output += f"   Labels: {', '.join(f'`{label}`' for label in labels)}\n"
        if r.get("baseline_score") is not None and r.get("ppr_score") is not None:
            output += (
                f"   Rank components: baseline={float(r['baseline_score']):.2f}, "
                f"graph={float(r['ppr_score']):.2f}\n"
            )
        output += f"   ```\n{text}...\n   ```\n\n"

    return output.strip()


def _format_git_file_history(file_path: str, history: List[Dict[str, Any]]) -> str:
    """Format git file history records for LLM output."""
    output = f"## Git History for `{file_path}`\n\n"
    output += f"Found {len(history)} commit(s):\n\n"

    for i, entry in enumerate(history, 1):
        sha = entry.get("sha", "unknown")
        short_sha = sha[:12] if isinstance(sha, str) else "unknown"
        subject = entry.get("message_subject", "(no subject)")
        committed_at = entry.get("committed_at", "unknown")
        author = entry.get("author_name") or entry.get("author_email") or "unknown"
        change_type = entry.get("change_type", "unknown")
        additions = entry.get("additions", 0)
        deletions = entry.get("deletions", 0)

        output += f"{i}. `{short_sha}` {subject}\n"
        output += f"   - Author: {author}\n"
        output += f"   - Committed: {committed_at}\n"
        output += f"   - Change: {change_type} (+{additions}/-{deletions})\n\n"

    return output.strip()


def _format_commit_context_output(context: Dict[str, Any], include_diff_stats: bool) -> str:
    """Format detailed commit context for LLM output."""
    sha = context.get("sha", "unknown")
    subject = context.get("message_subject", "(no subject)")
    body = context.get("message_body", "")
    committed_at = context.get("committed_at", "unknown")
    authored_at = context.get("authored_at", "unknown")
    is_merge = context.get("is_merge", False)
    parent_shas = context.get("parent_shas", [])
    author_name = context.get("author_name") or "unknown"
    author_email = context.get("author_email") or "unknown"
    pull_requests = context.get("pull_requests", [])
    issues = context.get("issues", [])

    output = f"## Commit `{sha}`\n\n"
    output += f"**Subject:** {subject}\n"
    output += f"**Author:** {author_name} <{author_email}>\n"
    output += f"**Authored At:** {authored_at}\n"
    output += f"**Committed At:** {committed_at}\n"
    output += f"**Merge Commit:** {is_merge}\n"
    if parent_shas:
        output += f"**Parents:** {', '.join(parent_shas)}\n"
    output += "\n"

    if body:
        output += f"### Message Body\n{body}\n\n"

    if pull_requests:
        output += "### Linked Pull Requests\n"
        for pr in pull_requests:
            number = pr.get("number", "?")
            title = pr.get("title", "(untitled)")
            state = pr.get("state", "unknown")
            output += f"- #{number}: {title} ({state})\n"
        output += "\n"

    if issues:
        output += "### Referenced Issues\n"
        for issue in issues:
            number = issue.get("number", "?")
            title = issue.get("title", "(untitled)")
            state = issue.get("state", "unknown")
            output += f"- #{number}: {title} ({state})\n"
        output += "\n"

    if include_diff_stats:
        stats = context.get("stats", {})
        files = context.get("files", [])
        output += "### Diff Stats\n"
        output += f"**Files Changed:** {stats.get('files_changed', 0)}\n"
        output += f"**Additions:** {stats.get('additions', 0)}\n"
        output += f"**Deletions:** {stats.get('deletions', 0)}\n\n"

        if files:
            output += "### Changed Files\n"
            for file_info in files:
                path = file_info.get("path", "unknown")
                change_type = file_info.get("change_type", "unknown")
                additions = file_info.get("additions", 0)
                deletions = file_info.get("deletions", 0)
                output += f"- `{path}` ({change_type}, +{additions}/-{deletions})\n"
            output += "\n"

    return output.strip()


@mcp.tool()
@rate_limit
@log_tool_call
def search_codebase(
    query: str,
    limit: int = 5,
    domain: str = "code",
    repo_id: str | None = None,
    retrieval_policy: str = SAFE_RETRIEVAL_POLICY,
) -> str:
    """
    Semantically search the codebase for functionality.

    Uses vector similarity to find relevant code entities (functions, classes)
    based on natural language queries.

    Args:
        query: Natural language query (e.g. "Where is the auth logic?")
        limit: Maximum number of results to return (default: 5)
        domain: Search domain route: code, git, or hybrid (default: code)
        repo_id: Optional explicit repo scope for code and git lookups
        retrieval_policy: Code retrieval policy. ``safe`` is the agent-safe
            default; ``graph_reranked`` enables structural reranking without
            using ``CALLS`` edges.

    Returns:
        Formatted string with search results including scores and code snippets
    """
    domain_mode = _normalize_domain(domain)
    if not domain_mode:
        valid_domains = "|".join(sorted(VALID_DOMAINS))
        return f"❌ Invalid domain `{domain}`. Valid values: {valid_domains}"

    current_graph = get_graph()
    if not current_graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    normalized_query = query.strip()
    safe_limit = max(1, int(limit))
    resolved_repo_id = repo_id or current_graph.repo_id
    resolved_retrieval_policy = None
    if domain_mode in {"code", "hybrid"}:
        resolved_retrieval_policy = normalize_retrieval_policy(
            retrieval_policy,
            allow_auto=False,
        )
        if resolved_retrieval_policy is None:
            return (
                "❌ Invalid retrieval_policy "
                f"`{retrieval_policy}`. Valid values: safe|graph_reranked"
            )

    try:
        if domain_mode == "code":
            results = search_code(
                current_graph,
                query=normalized_query,
                limit=safe_limit,
                repo_id=repo_id,
                retrieval_policy=resolved_retrieval_policy or SAFE_RETRIEVAL_POLICY,
            )
            if not results:
                return "No relevant code found."
            return validate_tool_output(_format_code_results(results))

        git_graph_error = _validate_git_graph_data(current_graph)
        if git_graph_error:
            return git_graph_error

        if domain_mode == "git":
            if SHA_PATTERN.match(normalized_query):
                context = current_graph.get_commit_context(
                    normalized_query, include_diff_stats=False
                )
                if not context:
                    return f"No commit found for `{normalized_query}`."
                return validate_tool_output(
                    _format_commit_context_output(context, include_diff_stats=False)
                )

            if repo_id is None:
                history = current_graph.get_git_file_history(normalized_query, limit=safe_limit)
            else:
                history = current_graph.get_git_file_history(
                    normalized_query,
                    limit=safe_limit,
                    repo_id=resolved_repo_id,
                )
            if not history:
                return f"No relevant git history found for `{normalized_query}`."
            return validate_tool_output(_format_git_file_history(normalized_query, history))

        # hybrid: return both code results and git context (if query maps to file/sha)
        code_results = search_code(
            current_graph,
            query=normalized_query,
            limit=safe_limit,
            repo_id=repo_id,
            retrieval_policy=resolved_retrieval_policy or SAFE_RETRIEVAL_POLICY,
        )
        output = "## Hybrid Search Results\n\n"

        if code_results:
            output += "### Code Results\n"
            output += _format_code_results(code_results)
            output += "\n\n"
        else:
            output += "### Code Results\nNo relevant code found.\n\n"

        if SHA_PATTERN.match(normalized_query):
            context = current_graph.get_commit_context(normalized_query, include_diff_stats=False)
            if context:
                output += "### Git Commit Context\n"
                output += _format_commit_context_output(context, include_diff_stats=False)
            else:
                output += f"### Git Commit Context\nNo commit found for `{normalized_query}`."
        else:
            if repo_id is None:
                history = current_graph.get_git_file_history(normalized_query, limit=safe_limit)
            else:
                history = current_graph.get_git_file_history(
                    normalized_query,
                    limit=safe_limit,
                    repo_id=resolved_repo_id,
                )
            if history:
                output += "### Git File History\n"
                output += _format_git_file_history(normalized_query, history)
            else:
                output += f"### Git File History\nNo git history found for `{normalized_query}`."

        return validate_tool_output(output.strip())
    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
        logger.error(f"Search error: {e}")
        return f"❌ Search failed: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected search error: {e}")
        return f"❌ Search failed: {str(e)}"


@mcp.tool()
@rate_limit
@log_tool_call
def get_file_dependencies(file_path: str, repo_id: str | None = None) -> str:
    """
    Returns a list of files that this file IMPORTS and files that IMPORT this file.

    Useful for understanding:
    - What modules this file depends on
    - What would break if this file is modified
    - Upstream and downstream dependencies

    Args:
        file_path: Relative path to the file (e.g., "src/services/auth.py")

    Returns:
        Formatted string with import dependencies
    """
    current_graph = get_graph()
    if not current_graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    try:
        if repo_id is None:
            deps = current_graph.get_file_dependencies(file_path)
        else:
            deps = current_graph.get_file_dependencies(file_path, repo_id=repo_id)

        output = f"## Dependencies for `{file_path}`\n\n"

        if deps["imports"]:
            output += "### 📥 Imports (this file depends on):\n"
            for imp in deps["imports"]:
                output += f"- `{imp}`\n"
        else:
            output += "### 📥 Imports\nNo imports found.\n"

        output += "\n"

        if deps["imported_by"]:
            output += "### 📤 Imported By (files that depend on this):\n"
            for imp in deps["imported_by"]:
                output += f"- `{imp}`\n"
        else:
            output += "### 📤 Imported By\n files depend on this.\n"

        return validate_tool_output(output.strip())
    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
        logger.error(f"Dependencies error: {e}")
        return f"❌ Failed to get dependencies: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected dependencies error: {e}")
        return f"❌ Failed to get dependencies: {str(e)}"


@mcp.tool()
@rate_limit
@log_tool_call
def get_git_file_history(file_path: str, limit: int = 20) -> str:
    """
    Return commit history for a file from the git graph domain.

    Args:
        file_path: Relative repository file path
        limit: Maximum commits to return (default: 20)

    Returns:
        Formatted commit history for the file
    """
    current_graph = get_graph()
    if not current_graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    normalized_path = file_path.strip()
    if not normalized_path:
        return "❌ `file_path` is required."

    safe_limit = max(1, int(limit))

    try:
        git_graph_error = _validate_git_graph_data(current_graph)
        if git_graph_error:
            return git_graph_error

        history = current_graph.get_git_file_history(normalized_path, limit=safe_limit)
        if not history:
            return f"No git history found for `{normalized_path}`."
        return validate_tool_output(_format_git_file_history(normalized_path, history))
    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
        logger.error(f"Git file history error: {e}")
        return f"❌ Failed to get git file history: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected git file history error: {e}")
        return f"❌ Failed to get git file history: {str(e)}"


@mcp.tool()
@rate_limit
@log_tool_call
def get_commit_context(sha: str, include_diff_stats: bool = True) -> str:
    """
    Return detailed context for a commit SHA from the git graph domain.

    Args:
        sha: Full or short commit SHA
        include_diff_stats: Include changed files and line stats in response

    Returns:
        Formatted commit metadata and optional diff stats
    """
    current_graph = get_graph()
    if not current_graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    normalized_sha = sha.strip()
    if not normalized_sha:
        return "❌ `sha` is required."
    if not SHA_PATTERN.match(normalized_sha):
        return f"❌ Invalid commit SHA `{sha}`."

    try:
        git_graph_error = _validate_git_graph_data(current_graph)
        if git_graph_error:
            return git_graph_error

        context = current_graph.get_commit_context(
            normalized_sha, include_diff_stats=include_diff_stats
        )
        if not context:
            return f"No commit found for `{normalized_sha}`."

        return validate_tool_output(
            _format_commit_context_output(context, include_diff_stats=include_diff_stats)
        )
    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
        logger.error(f"Commit context error: {e}")
        return f"❌ Failed to get commit context: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected commit context error: {e}")
        return f"❌ Failed to get commit context: {str(e)}"


@mcp.tool()
@rate_limit
@log_tool_call
def identify_impact(file_path: str, max_depth: int = 3, repo_id: str | None = None) -> str:
    """
    Identify the blast radius of changes to a file.

    Returns all files that transitively depend on this file, organized by depth.
    Useful for understanding the impact of changes before making them.

    Args:
        file_path: Relative path to the file (e.g., "src/models/user.py")
        max_depth: Maximum depth to traverse (default: 3)

    Returns:
        Formatted string with affected files organized by depth
    """
    current_graph = get_graph()
    if not current_graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    try:
        if repo_id is None:
            result = current_graph.identify_impact(file_path, max_depth=max_depth)
        else:
            result = current_graph.identify_impact(
                file_path,
                max_depth=max_depth,
                repo_id=repo_id,
            )
        affected = result["affected_files"]
        total = result["total_count"]

        if total == 0:
            return f"## Impact Analysis for `{file_path}`\n\nNo files depend on this file. Changes are isolated."

        output = f"## Impact Analysis for `{file_path}`\n\n"
        output += f"**Total affected files:** {total}\n\n"

        # Group by depth
        by_depth: dict[int, list[str]] = {}
        for item in affected:
            depth = item["depth"]
            path = item["path"]
            if depth not in by_depth:
                by_depth[depth] = []
            by_depth[depth].append(path)

        # Output by depth level
        for depth in sorted(by_depth.keys()):
            files = by_depth[depth]
            depth_label = "direct" if depth == 1 else f"{depth}-hop transitive"
            output += f"### Depth {depth} ({depth_label} dependents): {len(files)} files\n"
            for path in files:
                output += f"- `{path}`\n"
            output += "\n"

        return validate_tool_output(output.strip())
    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
        logger.error(f"Impact analysis error: {e}")
        return f"❌ Failed to analyze impact: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected impact analysis error: {e}")
        return f"❌ Failed to analyze impact: {str(e)}"


@mcp.tool()
@rate_limit
@log_tool_call
def get_file_info(file_path: str, repo_id: str | None = None) -> str:
    """
    Get detailed information about a file including its entities and relationships.

    Returns:
    - Functions defined in the file
    - Classes defined in the file
    - Direct import relationships

    Args:
        file_path: Relative path to the file (e.g., "src/services/auth.py")

    Returns:
        Formatted string with file structure information
    """
    current_graph = get_graph()
    if not current_graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    resolved_repo_id = repo_id or current_graph.repo_id

    try:
        with current_graph.driver.session() as session:
            # Get file info
            result = session.run(
                """
                MATCH (f:File {repo_id: $repo_id, path: $path})
                OPTIONAL MATCH (f)-[:DEFINES]->(fn:Function {repo_id: $repo_id})
                OPTIONAL MATCH (f)-[:DEFINES]->(c:Class {repo_id: $repo_id})
                OPTIONAL MATCH (f)-[:IMPORTS]->(imp:File {repo_id: $repo_id})
                RETURN
                    f.name as name,
                    f.path as path,
                    f.last_updated as updated,
                    collect(DISTINCT fn.name) as functions,
                    collect(DISTINCT c.name) as classes,
                    collect(DISTINCT imp.path) as imports
            """,
                repo_id=resolved_repo_id,
                path=file_path.replace("\\", "/"),
            ).single()

            if not result:
                return f"❌ File `{file_path}` not found in the graph."

            name = result["name"]
            functions = result["functions"] or []
            classes = result["classes"] or []
            imports = result["imports"] or []
            updated = result["updated"]

            output = f"## File: `{name}`\n\n"
            output += f"**Path:** `{file_path}`\n"
            output += f"**Last Updated:** {updated}\n\n"

            if classes:
                output += f"### 📦 Classes ({len(classes)})\n"
                for cls in classes:
                    output += f"- `{cls}`\n"
                output += "\n"

            if functions:
                output += f"### ⚡ Functions ({len(functions)})\n"
                for fn in functions:
                    output += f"- `{fn}()`\n"
                output += "\n"

            if imports:
                output += f"### 📥 Imports ({len(imports)})\n"
                for imp in imports:
                    output += f"- `{imp}`\n"
                output += "\n"

            if not classes and not functions and not imports:
                output += "*No entities found. File may not be parsed yet.*\n"

            return validate_tool_output(output.strip())
    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ClientError) as e:
        logger.error(f"File info error: {e}")
        return f"❌ Failed to get file info: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected file info error: {e}")
        return f"❌ Failed to get file info: {str(e)}"


@mcp.tool()
@rate_limit
@log_tool_call
def trace_execution_path(
    start_symbol: str,
    max_depth: int = 2,
    force_refresh: bool = False,
    repo_id: str | None = None,
) -> str:
    """Trace one function's behavioral path on demand.

    This is the JIT replacement for mandatory repo-wide CALLS computation.
    Agents should use it when they need to understand what one function likely
    invokes, rather than relying on a global call graph built at index time.
    """
    current_graph = get_graph()
    if not current_graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    try:
        service = TraceExecutionService(graph=current_graph)
        result = service.trace_execution_path(
            start_symbol=start_symbol,
            repo_id=repo_id,
            max_depth=max_depth,
            force_refresh=force_refresh,
        )
        if result.get("status") != "resolved":
            output = "## Trace Execution\n\n"
            output += f"Start symbol: `{start_symbol}`\n"
            output += f"Status: `{result.get('status')}`\n"
            candidates = result.get("candidates") or []
            if candidates:
                output += "\n### Candidate Functions\n"
                for candidate in candidates:
                    output += (
                        f"- `{candidate.get('signature')}`"
                        f" ({candidate.get('path')}, {candidate.get('qualified_name')})\n"
                    )
            return validate_tool_output(output.strip())

        output = "## Trace Execution\n\n"
        output += f"Start symbol: `{start_symbol}`\n"
        output += f"Resolved root: `{result['root']['signature']}`\n"
        output += f"Max depth: {result.get('max_depth')}\n"
        output += f"Cache hits: {result.get('cache_hits', 0)}\n"
        output += f"Cache misses: {result.get('cache_misses', 0)}\n\n"

        for trace in result.get("traces") or []:
            output += (
                f"### Depth {trace.get('depth')} :: `{trace.get('root_signature')}` "
                f"{'[cache]' if trace.get('cache_hit') else '[fresh]'}\n"
            )
            edges = trace.get("edges") or []
            if edges:
                output += "Resolved Edges:\n"
                for edge in edges:
                    output += (
                        f"- `{edge.get('edge_type')}` -> `{edge.get('callee_signature')}` "
                        f"(confidence={float(edge.get('confidence') or 0.0):.2f})\n"
                    )
                    if edge.get("evidence"):
                        output += f"  Evidence: {edge['evidence']}\n"
            else:
                output += "Resolved Edges:\n- None\n"

            unresolved = trace.get("unresolved") or []
            if unresolved:
                output += "Unresolved:\n"
                for row in unresolved:
                    label = row.get("target_name") or "<unknown>"
                    reason = row.get("reason") or "unresolved"
                    output += f"- `{label}` :: {reason}\n"
            output += "\n"

        return validate_tool_output(output.strip())
    except Exception as e:
        logger.error(f"Trace execution error: {e}")
        return f"❌ Failed to trace execution path: {str(e)}"


# ---------------------------------------------------------------------------
# Research pipeline (lazy singleton)
# ---------------------------------------------------------------------------

_research_pipeline = None


def _get_research_pipeline():
    """Return a singleton :class:`~agentic_memory.web.pipeline.ResearchIngestionPipeline`.

    Returns:
        Pipeline instance, or ``None`` when embedding or LLM configuration is
        missing (tools must return a clear configuration error to the agent).
    """
    global _research_pipeline
    if _research_pipeline is not None:
        return _research_pipeline

    extraction_llm = resolve_extraction_llm_config()
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    if not extraction_llm.api_key:
        logger.error("Extraction LLM API key not set — research pipeline unavailable")
        return None

    from agentic_memory.core.connection import ConnectionManager
    from agentic_memory.core.entity_extraction import EntityExtractionService
    from agentic_memory.core.runtime_embedding import build_embedding_service
    from agentic_memory.temporal.bridge import get_temporal_bridge
    from agentic_memory.web.pipeline import ResearchIngestionPipeline

    try:
        embedder = build_embedding_service("web")
    except ValueError as exc:
        logger.error("Embedding runtime unavailable — %s", exc)
        return None

    conn = ConnectionManager(neo4j_uri, neo4j_user, neo4j_password)
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key,
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    _research_pipeline = ResearchIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )
    return _research_pipeline


# ---------------------------------------------------------------------------
# Web research MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
@rate_limit
@log_tool_call
def memory_ingest_research(
    type: str,
    content: str,
    project_id: str,
    session_id: str,
    source_agent: str,
    title: str = None,
    research_question: str = None,
    confidence: str = None,
    findings: list = None,
    citations: list = None,
) -> str:
    """
    ALWAYS call this tool when you complete any research task, analysis,
    or produce a substantive report. This saves your work to persistent
    memory so it's available in future sessions. Call this BEFORE
    presenting results to the user.

    Args:
        type: Content type — "report" for full reports, "finding" for atomic facts
        content: The text content to store
        project_id: Project identifier for entity anchoring
        session_id: Current agent session ID
        source_agent: AI that produced the content ("claude", "perplexity", etc.)
        title: Human-readable label (reports only)
        research_question: Original query that prompted this research
        confidence: Confidence level for findings ("high", "medium", "low")
        findings: List of finding dicts [{text, confidence, citations}] (reports only)
        citations: Top-level citations [{url, title, snippet}]

    Returns:
        JSON string with ingestion result summary
    """
    pipeline = _get_research_pipeline()
    if pipeline is None:
        return (
            "Error: Research pipeline not available. Check the configured embedding provider and "
            "the configured extraction LLM API key environment variables."
        )

    source_dict = {
        "type": type,
        "content": content,
        "project_id": project_id,
        "session_id": session_id,
        "source_agent": source_agent,
        "title": title,
        "research_question": research_question,
        "confidence": confidence,
        "findings": findings,
        "citations": citations,
        "ingestion_mode": "active",
    }

    try:
        result = pipeline.ingest(source_dict)
        return validate_tool_output(json_module.dumps({"status": "ok", **result}))
    except Exception as e:
        logger.error("Research ingestion failed: %s", e)
        return f"Error: Research ingestion failed: {str(e)}"


def _format_baseline_research_results(results: list[dict[str, Any]]) -> str:
    """Format vector-index research rows when temporal retrieval is skipped or empty."""
    output = f"Found {len(results)} relevant research result(s):\n\n"
    for i, row in enumerate(results, 1):
        text = (row.get("text") or "")[:300]
        score = row.get("score", 0)
        source_agent = row.get("source_agent", "unknown")
        labels = row.get("node_labels", [])
        node_type = "Finding" if "Finding" in labels else "Chunk" if "Chunk" in labels else "Research"
        question = row.get("research_question") or ""
        confidence = row.get("confidence") or ""

        output += f"{i}. [{node_type}] [Score: {score:.2f}] (by {source_agent})\n"
        if question:
            output += f"   Question: {question}\n"
        if confidence:
            output += f"   Confidence: {confidence}\n"
        output += f"   ```\n{text}...\n   ```\n\n"

    return output.strip()


def _format_unified_search_results(payload: dict[str, Any]) -> str:
    """Turn ``search_all_memory_sync().to_dict()`` into a readable MCP string.

    Args:
        payload: Must contain ``results`` (list of hit dicts) and optional
            ``errors`` (list of ``module`` / ``message`` dicts).

    Returns:
        Multi-line summary with scores, excerpts, and trailing warnings.
    """
    results = payload.get("results") or []
    errors = payload.get("errors") or []
    if not results:
        if errors:
            details = ", ".join(f"{err['module']}: {err['message']}" for err in errors)
            return f"No relevant memory found.\n\nWarnings: {details}"
        return "No relevant memory found."

    output = f"Found {len(results)} unified memory result(s):\n\n"
    for index, hit in enumerate(results, 1):
        module = hit.get("module", "unknown")
        title = hit.get("title") or hit.get("source_id") or "Untitled"
        score = float(hit.get("score", 0.0) or 0.0)
        source_kind = hit.get("source_kind", "unknown")
        temporal_tag = " temporal" if hit.get("temporal_applied") else ""
        excerpt = str(hit.get("excerpt") or "")[:300]
        output += (
            f"{index}. [{module}{temporal_tag}] {title} "
            f"[{source_kind}] [Score: {score:.2f}]\n"
        )
        if excerpt:
            output += f"   ```\n{excerpt}...\n   ```\n\n"
        else:
            output += "\n"

    if errors:
        output += "Warnings:\n"
        for error in errors:
            output += f"- {error['module']}: {error['message']}\n"

    return output.strip()


def _format_temporal_research_results(results: list[dict[str, Any]]) -> str:
    """Format temporal graph rows (subject/predicate/object + evidence) for MCP text."""
    output = f"Found {len(results)} relevant research result(s):\n\n"
    for i, row in enumerate(results, 1):
        subject = (row.get("subject") or {}).get("name", "unknown")
        predicate = row.get("predicate", "RELATED_TO")
        obj = (row.get("object") or {}).get("name", "unknown")
        confidence = float(row.get("confidence", 0.0) or 0.0)
        relevance = float(row.get("relevance", 0.0) or 0.0)
        evidence = (row.get("evidence") or [{}])[0]
        source_kind = evidence.get("sourceKind", "unknown")
        snippet = (evidence.get("rawExcerpt") or "")[:300]

        output += (
            f"{i}. [Temporal] [Score: {(confidence * relevance):.2f}] "
            f"[{source_kind}] {subject} -[{predicate}]-> {obj}\n"
        )
        if snippet:
            output += f"   ```\n{snippet}...\n   ```\n\n"
        else:
            output += "\n"

    return output.strip()


def _filter_rows_as_of(rows: list[dict[str, Any]], as_of: str | None) -> list[dict[str, Any]]:
    """Filter research rows by string compare on ``ingested_at`` (inclusive cutoff)."""
    if as_of is None:
        return rows
    return [row for row in rows if (row.get("ingested_at") or "") <= as_of]


def _dominant_project_id(rows: list[dict[str, Any]]) -> str | None:
    """Pick the ``project_id`` with the highest summed baseline score (temporal seeding)."""
    project_scores: dict[str, float] = {}
    for row in rows:
        project_id = row.get("project_id")
        if not project_id:
            continue
        project_scores[project_id] = project_scores.get(project_id, 0.0) + float(
            row.get("score", 1.0) or 1.0
        )
    if not project_scores:
        return None
    return max(project_scores.items(), key=lambda item: item[1])[0]


@mcp.tool()
@rate_limit
@log_tool_call
def search_web_memory(query: str, limit: int = 5, as_of: str | None = None) -> str:
    """
    Search web research memory for relevant reports, findings, and research content.

    Uses vector similarity to find semantically relevant research stored
    by memory_ingest_research. Returns chunks and findings with scores.

    Args:
        query: Natural language search query
        limit: Maximum number of results (default: 5)
        as_of: Optional ISO-8601 cutoff for temporal filtering

    Returns:
        Formatted string with search results including text, source, and scores
    """
    pipeline = _get_research_pipeline()
    if pipeline is None:
        return (
            "Error: Research pipeline not available. Check the configured embedding provider and "
            "the configured extraction LLM API key environment variables."
        )

    safe_limit = max(1, int(limit))

    try:
        embedding = pipeline._embedder.embed(query)
        with pipeline._conn.session() as session:
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
                limit=safe_limit,
                embedding=embedding,
            ).data()
        baseline_results = _filter_rows_as_of(baseline_results, as_of)

        if not baseline_results:
            return "No relevant research found."

        bridge = pipeline.__dict__.get("_temporal_bridge") if hasattr(pipeline, "__dict__") else None
        project_id = _dominant_project_id(baseline_results)
        if bridge is not None and bridge.is_available() and project_id is not None:
            seeds = collect_seed_entities(baseline_results, limit=5)
            if not seeds:
                try:
                    seeds = extract_query_seed_entities(query, pipeline._extractor)  # type: ignore[attr-defined]
                except Exception as exc:
                    logger.warning("search_web_memory query seed extraction failed: %s", exc)
                    seeds = []

            if seeds:
                try:
                    temporal_payload = retry_transient(
                        lambda: bridge.retrieve(
                            project_id=project_id,
                            seed_entities=seeds,
                            as_of_us=parse_as_of_to_micros(as_of),
                            max_edges=max(safe_limit * 2, safe_limit),
                        )
                    )
                    temporal_results = temporal_payload.get("results") or []
                    if temporal_results:
                        return validate_tool_output(
                            _format_temporal_research_results(temporal_results)
                        )
                    logger.info(
                        "web_search_fallback",
                        extra={
                            "event": "temporal_fallback",
                            "request_id": get_request_id(),
                                "memory_module": "web",
                            "provider": getattr(pipeline._embedder, "provider", None),
                            "fallback": "empty_temporal_result",
                            "error_type": None,
                        },
                    )
                except Exception as exc:
                    logger.warning(
                        "web_search_fallback",
                        extra={
                            "event": "temporal_fallback",
                            "request_id": get_request_id(),
                                "memory_module": "web",
                            "provider": getattr(pipeline._embedder, "provider", None),
                            "fallback": "temporal_retrieve_failed",
                            "error_type": type(exc).__name__,
                        },
                    )
            else:
                logger.info(
                    "web_search_fallback",
                    extra={
                        "event": "temporal_fallback",
                        "request_id": get_request_id(),
                            "memory_module": "web",
                        "provider": getattr(pipeline._embedder, "provider", None),
                        "fallback": "temporal_bridge_unavailable",
                        "error_type": None,
                    },
                )

        return validate_tool_output(_format_baseline_research_results(baseline_results))
    except Exception as e:
        logger.error("Research search failed: %s", e)
        return f"Error: Research search failed: {str(e)}"


@mcp.tool()
@rate_limit
@log_tool_call
def search_all_memory(
    query: str,
    limit: int = 10,
    project_id: str | None = None,
    repo_id: str | None = None,
    as_of: str | None = None,
    modules: str | None = None,
) -> str:
    """Search code, research, and conversation memory in one unified ranked response.

    Delegates merging and sorting to :func:`agentic_memory.server.unified_search.search_all_memory_sync`,
    then formats the structured payload for MCP text consumption. Missing
    optional pipelines (no graph, no research embedder, etc.) simply omit that
    slice of results rather than failing the entire call.

    Args:
        query: Natural-language query.
        limit: Max hits after global merge.
        project_id: Conversation scope; also used by temporal web path when relevant.
        repo_id: Optional code-graph repo scope.
        as_of: Optional temporal cutoff for research rows.
        modules: Comma-separated subset of ``code``, ``web``, ``conversation``.

    Returns:
        Formatted string from :func:`_format_unified_search_results`, passed
        through :func:`validate_tool_output`.
    """
    current_graph = get_graph()
    research_pipeline = _get_research_pipeline()
    requested_modules = None
    if modules:
        requested_modules = [part.strip() for part in modules.split(",") if part.strip()]

    # Structured merge in unified_search; string formatting stays in this MCP layer.
    payload = search_all_memory_sync(
        query=query,
        limit=limit,
        project_id=project_id,
        repo_id=repo_id,
        as_of=as_of,
        modules=requested_modules,
        graph=current_graph,
        research_pipeline=research_pipeline,
        conversation_pipeline=_get_mcp_conversation_pipeline(),
    ).to_dict()
    return validate_tool_output(_format_unified_search_results(payload))


@mcp.tool()
@rate_limit
@log_tool_call
def brave_search(query: str, count: int = 10) -> str:
    """
    Search the web for current information using Brave Search.

    Returns top results with title, URL, and description. Results are
    returned to you for analysis — they are NOT automatically ingested.
    Use memory_ingest_research to save findings you want to persist.

    Args:
        query: Search query string
        count: Number of results to return (default: 10, max: 20)

    Returns:
        Formatted string with search results
    """
    api_key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not api_key:
        return "Error: BRAVE_SEARCH_API_KEY environment variable not set."

    safe_count = max(1, min(int(count), 20))

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={
                    "X-Subscription-Token": api_key,
                    "Accept": "application/json",
                },
                params={"q": query, "count": safe_count},
            )
            resp.raise_for_status()
            data = resp.json()

        results = data.get("web", {}).get("results", [])
        if not results:
            return f"No web results found for '{query}'."

        output = f"Found {len(results)} web result(s) for '{query}':\n\n"
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            description = r.get("description", "")[:200]
            output += f"{i}. **{title}**\n"
            output += f"   URL: {url}\n"
            output += f"   {description}\n\n"

        return validate_tool_output(output.strip())
    except httpx.HTTPStatusError as e:
        logger.error("Brave Search HTTP error: %s", e)
        return f"Error: Brave Search returned {e.response.status_code}"
    except Exception as e:
        logger.error("Brave Search failed: %s", e)
        return f"Error: Brave Search failed: {str(e)}"


# ---------------------------------------------------------------------------
# Phase 4: Register conversation MCP tools
# ---------------------------------------------------------------------------
# Import here (not at module top) to avoid any circular-import risk.
# register_conversation_tools() decorates its inner functions with @mcp.tool()
# so registration happens at import time of app.py.
from agentic_memory.server.tools import (  # noqa: E402,PLC0415
    _get_mcp_conversation_pipeline,
    register_conversation_tools,
    register_schedule_tools,
)

register_conversation_tools(mcp)
register_schedule_tools(
    mcp,
    groq_api_key=resolve_extraction_llm_config().api_key,
    brave_api_key=os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY"),
)


def run_server(port: int, repo_root: Optional[Path] = None):
    """Start the FastMCP server (transport and binding depend on FastMCP defaults).

    Initializes optional repo override, telemetry, and attempts a graph connection
    before blocking in ``mcp.run()``. The ``port`` argument is accepted for CLI
    parity; consult FastMCP documentation for how the listening port is applied
    in your installed version.

    Args:
        port: Desired listen port (logged; passed through the stack as configured
            by the CLI entrypoint).
        repo_root: If set, overrides automatic repo discovery for config and
            telemetry file placement.

    Side effects:
        Sets ``_repo_override``, may open SQLite telemetry, may connect Neo4j,
        then runs until process exit.
    """
    global _repo_override
    _repo_override = repo_root.resolve() if repo_root else None
    logger.info(f"🚀 Starting Agentic Memory MCP server on port {port}")
    if _repo_override:
        logger.info(f"📂 Repository override set to {_repo_override}")
    _init_telemetry(_repo_override)
    if not get_graph():
        logger.warning("⚠️ Starting MCP server without active graph connection.")
    mcp.run()
