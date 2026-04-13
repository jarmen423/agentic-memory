"""Top-level package for CodeMemory (Agentic Memory).

CodeMemory is an MCP (Model Context Protocol) server and ingestion pipeline that
stores code, git history, conversations, and web research in Neo4j as a hybrid
vector + property graph. IDE plugins and agents call MCP tools; operators and CI
use CLI commands to ingest and maintain the graph.

This file is the package entry point. It stays minimal on purpose: concrete APIs
live in subpackages such as ``codememory.server``, ``codememory.ingestion``, and
``codememory.core`` rather than being re-exported here.

Note:
    Import submodules directly (e.g. ``from codememory.server import app``) when
    extending the product; there is no barrel export from this module.

See Also:
    ``codememory.cli`` / ``agentic_memory.cli`` for the command-line interface.
    ``codememory.server.app`` for the FastMCP server process.
"""
