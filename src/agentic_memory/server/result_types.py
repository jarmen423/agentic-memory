"""Shared result types for cross-module unified search.

``UnifiedMemoryHit`` and ``UnifiedSearchResponse`` are the canonical structured
output of :func:`agentic_memory.server.unified_search.search_all_memory_sync`.
MCP tools format these objects into human-readable strings for the LLM; HTTP
or other adapters can call :meth:`UnifiedSearchResponse.to_dict` directly.

Design note:
    Keeping a small dataclass layer here avoids duplicating field names and
    merge/sort logic between the unified search service and any future API
    surfaces.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class UnifiedMemoryHit:
    """One normalized hit from any unified-search submodule (code, web, chat).

    All modules are coerced into this shape so callers can sort and display
    results in one pass. The ``score`` field is the value used for final ranking;
    ``baseline_score`` and ``temporal_score`` preserve the underlying retrieval
    signals when a submodule applies temporal or hybrid scoring.

    Attributes:
        module: Logical source — typically ``code``, ``web``, or ``conversation``.
        source_kind: Finer-grained type within the module (for example
            ``code_entity``, ``research_chunk``, ``conversation_turn``).
        source_id: Stable-ish identifier for deduplication or deep linking
            (signature, content hash, or session/turn composite).
        title: Short human-facing label; may mirror research question or role.
        excerpt: Truncated text preview for MCP or JSON consumers.
        score: Final ranking score after any submodule-specific blending.
        baseline_score: Vector or primary retrieval score when applicable.
        temporal_score: Temporal graph contribution when temporal rerank ran.
        temporal_applied: Whether temporal retrieval influenced this hit.
        rerank_score: Learned rerank score when a second-stage reranker ran.
        retrieval_provenance: Structured explanation of filters, graph/temporal
            enrichment, reranker usage, and fallback behavior.
        metadata: Opaque per-module details (paths, labels, extra source data).
    """

    module: str
    source_kind: str
    source_id: str
    title: str | None
    excerpt: str
    score: float
    baseline_score: float | None = None
    temporal_score: float | None = None
    temporal_applied: bool = False
    rerank_score: float | None = None
    retrieval_provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable ``dict`` copy of this hit (shallow values)."""
        return asdict(self)


@dataclass(slots=True)
class UnifiedSearchResponse:
    """Full unified search payload: ranked hits plus non-fatal submodule errors.

    Individual modules (code, web, conversation) are best-effort: a failure in
    one submodule appends to ``errors`` while others may still return results.
    The MCP ``search_all_memory`` tool stringifies this structure for the model.

    Attributes:
        results: Hits sorted by ``UnifiedMemoryHit.score`` (and tie-breakers)
            in :func:`~agentic_memory.server.unified_search.search_all_memory_sync`.
        errors: List of ``{"module": str, "message": str}`` for partial failures.
    """

    results: list[UnifiedMemoryHit]
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize ``results`` and ``errors`` for REST or logging consumers."""
        return {
            "results": [hit.to_dict() for hit in self.results],
            "errors": list(self.errors),
        }
