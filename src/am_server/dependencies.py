"""FastAPI dependency callables for long-lived service singletons.

This module exposes **factory functions** meant for ``Depends(...)`` in route
handlers. Each cached getter returns a process-wide singleton so every request
shares one Neo4j connection manager, embedder, and pipeline graph — avoiding
per-request construction cost and keeping external state consistent.

Caching:
    ``functools.lru_cache(maxsize=1)`` memoizes the first successful build. Clear
    caches only in tests or process reload scenarios; in production the ASGI
    worker process lifetime matches the singleton lifetime.

FastAPI wiring:
    Pass the bare function reference, e.g. ``Depends(get_pipeline)``. FastAPI
    calls the dependency per request by default, but the underlying function
    returns the same cached instance after the first resolution.
"""

from __future__ import annotations

import os
from functools import lru_cache

from agentic_memory.chat.pipeline import ConversationIngestionPipeline
from agentic_memory.core.connection import ConnectionManager
from agentic_memory.core.entity_extraction import EntityExtractionService
from agentic_memory.core.extraction_llm import resolve_extraction_llm_config
from agentic_memory.product.state import ProductStateStore
from agentic_memory.core.runtime_embedding import build_embedding_service
from agentic_memory.temporal.bridge import get_temporal_bridge
from agentic_memory.web.pipeline import ResearchIngestionPipeline

from am_server.neo4j_routing import operator_neo4j_credentials, use_operator_neo4j


@lru_cache(maxsize=1)
def get_pipeline() -> ResearchIngestionPipeline:
    """Build or return the singleton web/research ingestion pipeline.

    Intended for ``Depends(get_pipeline)`` on routes that run the research
    ingestion path (embeddings profile ``"web"``).

    Returns:
        Shared :class:`~agentic_memory.web.pipeline.ResearchIngestionPipeline`
        instance for this process.

    Note:
        Reads ``NEO4J_URI``, ``NEO4J_USER``, ``NEO4J_PASSWORD`` and extraction LLM
        configuration from the environment on first call; subsequent calls hit
        the cache and do not re-read env.
    """
    conn = ConnectionManager(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=os.environ["NEO4J_PASSWORD"],
    )
    embedder = build_embedding_service("web")
    extraction_llm = resolve_extraction_llm_config()
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key or "",
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    return ResearchIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def get_conversation_pipeline() -> ConversationIngestionPipeline:
    """Build or return the singleton chat/conversation ingestion pipeline.

    Intended for ``Depends(get_conversation_pipeline)``. Uses a separate cache
    entry from :func:`get_pipeline` (embeddings profile ``"chat"`` vs ``"web"``).

    Returns:
        Shared
        :class:`~agentic_memory.chat.pipeline.ConversationIngestionPipeline`
        instance for this process.

    Note:
        Environment variable reads occur only on the first cache miss, same as
        :func:`get_pipeline`.
    """
    conn = ConnectionManager(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=os.environ["NEO4J_PASSWORD"],
    )
    embedder = build_embedding_service("chat")
    extraction_llm = resolve_extraction_llm_config()
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key or "",
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    return ConversationIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def get_operator_pipeline() -> ResearchIngestionPipeline:
    """Research pipeline bound to ``NEO4J_OPERATOR_URI`` (operator private graph).

    Only constructed when routing sends OpenClaw traffic for configured operator
    workspace ids. See :mod:`am_server.neo4j_routing`.
    """

    uri, user, password = operator_neo4j_credentials()
    conn = ConnectionManager(uri=uri, user=user, password=password)
    embedder = build_embedding_service("web")
    extraction_llm = resolve_extraction_llm_config()
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key or "",
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    return ResearchIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def get_operator_conversation_pipeline() -> ConversationIngestionPipeline:
    """Conversation pipeline bound to ``NEO4J_OPERATOR_URI``."""

    uri, user, password = operator_neo4j_credentials()
    conn = ConnectionManager(uri=uri, user=user, password=password)
    embedder = build_embedding_service("chat")
    extraction_llm = resolve_extraction_llm_config()
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key or "",
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    return ConversationIngestionPipeline(
        conn,
        embedder,
        extractor,
        temporal_bridge=get_temporal_bridge(),
    )


@lru_cache(maxsize=1)
def get_operator_graph():
    """Code-memory graph builder for the operator Neo4j (same Bolt as operator pipelines)."""

    from agentic_memory.ingestion.graph import KnowledgeGraphBuilder

    uri, user, password = operator_neo4j_credentials()
    return KnowledgeGraphBuilder(
        uri=uri,
        user=user,
        password=password,
        openai_key=None,
        config=None,
        repo_root=None,
    )


def pipelines_for_openclaw_workspace(
    workspace_id: str,
) -> tuple[ResearchIngestionPipeline, ConversationIngestionPipeline]:
    """Return research + conversation pipelines for one OpenClaw workspace."""

    if use_operator_neo4j(workspace_id):
        return get_operator_pipeline(), get_operator_conversation_pipeline()
    return get_pipeline(), get_conversation_pipeline()


def graph_for_openclaw_workspace(workspace_id: str):
    """Return the code graph handle for unified search (shared vs operator Neo4j)."""

    from agentic_memory.server.app import get_graph

    if use_operator_neo4j(workspace_id):
        return get_operator_graph()
    return get_graph()


@lru_cache(maxsize=1)
def get_product_store() -> ProductStateStore:
    """Build or return the shared on-disk product control-plane state store.

    Intended for ``Depends(get_product_store)`` so product/dashboard routes all
    observe the same :class:`~agentic_memory.product.state.ProductStateStore`.

    Returns:
        Cached :class:`~agentic_memory.product.state.ProductStateStore` for this
        process.
    """
    return ProductStateStore()
