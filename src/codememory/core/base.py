"""Abstract base for ingestion pipelines (code, web, chat, …).

Subclasses share `ConnectionManager` for Neo4j sessions and resolve per-source Neo4j
labels via `SOURCE_REGISTRY` through `node_labels`. Each domain implements `ingest`
to turn a source into graph updates.
"""

import abc
from typing import Any

from codememory.core.connection import ConnectionManager
from codememory.core.registry import SOURCE_REGISTRY


class BaseIngestionPipeline(abc.ABC):
    """Base class for all memory ingestion pipelines.

    Subclasses MUST declare:
        DOMAIN_LABEL: str  — "Code", "Research", or "Conversation"

    Subclasses MUST implement:
        ingest(source) — domain-specific ingestion logic
    """

    DOMAIN_LABEL: str  # Subclass MUST set this class variable

    def __init__(self, connection_manager: ConnectionManager) -> None:
        """Initialize the pipeline with a Neo4j connection manager.

        Args:
            connection_manager: Configured ConnectionManager instance.
        """
        self._conn = connection_manager

    @abc.abstractmethod
    def ingest(self, source: Any) -> dict[str, Any]:
        """Ingest a source document. Returns ingestion summary dict.

        Args:
            source: Domain-specific source object (file path, URL, message, etc.)

        Returns:
            Dict summarizing the ingestion result (nodes created, entities found, etc.)
        """

    def node_labels(self, source_key: str) -> list[str]:
        """Get node labels from source registry, with fallback.

        Resolves the label tier for the given source_key from SOURCE_REGISTRY.
        Falls back to ["Memory", DOMAIN_LABEL] if source_key is not registered.

        Args:
            source_key: Unique identifier for the ingestion source.

        Returns:
            List of Neo4j node labels for this source.
        """
        return SOURCE_REGISTRY.get(source_key, ["Memory", self.DOMAIN_LABEL])
