"""Temporal (SpacetimeDB) bridge — retrieval and shadow ingestion helpers.

Re-exports the JSON-lines RPC client used to talk to the Node ``tsx`` helper
(``query_temporal.ts``), plus a cached factory. Pipelines such as
``ResearchIngestionPipeline`` and ``ConversationIngestionPipeline`` use this
layer for best-effort shadow writes when configured.

See Also:
    ``codememory.temporal.bridge.TemporalBridge``
    ``codememory.temporal.seeds`` for seed entity construction used with retrieve.
"""

from codememory.temporal.bridge import (
    TemporalBridge,
    TemporalBridgeError,
    TemporalBridgeUnavailableError,
    get_temporal_bridge,
)

__all__ = [
    "TemporalBridge",
    "TemporalBridgeError",
    "TemporalBridgeUnavailableError",
    "get_temporal_bridge",
]
