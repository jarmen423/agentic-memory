"""
MCP server package for agentic_memory.

Exposes the Agentic Memory knowledge graph to AI agents via the Model Context
Protocol (MCP), enabling agents to query code structure, conversation history,
git history, and web research without direct database access.

Extended layout:
    The server surface is composed of several cooperating modules:

    - ``app.py``: FastMCP server lifecycle, ``@mcp.tool()`` registration, per-tool
      rate limiting, telemetry wrapping, lazy graph/research/conversation
      initialization, and the ``run_server()`` process entry point.
    - ``code_search.py``: Code-domain retrieval orchestration — baseline vector
      search on the code graph plus optional structural reranking (PPR) with
      explicit ``retrieval_provenance`` on every row.
    - ``unified_search.py``: Cross-module search orchestration used by
      ``search_all_memory`` — fans out to code, web (research), and conversation
      pipelines, then merges and sorts into one normalized response.
    - ``result_types.py``: Dataclasses (``UnifiedMemoryHit``,
      ``UnifiedSearchResponse``) shared by unified search and any HTTP/REST
      adapters that need the same JSON shape.
    - ``tools.py``: Additional MCP tools (conversation ingestion/search,
      scheduling) registered from ``app`` via late import to avoid circular
      dependencies.

    Tool handlers in ``app.py`` are synchronous; blocking Neo4j and embedding
    work still runs inside the MCP runtime's thread pool where the framework
    schedules it, keeping the event loop responsive at the decorator level.

Role:
    Consumed by the ``agent-memory serve`` CLI command (via ``app.run_server``)
    and by integrations (for example browser-side MCP bridges) that attach to the
    same tool surface.

Dependencies:
    - fastmcp / MCP SDK (server framework)
    - agentic_memory.ingestion.graph (KnowledgeGraphBuilder)
    - agentic_memory.chat.pipeline (ConversationIngestionPipeline)
    - agentic_memory.web.pipeline (ResearchIngestionPipeline)
    - agentic_memory.temporal (temporal graph bridge and seed helpers)
    - Neo4j (Bolt driver via ``KnowledgeGraphBuilder``)

Key technologies:
    Model Context Protocol (MCP), FastMCP, Neo4j vector indexes, optional
    graph-aware reranking for code retrieval.
"""
