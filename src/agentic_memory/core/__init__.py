"""Shared infrastructure for all memory modules.

Exports the complete public API of the codememory.core package.
Import from here instead of individual modules:

    from agentic_memory.core import BaseIngestionPipeline, GraphWriter, ConnectionManager
"""

from agentic_memory.core.registry import SOURCE_REGISTRY, register_source
from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.embedding import EmbeddingService
from agentic_memory.core.entity_extraction import EntityExtractionService, build_embed_text
from agentic_memory.core.base import BaseIngestionPipeline
from agentic_memory.core.graph_writer import GraphWriter
from agentic_memory.core.config_validator import validate_embedding_config

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
