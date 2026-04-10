"""Config validator for Agentic Memory embedding configuration.

Catches embedding dimension mismatches between module config and the expected
vector index dimensions at startup, before any costly ingestion runs.
"""

import logging
from typing import Any

from agentic_memory.core.embedding import EmbeddingService

logger = logging.getLogger(__name__)

# Maps module name to its expected vector index dimensions.
# These match the Neo4j vector index definitions in ConnectionManager.setup_database().
LABEL_DIMENSION_MAP: dict[str, int] = {
    "code": 3072,   # OpenAI text-embedding-3-large — :Memory:Code vector index
    "web": 3072,    # Gemini gemini-embedding-2-preview default — :Memory:Research vector index
    "chat": 3072,   # Gemini gemini-embedding-2-preview default — :Memory:Conversation vector index
}

# Providers that support flexible output dimensionality (MRL / Matryoshka).
# For these providers, any configured dimension is accepted — we log a warning
# if it differs from the provider default so the caller is informed.
_MRL_PROVIDERS = frozenset({"gemini"})


def validate_embedding_config(config: dict[str, Any]) -> None:
    """Validate embedding provider/dimensions configuration against expected index dims.

    Raises ValueError for:
    - Unknown provider names (not in EmbeddingService.PROVIDERS)
    - OpenAI or Nemotron dimension mismatches (these providers use fixed dimensions)

    Allows (with a warning):
    - Gemini modules with non-default dimensions (Gemini MRL supports any output_dimensionality)

    No-ops:
    - Config without a "modules" key
    - Modules without an "embedding_dimensions" key

    Args:
        config: Full application config dict (may or may not contain "modules").

    Raises:
        ValueError: If an unknown provider is specified or a fixed-dimension
            provider is configured with mismatched dimensions.
    """
    if "modules" not in config:
        return

    modules = config["modules"]

    for module_name, module_cfg in modules.items():
        provider = module_cfg.get("embedding_provider", "")

        if not provider:
            continue

        # Validate provider is known
        if provider not in EmbeddingService.PROVIDERS:
            raise ValueError(
                f"Unknown embedding provider '{provider}' for module '{module_name}'. "
                f"Valid providers: {list(EmbeddingService.PROVIDERS.keys())}"
            )

        configured_dims = module_cfg.get("embedding_dimensions")
        if configured_dims is None:
            # No dimension configured — nothing to validate
            continue

        provider_default_dims: int = EmbeddingService.PROVIDERS[provider]["dimensions"]

        if provider in _MRL_PROVIDERS:
            # Gemini MRL supports output_dimensionality override — any value is valid.
            # Log a warning so callers know they're using dimension reduction.
            if configured_dims != provider_default_dims:
                logger.warning(
                    "Module '%s' uses Gemini MRL dimension reduction: %dd (provider default: %dd). "
                    "Ensure Neo4j vector index matches configured dimensions.",
                    module_name,
                    configured_dims,
                    provider_default_dims,
                )
        else:
            # OpenAI and Nemotron use fixed dimensions — any mismatch is a hard error.
            if configured_dims != provider_default_dims:
                raise ValueError(
                    f"Module '{module_name}' configured with {configured_dims}d but "
                    f"provider '{provider}' requires {provider_default_dims}d. "
                    f"Dimension mismatch will cause Neo4j vector index errors."
                )

    module_count = len(modules)
    logger.info("Embedding config validated for %d module(s)", module_count)
