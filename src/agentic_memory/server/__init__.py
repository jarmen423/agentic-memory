"""
MCP server package for agentic_memory.

Exposes the Agentic Memory knowledge graph to AI agents via the Model Context
Protocol (MCP), enabling agents to query code structure, conversation history,
git history, and web research without direct database access.

Extended:
    The server package is split into two main modules:
    - ``app.py``: FastMCP server lifecycle, tool registration, rate limiting,
      telemetry decoration, and the ``run_server()`` entry point.
    - ``tools.py``: The public MCP tool API surface — conversation ingestion/search
      (Phase 4), research scheduling tools, and the ``Toolkit`` class for
      structural code queries (semantic search, dependency analysis, git history).

    All tools in this package are async and run blocking Neo4j/OpenAI calls in
    a thread executor to avoid blocking the MCP event loop.

Role:
    Consumed by the ``agentic-memory serve`` CLI command (via ``app.run_server``)
    and by the ``am-openclaw`` browser plugin MCP bridge.

Dependencies:
    - fastmcp (MCP server framework)
    - agentic_memory.ingestion.graph (KnowledgeGraphBuilder)
    - agentic_memory.chat.pipeline (ConversationIngestionPipeline)
    - agentic_memory.web.pipeline (ResearchIngestionPipeline)
    - agentic_memory.core.scheduler (ResearchScheduler)
    - agentic_memory.temporal (temporal graph bridge)
    - Neo4j (via ConnectionManager)

Key Technologies:
    Model Context Protocol (MCP), FastMCP, asyncio, Neo4j vector search.
"""
