"""Dependency injection: singleton pipeline factory functions."""

from __future__ import annotations

import os
from functools import lru_cache

from codememory.chat.pipeline import ConversationIngestionPipeline
from codememory.core.connection import ConnectionManager
from codememory.core.embedding import EmbeddingService
from codememory.core.entity_extraction import EntityExtractionService
from codememory.temporal.bridge import get_temporal_bridge
from codememory.web.pipeline import ResearchIngestionPipeline


@lru_cache(maxsize=1)
def get_pipeline() -> ResearchIngestionPipeline:
    """Return a cached ResearchIngestionPipeline instance.

    Reads Neo4j and API key env vars. Called at app startup and by routes.
    """
    conn = ConnectionManager(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=os.environ["NEO4J_PASSWORD"],
    )
    embedder = EmbeddingService(
        provider="gemini",
        api_key=os.environ["GEMINI_API_KEY"],
    )
    extractor = EntityExtractionService(api_key=os.environ["GROQ_API_KEY"])
    return ResearchIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def get_conversation_pipeline() -> ConversationIngestionPipeline:
    """Return a cached ConversationIngestionPipeline instance.

    Reads Neo4j and API key env vars. Independent singleton from get_pipeline().
    """
    conn = ConnectionManager(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=os.environ["NEO4J_PASSWORD"],
    )
    embedder = EmbeddingService(
        provider="gemini",
        api_key=os.environ["GEMINI_API_KEY"],
    )
    extractor = EntityExtractionService(api_key=os.environ["GROQ_API_KEY"])
    return ConversationIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )
