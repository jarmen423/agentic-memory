"""Resolve agent executable paths for subprocess spawning (Windows-safe)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def resolve_spawn_binary(binary: str) -> str:
    """Return a path/name suitable for asyncio.create_subprocess_exec.

    On Windows, ``shutil.which("codex")`` may return ``codex.ps1``, which is not
    directly executable via CreateProcess. Prefer ``codex.cmd`` or ``codex.exe``
    in the same directory when present.

    Args:
        binary: Bare name (e.g. ``codex``) or full path to a launcher.

    Returns:
        Resolved executable string to pass as the subprocess argv[0].
    """
    if not binary:
        return binary

    # Explicit path: swap .ps1 for .cmd if sibling exists
    p = Path(binary)
    if p.suffix.lower() == ".ps1" and p.with_suffix(".cmd").is_file():
        return str(p.with_suffix(".cmd").resolve())
    if len(p.parts) > 1 or p.is_absolute():
        if p.is_file():
            return str(p.resolve())
        return binary

    found = shutil.which(binary)
    if not found:
        return binary

    found_path = Path(found)
    if sys.platform == "win32" and found_path.suffix.lower() == ".ps1":
        cmd = found_path.with_suffix(".cmd")
        if cmd.is_file():
            return str(cmd.resolve())
        exe = found_path.with_suffix(".exe")
        if exe.is_file():
            return str(exe.resolve())

    return found
