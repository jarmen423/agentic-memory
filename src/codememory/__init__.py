"""
Top-level package for the codememory codebase-memory system.

Extended:
    codememory is an MCP (Model Context Protocol) server and ingestion pipeline
    that stores code, git history, conversations, and web research as a hybrid
    vector + graph database in Neo4j. Agents and IDE plugins talk to it via MCP
    tools; humans or CI pipelines feed it via CLI ingestion commands.

Role:
    This __init__.py is the Python package entry point. Because codememory is
    consumed as a library (imported by the MCP server and by CLI commands), this
    file intentionally stays minimal — all public API surfaces live in their
    respective submodules (server/, ingestion/, core/, etc.).

Dependencies:
    - Neo4j (graph + vector store)
    - OpenAI / configurable embedding providers
    - FastMCP (MCP server framework)
    - tree-sitter (AST-based code parsing)

Key Technologies:
    - Model Context Protocol (MCP) for agent-facing tool exposure
    - Neo4j vector indexes for semantic search
    - tree-sitter for language-agnostic AST parsing
"""
