"""Source registry for Agentic Memory ingestion pipelines.

Maps source keys to Neo4j label tiers. This is a LEAF module — it imports
nothing from codememory. All other modules that need label resolution import
from here.
"""

SOURCE_REGISTRY: dict[str, list[str]] = {}


def register_source(source_key: str, labels: list[str]) -> None:
    """Register an ingestion source's label tier.

    Args:
        source_key: Unique identifier for the ingestion source (e.g. "code_treesitter").
        labels: Ordered list of Neo4j node labels assigned to this source's nodes.
    """
    SOURCE_REGISTRY[source_key] = labels
