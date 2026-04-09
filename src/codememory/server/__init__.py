"""
MCP server package for the codememory memory system.

Extended:
    This subpackage contains everything needed to run the MCP server that
    exposes memory tools to AI agents and IDE plugins. The server is built on
    FastMCP and registers tools for code search, conversation retrieval, web
    research scheduling, and telemetry-annotated tool tracing.

    The two primary entry points within this package are:
      - ``app.py``   — FastMCP server instance, tool registrations, and
                       graph/telemetry initialization logic.
      - ``tools.py`` — MCP tool implementations and the Toolkit helper class
                       that backs code-graph queries.

Role:
    Acts as the protocol boundary between the Neo4j-backed memory graph and
    AI agents. All agent-facing reads and writes flow through the tools defined
    here; direct Neo4j access is never exposed to agents.

Dependencies:
    - FastMCP (MCP server framework)
    - codememory.ingestion (graph and pipeline objects)
    - codememory.core (connection, embedding, entity extraction)
    - codememory.telemetry (SQLite tool-call telemetry)

Key Technologies:
    - Model Context Protocol (MCP)
    - Neo4j (graph + vector store)
    - APScheduler (recurring research schedules, via ResearchScheduler)
"""
