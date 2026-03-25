"""CLI entry point for am-proxy.

Usage:
    am-proxy --agent claude --project my-project [agent-args...]
    am-proxy setup
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from am_proxy.agents import detect_installed_agents, get_agent_config
from am_proxy.config import load_config
from am_proxy.proxy import ACPProxy


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for am-proxy."""
    parser = argparse.ArgumentParser(
        prog="am-proxy",
        description="Transparent ACP stdio proxy with passive conversation ingestion.",
        add_help=True,
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # setup subcommand
    subparsers.add_parser(
        "setup",
        help="Detect installed agents and print editor configuration snippets.",
    )

    # run arguments (default when no subcommand given)
    parser.add_argument(
        "--agent",
        metavar="NAME",
        help="Agent to proxy (e.g. claude, codex, gemini, opencode, kiro).",
    )
    parser.add_argument(
        "--project",
        metavar="ID",
        help="Project ID for memory ingestion. Overrides config default_project_id.",
    )
    parser.add_argument(
        "--endpoint",
        metavar="URL",
        help="am-server base URL (e.g. http://localhost:8000). Overrides config.",
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


async def _run_proxy(
    agent_name: str,
    agent_args: list[str],
    project_id: str | None,
    endpoint: str | None,
    api_key: str | None,
    debug: bool,
) -> int:
    """Load config, look up agent, and run ACPProxy.

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

    agent_cfg = get_agent_config(agent_name)
    proxy = ACPProxy(
        binary=agent_cfg.binary,
        args=agent_args,
        config=config,
        project_id=project_id,
    )
    return await proxy.run()


def main() -> None:
    """Entry point for am-proxy CLI.

    Sets Windows ProactorEventLoop policy before asyncio.run() on win32.
    """
    # Windows requires ProactorEventLoop for subprocess streams.
    # Set before asyncio.run() for Python 3.10/3.11 compatibility.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    parser = _build_parser()
    args, remaining = parser.parse_known_args()

    # All unrecognized args are passed through to the agent binary
    agent_args: list[str] = list(remaining)

    if args.subcommand == "setup":
        _cmd_setup()
        return

    if not args.agent:
        parser.error("--agent NAME is required when not using a subcommand.")

    exit_code = asyncio.run(
        _run_proxy(
            agent_name=args.agent,
            agent_args=agent_args,
            project_id=args.project,
            endpoint=args.endpoint,
            api_key=getattr(args, "api_key", None),
            debug=args.debug,
        )
    )
    sys.exit(exit_code)
