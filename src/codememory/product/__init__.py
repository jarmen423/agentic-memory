"""Compatibility re-export: product package under ``codememory.product``.

CodeMemory installs the canonical implementation under ``agentic_memory.product``.
This module preserves imports like ``from codememory.product import ...`` without
duplicating logic.

Note:
    Star-imports are intentional for backward compatibility; see
    ``agentic_memory.product`` for symbols and behavior.
"""

from agentic_memory.product import *  # noqa: F401,F403

