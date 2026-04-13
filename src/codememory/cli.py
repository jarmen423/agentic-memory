"""Backward-compatible CLI surface for the ``codememory`` package name.

Re-exports the public CLI API from ``agentic_memory.cli`` (including ``main``)
so imports like ``from codememory.cli import main`` keep working after the
canonical CLI moved under ``agentic_memory``.

Warning:
    The star import pulls in whatever ``agentic_memory.cli`` exports; new code
    should import from ``agentic_memory.cli`` explicitly for a stable surface.

See Also:
    ``agentic_memory.cli`` for command definitions, parsers, and entry logic.
"""

from agentic_memory.cli import *  # noqa: F401,F403
from agentic_memory.cli import main
