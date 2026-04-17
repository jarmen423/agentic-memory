"""Shared infrastructure for all memory modules.

This package-level module re-exports the main building blocks used across the
repo, but it now treats the embedding stack as an optional dependency.

Why this matters:
    Some workflows, such as the VM-side healthcare chunk importer, never call
    :class:`EmbeddingService` because they operate entirely on precomputed
    vectors. Those workflows still import ``agentic_memory.core.connection``,
    which causes Python to load this package ``__init__`` first. If we eagerly
    import the embedding module here, optional provider dependencies such as
    ``google-genai`` become mandatory even for code paths that do not need
    them.

Result:
    Core infrastructure like :class:`ConnectionManager` remains importable on
    lean VM environments, while callers that actually need ``EmbeddingService``
    still get a clear import error when the optional dependencies are missing.
"""

from agentic_memory.core.base import BaseIngestionPipeline
from agentic_memory.core.config_validator import validate_embedding_config
from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.entity_extraction import EntityExtractionService, build_embed_text
from agentic_memory.core.graph_writer import GraphWriter
from agentic_memory.core.registry import SOURCE_REGISTRY, register_source

try:
    from agentic_memory.core.embedding import EmbeddingService
except ModuleNotFoundError as exc:
    _EMBEDDING_IMPORT_ERROR = exc

    class EmbeddingService:  # type: ignore[no-redef]
        """Lazy error placeholder when optional embedding deps are absent.

        The class keeps ``from agentic_memory.core import EmbeddingService``
        imports syntactically valid on hosts that do not install every provider
        SDK. Instantiating it raises the original import error with context.
        """

        def __init__(self, *args, **kwargs) -> None:
            raise ModuleNotFoundError(
                "EmbeddingService could not be imported because an optional "
                f"dependency is missing: {_EMBEDDING_IMPORT_ERROR}"
            ) from _EMBEDDING_IMPORT_ERROR

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
