"""Runtime code tracing services for just-in-time behavioral exploration.

This package contains the on-demand tracing path that replaces mandatory
repo-wide CALLS computation during indexing. The tracer resolves one function at
runtime, gathers graph context, asks the configured extraction LLM to map likely
behavioral edges, and optionally caches the result as derived graph metadata.
"""

from agentic_memory.trace.service import TraceExecutionService

__all__ = ["TraceExecutionService"]
