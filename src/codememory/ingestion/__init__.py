"""Public ingestion API for CodeMemory.

This package exposes git-history graph utilities used alongside the main
code-graph builder. Code-tree ingestion (Tree-sitter, Neo4j passes) lives in
sibling modules such as ``codememory.ingestion.graph`` and
``codememory.ingestion.watcher``; this ``__init__`` only re-exports the
git provenance helpers for convenient imports.

Exports:
    GitGraphIngestor: Sync local git history into ``Git*`` labels in Neo4j.
    parse_name_status_output: Parse ``git show --name-status`` lines.
    parse_numstat_output: Parse ``git show --numstat`` lines.
"""

from codememory.ingestion.git_graph import (
    GitGraphIngestor,
    parse_name_status_output,
    parse_numstat_output,
)

__all__ = [
    "GitGraphIngestor",
    "parse_name_status_output",
    "parse_numstat_output",
]
