"""FastMCP server subpackage for CodeMemory.

Hosts the Model Context Protocol (MCP) surface that agents use to query and
update the Neo4j-backed memory graph. Implementation is split between:

* ``codememory.server.app`` — FastMCP instance, graph lifecycle, code/git/research
  tools, rate limiting, and telemetry hooks.
* ``codememory.server.tools`` — Conversation MCP tools, research scheduler
  registration, and the ``Toolkit`` helper for graph-backed string formatting.

Agents never receive raw Cypher or Bolt access; tools enforce the supported
operations and response shapes.

Note:
    Import ``app`` for the running server (``mcp`` instance and ``run_server``)
    or ``tools`` for registration helpers and shared search utilities.

See Also:
    ``codememory.server.unified_search`` for cross-module ranked search used by
    ``search_all_memory``.
"""
