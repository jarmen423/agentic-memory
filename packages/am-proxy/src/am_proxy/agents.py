"""Agent name-to-binary mapping for am-proxy.

Defines known ACP-compatible agent CLIs with their executable names and
source_agent identifiers used in ConversationIngestRequest payloads.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from am_proxy.exec_resolve import resolve_spawn_binary


@dataclasses.dataclass
class AgentConfig:
    """Configuration for a known ACP-compatible agent CLI.

    Attributes:
        binary: Executable name on PATH (e.g. "claude").
        source_agent: Value for source_agent field in ConversationIngestRequest.
    """

    binary: str
    source_agent: str


# Hardcoded defaults for known ACP-compatible agents.
AGENT_CONFIGS: dict[str, AgentConfig] = {
    "claude": AgentConfig(binary="claude", source_agent="claude_code"),
    "codex": AgentConfig(binary="codex", source_agent="openai_codex"),
    "gemini": AgentConfig(binary="gemini", source_agent="google_gemini"),
    "opencode": AgentConfig(binary="opencode", source_agent="opencode"),
    "kiro": AgentConfig(binary="kiro", source_agent="aws_kiro"),
}


def logical_agent_key(name: str) -> str:
    """Map argv or path (e.g. ``codex.cmd``) to a known registry key when possible.

    Args:
        name: User ``--agent`` value (short name or path to binary).

    Returns:
        Lowercase registry key if basename matches a known agent, else ``name``.
    """
    stem = Path(name).stem.lower()
    if stem in AGENT_CONFIGS:
        return stem
    lowered = name.lower()
    if lowered in AGENT_CONFIGS:
        return lowered
    return name


def get_agent_config(name: str) -> AgentConfig:
    """Return AgentConfig for a given agent name (case-insensitive).

    If the agent name is not in AGENT_CONFIGS, treats the name itself as
    both the binary and source_agent — allowing unknown agents to be proxied
    without configuration.

    Paths to known launchers (e.g. ``.../codex.cmd``) are mapped via
    :func:`logical_agent_key` so ``source_agent`` matches the canonical id.

    Args:
        name: Agent name (e.g. "claude", "CLAUDE", "my-custom-agent").

    Returns:
        AgentConfig for the named agent, or a passthrough config for unknown names.
    """
    key = logical_agent_key(name)
    if key in AGENT_CONFIGS:
        return AGENT_CONFIGS[key]
    return AgentConfig(binary=name, source_agent=name)


def resolved_binary_for_agent(name: str) -> str:
    """Return the spawn argv0 for *name*, after Windows-safe resolution."""
    cfg = get_agent_config(name)
    return resolve_spawn_binary(cfg.binary)


def detect_installed_agents() -> list[str]:
    """Return names of known agents whose binary is found on PATH.

    Uses shutil.which to check each entry in AGENT_CONFIGS. Only returns
    agents whose binary is actually executable on the current system.

    Returns:
        List of agent name keys (e.g. ["claude", "codex"]) whose binaries
        are present on PATH.
    """
    present: list[str] = []
    for name, cfg in AGENT_CONFIGS.items():
        if shutil.which(cfg.binary) is None:
            continue
        resolved = resolve_spawn_binary(cfg.binary)
        if Path(resolved).is_file():
            present.append(name)
    return present
