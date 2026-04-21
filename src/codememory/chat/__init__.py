"""Conversation memory: turn-by-turn chat ingestion into Neo4j.

Importing this package loads ``codememory.chat.pipeline``, which registers
conversation sources (``chat_mcp``, ``chat_proxy``, ``chat_ext``, ``chat_cli``,
and extensions) with the global source registry. The primary entry point is
``ConversationIngestionPipeline`` — one ``ingest()`` call per turn, with
session grouping and optional temporal shadow writes.
"""

from codememory.chat.pipeline import ConversationIngestionPipeline

__all__ = ["ConversationIngestionPipeline"]
