"""Structured types for unified cross-module memory search results.

``UnifiedMemoryHit`` is one row after normalizing code, web, or conversation
sources to a common shape. ``UnifiedSearchResponse`` bundles ranked hits plus
optional per-module error messages for callers that want both data and
diagnostics (MCP tools typically stringify this via ``to_dict()``).

See Also:
    ``codememory.server.unified_search.search_all_memory_sync`` for construction.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class UnifiedMemoryHit:
    """Single normalized hit from code, web, or conversation search.

    ``score`` is the value used for final ordering; ``baseline_score`` and
    ``temporal_score`` preserve provenance when temporal reranking runs on top
    of vector retrieval.

    Attributes:
        module: Source domain: ``code``, ``web``, or ``conversation``.
        source_kind: Fine-grained type (e.g. ``code_entity``, ``conversation_turn``).
        source_id: Stable identifier within the module (signature, hash, or
            ``session_id:turn_index``).
        title: Short label for display; may be None for some web rows.
        excerpt: Truncated text snippet for LLM or UI previews.
        score: Final ranking score (may combine baseline and temporal signals).
        baseline_score: Vector or primary retrieval score when not temporally
            reranked; None when ``temporal_applied`` is True for that path.
        temporal_score: Score from temporal bridge when applicable; otherwise None.
        temporal_applied: True if results came from temporal enrichment path.
        metadata: Module-specific fields (signatures, roles, project_id, etc.).
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
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this hit to a JSON-friendly dict (dataclass asdict).

        Returns:
            Plain dict mirroring field names and values.
        """
        return asdict(self)


@dataclass(slots=True)
class UnifiedSearchResponse:
    """Container for unified search results and optional module-level errors.

    Attributes:
        results: Ordered list of ``UnifiedMemoryHit`` after cross-module merge
            and sort (caller may truncate further).
        errors: List of ``{"module": str, "message": str}`` dicts for failures
            that did not stop the overall search.
    """

    results: list[UnifiedMemoryHit]
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize results and errors for JSON or MCP string formatting.

        Returns:
            Dict with ``results`` (list of per-hit dicts) and ``errors`` (list
            of error dicts).
        """
        return {
            "results": [hit.to_dict() for hit in self.results],
            "errors": list(self.errors),
        }
