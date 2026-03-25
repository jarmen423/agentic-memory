---
phase: 05-am-proxy
plan: 03
subsystem: cli
tags: [argparse, asyncio, windows-proactor, am-proxy, cli]

# Dependency graph
requires:
  - phase: 05-01
    provides: ProxyConfig, AgentConfig, pyproject.toml entry point
  - phase: 05-02
    provides: ACPProxy, IngestClient, bidirectional proxy loop
provides:
  - am-proxy CLI entry point (main() registered as console_script)
  - setup subcommand to detect installed agents and print editor config snippets
  - Windows ProactorEventLoop policy set before asyncio.run() on win32
  - 19 unit tests for CLI argparse, setup output, exit codes, policy
affects: [users installing am-proxy, editor configuration workflows]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "parse_known_args() for flag-style passthrough to child binary (not REMAINDER, Python 3.13 incompatible)"
    - "asyncio.run() with side_effect coro.close() in tests to suppress RuntimeWarning"
    - "Windows ProactorEventLoop policy set as first action in main() before asyncio.run()"

key-files:
  created:
    - packages/am-proxy/src/am_proxy/cli.py
    - packages/am-proxy/tests/test_cli.py
  modified:
    - .planning/phases/05-am-proxy/05-03-PLAN.md

key-decisions:
  - "Removed argparse.REMAINDER from parser — Python 3.13 treats bare positional args as invalid subcommand choices; rely on parse_known_args() remaining list for flag passthrough"
  - "Used type(call_arg).__name__ == 'WindowsProactorEventLoopPolicy' assertion instead of direct equality to handle cross-platform test environments"
  - "asyncio.run mock uses side_effect with coro.close() to prevent RuntimeWarning: coroutine never awaited"

patterns-established:
  - "CLI entry: Windows ProactorEventLoop policy → parse_known_args → dispatch setup/run"
  - "Test isolation: patch asyncio.run with side_effect lambda closing coroutine"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-03-25
---

# Phase 05 Plan 03: CLI Entry Point + Setup Command + Tests Summary

**argparse CLI wiring config.py + agents.py + proxy.py into am-proxy --agent/setup entry point with Windows ProactorEventLoop and 19 unit tests**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-25T04:08:00Z
- **Completed:** 2026-03-25T04:22:56Z
- **Tasks:** 2 (Task 1: cli.py, Task 2: test_cli.py)
- **Files modified:** 2 created + 1 plan updated

## Accomplishments
- `cli.py` implements `main()` as `am-proxy` console_script entry point with argparse subparsers
- Windows `ProactorEventLoop` policy set before `asyncio.run()` on `win32`
- `setup` subcommand detects installed agents via `shutil.which` and prints editor config snippets
- `--endpoint`, `--api-key`, `--project`, `--debug` override `ProxyConfig` fields before `ACPProxy.run()`
- 19 CLI unit tests covering parser flags, setup output, Windows policy, exit code propagation
- Full am-proxy suite: **41 tests pass** (19 new + 5 ingest + 17 proxy)

## Task Commits

1. **Tasks 1 + 2: cli.py + test_cli.py** - `2a0ae2b` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `packages/am-proxy/src/am_proxy/cli.py` — main() entry point: argparse, Windows policy, setup/run dispatch
- `packages/am-proxy/tests/test_cli.py` — 19 unit tests: parser, setup output, policy, exit codes

## Decisions Made
- Removed `argparse.REMAINDER` from parser — Python 3.13 subparser behavior rejects bare positional args (like `file.py`) as invalid subcommand choices even in `parse_known_args`. Rely entirely on `remaining` list from `parse_known_args()` for flag passthrough.
- Used `type(call_arg).__name__ == "WindowsProactorEventLoopPolicy"` assertion in tests (not direct `==` equality) to work on non-Windows CI where the class attribute access may differ.
- Mocked `asyncio.run` with `side_effect=lambda coro: (coro.close(), 0)[1]` to prevent `RuntimeWarning: coroutine never awaited`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed argparse.REMAINDER — Python 3.13 subparser incompatibility**
- **Found during:** Task 2 (writing test_cli.py)
- **Issue:** `parse_known_args` with subparsers + `REMAINDER` raises `ArgumentError: invalid choice` for any positional arg (bare filenames) in Python 3.13 — the subparser's positional handler intercepts them before REMAINDER can capture
- **Fix:** Removed `agent_args` REMAINDER positional from parser; rely on `parse_known_args()` `remaining` list for all unknown args. `main()` sets `agent_args = list(remaining)`.
- **Files modified:** `packages/am-proxy/src/am_proxy/cli.py`
- **Verification:** All 41 tests pass; `--help` renders; unknown flags like `--verbose` correctly appear in remaining
- **Committed in:** `2a0ae2b` (Task 1+2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug fix for Python 3.13 compatibility)
**Impact on plan:** Behavior preserved — unknown CLI flags still pass through to child binary via `remaining`. Positional bare-word args (rare for ACP agents) are also passed through. No functional regression.

## Issues Encountered
- Python 3.13 changed argparse subparser positional handling — `parse_known_args` no longer swallows positional args that don't match subcommand choices. Fixed by relying on `remaining` instead of `REMAINDER` nargs.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- Phase 5 (am-proxy) is complete. All three plans (05-01, 05-02, 05-03) are done.
- `am-proxy --agent claude --project <id>` is wired end-to-end.
- `am-proxy setup` detects and reports installed agents.
- Ready for Phase 6 (browser extension passive capture path).

## Self-Check: PASSED
- cli.py: FOUND
- test_cli.py: FOUND
- SUMMARY.md: FOUND
- commit 2a0ae2b: FOUND

---
*Phase: 05-am-proxy*
*Completed: 2026-03-25*
