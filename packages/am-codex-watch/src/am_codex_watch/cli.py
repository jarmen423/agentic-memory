"""CLI entry for am-codex-watch."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from am_codex_watch.config import load_config
from am_codex_watch.state import WatchState
from am_codex_watch.watcher import initial_scan, iter_rollout_files, run_forever


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Watch session artifact files from coding agent CLIs (pluggable adapters; "
            "Codex rollout JSONL by default) and POST turns to am-server."
        ),
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config TOML (default: ~/.config/am-codex-watch/config.toml)",
    )
    parser.add_argument("--endpoint", type=str, default=None, help="Override am-server base URL")
    parser.add_argument("--api-key", type=str, default=None, help="Bearer token for am-server")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Scan rollout files once and exit (no watch loop)",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    cfg = load_config(Path(args.config) if args.config else None)
    if args.endpoint:
        cfg.endpoint = args.endpoint
    if args.api_key is not None:
        cfg.api_key = args.api_key
    if args.debug:
        cfg.debug = True

    state = WatchState(cfg.state_path)

    if args.once:
        paths = iter_rollout_files(cfg)
        if not paths:
            print("No .jsonl files under configured roots.", file=sys.stderr)
            return 1
        from am_codex_watch.tail import process_rollout_file

        for p in paths:
            process_rollout_file(p, config=cfg, state=state)
        return 0

    run_forever(cfg, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
