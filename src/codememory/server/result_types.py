"""Shared result types for cross-module unified search."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class UnifiedMemoryHit:
    """Normalized cross-module search hit."""

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
        """Serialize to a plain dictionary."""
        return asdict(self)


@dataclass(slots=True)
class UnifiedSearchResponse:
    """Structured response for unified cross-module search."""

    results: list[UnifiedMemoryHit]
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full response to a plain dictionary."""
        return {
            "results": [hit.to_dict() for hit in self.results],
            "errors": list(self.errors),
        }
