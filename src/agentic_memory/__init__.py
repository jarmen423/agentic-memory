"""Agentic Memory: structural code graph and MCP tooling for AI agents.

This package implements repository-local configuration, Neo4j-backed code
memory, ingestion pipelines, and an MCP server surface. Most operators
interact through the ``agentic-memory`` console script (see
``agentic_memory.cli``) or by importing subpackages such as
``agentic_memory.ingestion`` or ``agentic_memory.server`` from application
code.

The root namespace intentionally stays lightweight: submodules carry their
own docstrings and exports so import graphs stay clear for tooling and for
agents mapping the codebase.
"""
