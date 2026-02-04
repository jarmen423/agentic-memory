import os
import atexit
from mcp.server.fastmcp import FastMCP
from codememory.ingestion.graph import KnowledgeGraphBuilder

# Initialize the MCP Server
mcp = FastMCP("Agentic Memory")

# Global Graph Connection (Lazy Init recommended in prod)
graph = KnowledgeGraphBuilder(
    uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    user=os.getenv("NEO4J_USER", "neo4j"),
    password=os.getenv("NEO4J_PASSWORD", "password"),
    openai_key=os.getenv("OPENAI_API_KEY")
)

# Register cleanup on exit
atexit.register(graph.close)

@mcp.tool()
def search_codebase(query: str) -> str:
    """
    Semantically search the codebase for functionality.
    Args:
        query: Natural language query (e.g. "Where is the auth logic?")
    """
    results = graph.semantic_search(query)
    if not results:
        return "No relevant code found."
    
    output = "Found relevant code:\n"
    for r in results:
        output += f"- **{r['name']}** (Score: {r['score']:.2f}):\n  {r['text'][:200]}...\n"
    return output

@mcp.tool()
def get_file_dependencies(file_path: str) -> str:
    """
    Returns a list of files that this file IMPORTS.
    """
    # Logic to query [:IMPORTS] relationship
    # ...
    return f"Dependencies for {file_path}: [Not Implemented in MVP]"

def run_server(port: int):
    mcp.run()