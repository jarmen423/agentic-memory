"""Shared temporal-retrieval contract helpers for public and hosted surfaces.

This module exists because the project roadmap now treats time-aware retrieval
for research and conversation memory as a product contract, not a best-effort
enhancement. Public and hosted surfaces need one stable way to describe:

- which memory module failed the temporal requirement,
- why the temporal path could not run,
- how HTTP routes should serialize that failure, and
- how MCP/text surfaces should present an explicit error instead of a
  success-looking dense fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TemporalRetrievalRequiredError(RuntimeError):
    """Raised when a temporal-first retrieval surface cannot honor that contract.

    Attributes:
        module: The affected module, typically ``"web"``, ``"conversation"``,
            or ``"unified"``.
        reason: Stable machine-readable reason code.
        message: Human-readable explanation suitable for logs and error payloads.
        details: Structured debugging context safe to expose in API details.
    """

    module: str
    reason: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)

    def to_http_detail(self) -> dict[str, Any]:
        """Convert the exception into the shared am-server error-envelope shape."""

        return {
            "code": "temporal_retrieval_unavailable",
            "message": self.message,
            "details": {
                "module": self.module,
                "reason": self.reason,
                **self.details,
            },
        }


def temporal_error_string(error: TemporalRetrievalRequiredError) -> str:
    """Render a compact MCP-safe error string for temporal contract failures."""

    return (
        f"Error: {error.message} "
        f"(module={error.module}, reason={error.reason})"
    )
