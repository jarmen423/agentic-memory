"""Mutable registry: ingestion source_key → ordered Neo4j labels.

Pipelines call `register_source` at import time so `node_labels` can build label
strings like Memory:Code:Chunk without hard-coding tiers in each module.
This module is intentionally dependency-free (no other codememory imports).
"""

# Populated by ingestion modules via register_source; keys are stable identifiers (e.g. parser backend).
SOURCE_REGISTRY: dict[str, list[str]] = {}


def register_source(source_key: str, labels: list[str]) -> None:
    """Register an ingestion source's label tier.

    Args:
        source_key: Unique identifier for the ingestion source (e.g. "code_treesitter").
        labels: Ordered list of Neo4j node labels assigned to this source's nodes.
    """
    SOURCE_REGISTRY[source_key] = labels
