"""Compatibility re-export: product state store under ``codememory.product.state``.

Delegates to ``agentic_memory.product.state`` so CLI and desktop shells can use
either namespace. No additional behavior is defined here.

Note:
    Star-imports mirror the legacy module surface area.
"""

from agentic_memory.product.state import *  # noqa: F401,F403
