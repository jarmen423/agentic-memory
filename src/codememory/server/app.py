"""
MCP Server for Agentic Memory.

Exposes high-level skills to AI agents via the Model Context Protocol.
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
from codememory.ingestion.graph import KnowledgeGraphBuilder
from codememory.telemetry import TelemetryStore, resolve_telemetry_db_path

logger = logging.getLogger(__name__)

# Initialize the MCP Server
mcp = FastMCP("Agentic Memory")

# Global Graph Connection (initialized when server starts)
graph: Optional[KnowledgeGraphBuilder] = None
_repo_override: Optional[Path] = None
telemetry_store: Optional[TelemetryStore] = None

# Rate limiting configuration
RATE_LIMIT_REQUESTS = 100  # Max requests per window
RATE_LIMIT_WINDOW = 60     # Window in seconds
_request_log: Dict[str, list] = {}
VALID_DOMAINS = {"code", "git", "hybrid"}
GIT_GRAPH_MISSING_MESSAGE = (
    "❌ Git graph data not found. Run git ingestion before using git-aware queries."
)
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")


def rate_limit(func):
    """Rate limiting decorator for MCP tools."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Use function name as key
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
    """Decorator to log tool calls for debugging."""
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
    raw = os.getenv("CODEMEMORY_TELEMETRY_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _init_telemetry(repo_root: Optional[Path]) -> None:
    global telemetry_store
    if not _is_telemetry_enabled():
        telemetry_store = None
        logger.info("🧾 Telemetry disabled (CODEMEMORY_TELEMETRY_ENABLED=0).")
        return

    db_path = resolve_telemetry_db_path(repo_root)
    telemetry_store = TelemetryStore(db_path)
    logger.info(f"🧾 Telemetry writing to {db_path}")


def init_graph():
    """Initialize the global graph connection."""
    global graph

    # Try to load from local config first
    from codememory.config import find_repo_root, Config

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
        openai_key = config.get_openai_key()
        logger.info(f"📂 Using config from: {config.config_file}")
    else:
        # Fall back to environment variables
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        openai_key = os.getenv("OPENAI_API_KEY")
        logger.info("🔧 Using environment variables for configuration")

    if not openai_key:
        logger.warning("⚠️ OPENAI_API_KEY not set - semantic search will not work")

    graph = KnowledgeGraphBuilder(
        uri=uri,
        user=user,
        password=password,
        openai_key=openai_key,
    )
    logger.info(f"✅ Connected to Neo4j at {uri}")
    return graph


def get_graph() -> Optional[KnowledgeGraphBuilder]:
    """Lazily initialize and return the graph connection."""
    global graph
    if graph is not None:
        return graph

    try:
        return init_graph()
    except Exception as e:
        logger.error(f"❌ Failed to initialize graph connection: {e}")
        return None


def _close_graph_on_exit():
    """Close graph connection on process exit if initialized."""
    if graph:
        graph.close()


# Register cleanup on exit
atexit.register(_close_graph_on_exit)


def validate_tool_output(output: str, max_length: int = 8000) -> str:
    """
    Validate and truncate tool output to ensure LLM-readable format.
    
    Args:
        output: The raw output string
        max_length: Maximum length for LLM consumption
        
    Returns:
        Validated and potentially truncated output
    """
    if not output or not isinstance(output, str):
        return "❌ Tool returned invalid output"
    
    if len(output) > max_length:
        truncated = output[:max_length]
        truncated += f"\n\n... [Output truncated: {len(output) - max_length} chars omitted]"
        return truncated
    
    return output


def _normalize_domain(domain: str) -> Optional[str]:
    """Normalize and validate search routing domain."""
    if not isinstance(domain, str):
        return None
    normalized = domain.strip().lower()
    if normalized in VALID_DOMAINS:
        return normalized
    return None


def _validate_git_graph_data(current_graph: KnowledgeGraphBuilder) -> Optional[str]:
    """Ensure git graph data is available before running git-domain tools."""
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
    """Format code semantic search results."""
    output = f"Found {len(results)} relevant code result(s):\n\n"
    for i, r in enumerate(results, 1):
        name = r.get("name", "Unknown")
        score = r.get("score", 0)
        text = r.get("text", "")[:300]
        sig = r.get("sig", "")

        output += f"{i}. **{name}**"
        if sig:
            output += f" (`{sig}`)"
        output += f" [Score: {score:.2f}]\n"
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
def search_codebase(query: str, limit: int = 5, domain: str = "code") -> str:
    """
    Semantically search the codebase for functionality.

    Uses vector similarity to find relevant code entities (functions, classes)
    based on natural language queries.

    Args:
        query: Natural language query (e.g. "Where is the auth logic?")
        limit: Maximum number of results to return (default: 5)
        domain: Search domain route: code, git, or hybrid (default: code)

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

    try:
        if domain_mode == "code":
            results = current_graph.semantic_search(normalized_query, limit=safe_limit)
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

            history = current_graph.get_git_file_history(normalized_query, limit=safe_limit)
            if not history:
                return f"No relevant git history found for `{normalized_query}`."
            return validate_tool_output(_format_git_file_history(normalized_query, history))

        # hybrid: return both code results and git context (if query maps to file/sha)
        code_results = current_graph.semantic_search(normalized_query, limit=safe_limit)
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
            history = current_graph.get_git_file_history(normalized_query, limit=safe_limit)
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
def get_file_dependencies(file_path: str) -> str:
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
        deps = current_graph.get_file_dependencies(file_path)

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
def identify_impact(file_path: str, max_depth: int = 3) -> str:
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
        result = current_graph.identify_impact(file_path, max_depth=max_depth)
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
def get_file_info(file_path: str) -> str:
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

    try:
        with current_graph.driver.session() as session:
            # Get file info
            result = session.run(
                """
                MATCH (f:File {path: $path})
                OPTIONAL MATCH (f)-[:DEFINES]->(fn:Function)
                OPTIONAL MATCH (f)-[:DEFINES]->(c:Class)
                OPTIONAL MATCH (f)-[:IMPORTS]->(imp:File)
                RETURN
                    f.name as name,
                    f.path as path,
                    f.last_updated as updated,
                    collect(DISTINCT fn.name) as functions,
                    collect(DISTINCT c.name) as classes,
                    collect(DISTINCT imp.path) as imports
            """,
                path=file_path,
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


# ---------------------------------------------------------------------------
# Research pipeline (lazy singleton)
# ---------------------------------------------------------------------------

_research_pipeline = None


def _get_research_pipeline():
    """Lazily initialize the research ingestion pipeline."""
    global _research_pipeline
    if _research_pipeline is not None:
        return _research_pipeline

    google_api_key = os.getenv("GOOGLE_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "password")

    if not google_api_key:
        logger.error("GOOGLE_API_KEY not set — research pipeline unavailable")
        return None
    if not groq_api_key:
        logger.error("GROQ_API_KEY not set — research pipeline unavailable")
        return None

    from codememory.core.connection import ConnectionManager
    from codememory.core.embedding import EmbeddingService
    from codememory.core.entity_extraction import EntityExtractionService
    from codememory.web.pipeline import ResearchIngestionPipeline

    conn = ConnectionManager(neo4j_uri, neo4j_user, neo4j_password)
    embedder = EmbeddingService(provider="gemini", api_key=google_api_key)
    extractor = EntityExtractionService(api_key=groq_api_key)
    _research_pipeline = ResearchIngestionPipeline(conn, embedder, extractor)
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
        return "Error: Research pipeline not available. Check GOOGLE_API_KEY and GROQ_API_KEY environment variables."

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


@mcp.tool()
@rate_limit
@log_tool_call
def search_web_memory(query: str, limit: int = 5) -> str:
    """
    Search web research memory for relevant reports, findings, and research content.

    Uses vector similarity to find semantically relevant research stored
    by memory_ingest_research. Returns chunks and findings with scores.

    Args:
        query: Natural language search query
        limit: Maximum number of results (default: 5)

    Returns:
        Formatted string with search results including text, source, and scores
    """
    pipeline = _get_research_pipeline()
    if pipeline is None:
        return "Error: Research pipeline not available. Check GOOGLE_API_KEY and GROQ_API_KEY environment variables."

    try:
        embedding = pipeline._embedder.embed(query)
    except Exception as e:
        logger.error("Embedding failed for search query: %s", e)
        return f"Error: Failed to embed search query: {str(e)}"

    safe_limit = max(1, int(limit))

    search_cypher = """
    CALL db.index.vector.queryNodes('research_embeddings', $limit, $embedding)
    YIELD node, score
    RETURN
        node.text AS text,
        node.source_agent AS source_agent,
        node.research_question AS research_question,
        node.confidence AS confidence,
        node.source_key AS source_key,
        node.project_id AS project_id,
        labels(node) AS node_labels,
        score
    ORDER BY score DESC
    """

    try:
        with pipeline._conn.session() as session:
            results = session.run(
                search_cypher,
                limit=safe_limit,
                embedding=embedding,
            ).data()

        if not results:
            return "No relevant research found."

        output = f"Found {len(results)} relevant research result(s):\n\n"
        for i, r in enumerate(results, 1):
            text = (r.get("text") or "")[:300]
            score = r.get("score", 0)
            source_agent = r.get("source_agent", "unknown")
            labels = r.get("node_labels", [])
            node_type = "Finding" if "Finding" in labels else "Chunk" if "Chunk" in labels else "Research"
            question = r.get("research_question") or ""
            confidence = r.get("confidence") or ""

            output += f"{i}. [{node_type}] [Score: {score:.2f}] (by {source_agent})\n"
            if question:
                output += f"   Question: {question}\n"
            if confidence:
                output += f"   Confidence: {confidence}\n"
            output += f"   ```\n{text}...\n   ```\n\n"

        return validate_tool_output(output.strip())
    except Exception as e:
        logger.error("Research search failed: %s", e)
        return f"Error: Research search failed: {str(e)}"


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


def run_server(port: int, repo_root: Optional[Path] = None):
    """
    Start the MCP server.

    Args:
        port: Port number to listen on
        repo_root: Optional explicit repository root for config resolution
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
