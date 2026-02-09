"""
MCP Server for Agentic Memory.

Exposes high-level skills to AI agents via the Model Context Protocol.
"""

import os
import atexit
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from codememory.ingestion.graph import KnowledgeGraphBuilder

logger = logging.getLogger(__name__)

# Initialize the MCP Server
mcp = FastMCP("Agentic Memory")

# Global Graph Connection (initialized when server starts)
graph: Optional[KnowledgeGraphBuilder] = None


def init_graph():
    """Initialize the global graph connection."""
    global graph

    # Try to load from local config first
    from codememory.config import find_repo_root, Config

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
        user = os.getenv("NEO4J_USER", "neo4j")
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


# Initialize on module load
init_graph()

# Register cleanup on exit
atexit.register(lambda: graph.close() if graph else None)


@mcp.tool()
def search_codebase(query: str, limit: int = 5) -> str:
    """
    Semantically search the codebase for functionality.

    Uses vector similarity to find relevant code entities (functions, classes)
    based on natural language queries.

    Args:
        query: Natural language query (e.g. "Where is the auth logic?")
        limit: Maximum number of results to return (default: 5)

    Returns:
        Formatted string with search results including scores and code snippets
    """
    if not graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    try:
        results = graph.semantic_search(query, limit=limit)
        if not results:
            return "No relevant code found."

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
    except Exception as e:
        logger.error(f"Search error: {e}")
        return f"❌ Search failed: {str(e)}"


@mcp.tool()
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
    if not graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    try:
        deps = graph.get_file_dependencies(file_path)

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

        return output.strip()
    except Exception as e:
        logger.error(f"Dependencies error: {e}")
        return f"❌ Failed to get dependencies: {str(e)}"


@mcp.tool()
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
    if not graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    try:
        result = graph.identify_impact(file_path, max_depth=max_depth)
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

        return output.strip()
    except Exception as e:
        logger.error(f"Impact analysis error: {e}")
        return f"❌ Failed to analyze impact: {str(e)}"


@mcp.tool()
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
    if not graph:
        return "❌ Graph not initialized. Check Neo4j connection."

    try:
        from neo4j import GraphDatabase

        with graph.driver.session() as session:
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

            return output.strip()
    except Exception as e:
        logger.error(f"File info error: {e}")
        return f"❌ Failed to get file info: {str(e)}"


def run_server(port: int):
    """
    Start the MCP server.

    Args:
        port: Port number to listen on
    """
    logger.info(f"🚀 Starting Agentic Memory MCP server on port {port}")
    mcp.run()
