"""Agent Conversation Memory module.

Exposes ConversationIngestionPipeline and triggers source registry
registration for all four chat ingest paths (chat_mcp, chat_proxy,
chat_ext, chat_cli).
"""

from codememory.chat.pipeline import ConversationIngestionPipeline

__all__ = ["ConversationIngestionPipeline"]
