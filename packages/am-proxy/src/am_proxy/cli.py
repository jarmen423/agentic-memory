"""CLI entry point for am-proxy.

Usage:
    am-proxy --agent claude --project my-project [agent-args...]
    am-proxy setup
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from am_proxy.agents import (
    detect_installed_agents,
    logical_agent_key,
    resolved_binary_for_agent,
)
from am_proxy.config import load_config
from am_proxy.proxy import ACPProxy


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the proxy run path (no subcommands).

    Child arguments are all tokens not consumed by this parser — including
    ``resume``, ``--``, and flags for the agent — so they are never mistaken
    for am-proxy subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="am-proxy",
        description="Transparent ACP stdio proxy with passive conversation ingestion.",
        add_help=True,
    )
    parser.add_argument(
        "--agent",
        metavar="NAME",
        help="Agent to proxy (e.g. claude, codex, gemini, opencode, kiro) or path to binary.",
    )
    parser.add_argument(
        "--project",
        metavar="ID",
        help="Project ID for memory ingestion. Overrides config default_project_id.",
    )
    parser.add_argument(
        "--endpoint",
        metavar="URL",
        help="am-server base URL (default from config: http://127.0.0.1:8765). Overrides config.",
    )
    parser.add_argument(
        "--api-key",
        metavar="KEY",
        help="Bearer token for am-server auth. Overrides config.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug logging to stderr.",
    )
    return parser


def _cmd_setup() -> None:
    """Detect installed agents and print editor configuration snippets."""
    detected = detect_installed_agents()
    if not detected:
        print("No supported agents found on PATH.")
        print("Supported agents: claude, codex, gemini, opencode, kiro")
        return
    for agent_name in detected:
        print(f"\n{agent_name.title()} detected.")
        print(f"Add to your editor's {agent_name} configuration:")
        print(f"  command: am-proxy --agent {agent_name} --project <your-project>")


def _default_codex_child_args(agent_args: list[str]) -> list[str]:
    """If agent is Codex and user passed no child argv, default to app-server (stdio)."""
    if agent_args:
        return agent_args
    return ["app-server"]


def _normalize_child_args(agent_args: list[str]) -> list[str]:
    """Strip an argv separator before forwarding args to the child process."""
    if agent_args and agent_args[0] == "--":
        return agent_args[1:]
    return agent_args


async def _run_proxy(
    spawn_binary: str,
    agent_args: list[str],
    project_id: str | None,
    endpoint: str | None,
    api_key: str | None,
    debug: bool,
) -> int:
    """Load config, spawn resolved binary, and run ACPProxy.

    Returns:
        Exit code from the agent subprocess.
    """
    config = load_config()
    if endpoint is not None:
        config.endpoint = endpoint
    if api_key is not None:
        config.api_key = api_key
    if debug:
        config.debug = True

    proxy = ACPProxy(
        binary=spawn_binary,
        args=agent_args,
        config=config,
        project_id=project_id,
    )
    return await proxy.run()


def main() -> None:
    """Entry point for am-proxy CLI.

    Sets Windows ProactorEventLoop policy before asyncio.run() on win32.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    argv = sys.argv[1:]
    if argv and argv[0] == "setup":
        _cmd_setup()
        return

    parser = _build_parser()
    args, remaining = parser.parse_known_args(argv)

    if not args.agent:
        parser.error("--agent NAME is required when not using 'setup'.")

    agent_key = logical_agent_key(args.agent)
    child_args = _normalize_child_args(list(remaining))
    if agent_key == "codex":
        child_args = _default_codex_child_args(child_args)

    spawn_binary = resolved_binary_for_agent(args.agent)

    exit_code = asyncio.run(
        _run_proxy(
            spawn_binary=spawn_binary,
            agent_args=child_args,
            project_id=args.project,
            endpoint=args.endpoint,
            api_key=getattr(args, "api_key", None),
            debug=args.debug,
        )
    )
    sys.exit(exit_code)
