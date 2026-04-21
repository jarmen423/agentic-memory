"""Public ingestion API for Agentic Memory.

This package wires repository indexing into the knowledge graph. Submodules
implement filesystem observation, Tree-sitter parsing, Neo4j writes, and
optional git-derived graph helpers.

Exports here point at git-history helpers used by higher-level tooling; the
primary code-graph pipeline lives in :mod:`agentic_memory.ingestion.graph` and
:mod:`agentic_memory.ingestion.watcher`.
"""

from agentic_memory.ingestion.git_graph import (
    GitGraphIngestor,
    parse_name_status_output,
    parse_numstat_output,
)

__all__ = [
    "GitGraphIngestor",
    "parse_name_status_output",
    "parse_numstat_output",
]
