"""Shared infrastructure for all memory modules.

Exports the complete public API of the codememory.core package.
Import from here instead of individual modules:

    from codememory.core import BaseIngestionPipeline, GraphWriter, ConnectionManager
"""

from codememory.core.registry import SOURCE_REGISTRY, register_source
from codememory.core.connection import ConnectionManager
from codememory.core.embedding import EmbeddingService
from codememory.core.entity_extraction import EntityExtractionService, build_embed_text
from codememory.core.base import BaseIngestionPipeline
from codememory.core.graph_writer import GraphWriter
from codememory.core.config_validator import validate_embedding_config

__all__ = [
    "SOURCE_REGISTRY",
    "register_source",
    "ConnectionManager",
    "EmbeddingService",
    "EntityExtractionService",
    "build_embed_text",
    "BaseIngestionPipeline",
    "GraphWriter",
    "validate_embedding_config",
]
