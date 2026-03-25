---
phase: 07-temporal-schema
plan: 04
subsystem: temporal-schema
tags:
  - scheduler
  - apscheduler
  - brave-search
  - mcp
  - temporal-filtering
requires:
  - 07-01-SUMMARY.md
  - 07-02-SUMMARY.md
  - 07-03-SUMMARY.md
provides:
  - Persistent recurring research scheduling with APScheduler + SQLite job store
  - CLI commands for schedule creation and immediate research execution
  - MCP tools for schedule create/run/list flows
  - `as_of` temporal filtering on web and conversation search tools
affects:
  - src/codememory/core/scheduler.py
  - src/codememory/cli.py
  - src/codememory/server/tools.py
  - src/codememory/server/app.py
  - tests/test_scheduler.py
  - tests/test_cli.py
  - tests/test_web_tools.py
tech_stack:
  - Python 3.10+
  - APScheduler 3.x
  - SQLAlchemy job store
  - Brave Search API
  - Groq JSON mode
  - pytest
  - node:test
key_files:
  created:
    - src/codememory/core/scheduler.py
    - tests/test_scheduler.py
  modified:
    - src/codememory/cli.py
    - src/codememory/server/tools.py
    - src/codememory/server/app.py
    - tests/test_cli.py
    - tests/test_web_tools.py
decisions:
  - Use a module-level APScheduler job target that reconstructs runtime dependencies from environment so persisted jobs do not rely on pickling a live scheduler instance.
  - Keep schedule execution synchronous because the current research ingestion pipeline is synchronous.
  - Apply `as_of` as a node-level `ingested_at` post-filter heuristic and defer full graph-temporal filtering to a later phase.
  - Treat the stale `C:\\Users\\jfrie\\.local\\bin\\codememory.exe` as an environment shadowing issue rather than a repo code issue.
metrics:
  completed_at: 2026-03-25T18:31:00-04:00
  duration: "~40m"
  task_count: 2
  file_count: 7
commits:
  - e4876d4
---

# Phase 7 Plan 04: Research Scheduler + MCP Surface Summary

Plan `07-04` added the recurring research scheduler, exposed it through both the CLI and MCP layers, and extended search tools with a lightweight temporal `as_of` cutoff.

## Completed Work

### Task 1: ResearchScheduler

- Added [scheduler.py](D:/code/agentic-memory/src/codememory/core/scheduler.py) with `ResearchScheduler`, APScheduler job-store setup, schedule persistence, Brave Search execution, Groq-backed variable filling, and RESEARCHED-edge steering.
- Used `~/.config/agentic-memory/schedules.db` as the APScheduler SQLite job store and stable `schedule_id` values as persistent job IDs.
- Added circuit-breaker behavior for Brave Search failures and a `max_runs_per_day` skip path.
- Added `build_scheduler_from_env()` and a module-level `_sync_run_research_job()` so persisted jobs can run without serializing a live scheduler object.

### Task 2: CLI, MCP, and Temporal Search Filters

- Added `web-schedule` and `web-run-research` to [cli.py](D:/code/agentic-memory/src/codememory/cli.py), including environment-backed dependency resolution and immediate execution support.
- Added `register_schedule_tools()` to [tools.py](D:/code/agentic-memory/src/codememory/server/tools.py) with `schedule_research`, `run_research_session`, and `list_research_schedules`.
- Updated [app.py](D:/code/agentic-memory/src/codememory/server/app.py) to register the schedule tools and to expose `as_of` on `search_web_memory`.
- Updated conversation search/context tools in [tools.py](D:/code/agentic-memory/src/codememory/server/tools.py) to accept `as_of` and post-filter on `ingested_at`.
- Added scheduler/MCP coverage in [test_scheduler.py](D:/code/agentic-memory/tests/test_scheduler.py) and updated [test_cli.py](D:/code/agentic-memory/tests/test_cli.py) plus [test_web_tools.py](D:/code/agentic-memory/tests/test_web_tools.py).

## Verification

Executed and passed:

```powershell
python -m pytest tests/test_scheduler.py tests/test_web_tools.py tests/test_cli.py -q
python -m pytest tests/test_conversation_pipeline.py tests/test_web_pipeline.py tests/test_conversation_graph_writer.py -q
python -m pytest tests -q
node --test packages/am-ext/tests/*.test.js
python -m codememory.cli web-schedule --help
python -m codememory.cli web-run-research --help
python -c "from codememory.core.scheduler import ResearchScheduler; print('scheduler ok'); from codememory.server.tools import register_schedule_tools; print('tools ok')"
& "$env:APPDATA\Python\Python313\Scripts\codememory.exe" web-schedule --help
& "$env:APPDATA\Python\Python313\Scripts\codememory.exe" web-run-research --help
rg -n "as_of|schedule_research|run_research_session|list_research_schedules|web-schedule|web-run-research" src/codememory/server/app.py src/codememory/server/tools.py src/codememory/cli.py
```

Observed results:

- Full `tests/` suite passed with 2 existing Neo4j-dependent skips in `tests/test_graph.py`.
- `packages/am-ext/tests/*.test.js` passed: 10 tests, 0 failures.
- `python -m codememory.cli ... --help` recognized both new commands.
- The PATH-resolved `codememory` command remained shadowed by `C:\Users\jfrie\.local\bin\codememory.exe`, while the freshly installed user-site script at `C:\Users\jfrie\AppData\Roaming\Python\Python313\Scripts\codememory.exe` resolved correctly.

## Deviations from Plan

### Auto-fixed Issues

**1. APScheduler persisted jobs cannot safely pickle a live scheduler instance**
- **Found during:** Task 1 implementation
- **Issue:** The plan sketch passed the live `ResearchScheduler` instance as APScheduler job kwargs, but the SQLAlchemy job store must serialize job arguments across restarts.
- **Fix:** Switched to a module-level `_sync_run_research_job(schedule_id)` target that rebuilds runtime dependencies from environment and runs the scheduled job by ID.

**2. PATH shadowed the correct console script after editable reinstall**
- **Found during:** verification
- **Issue:** `codememory` resolved to the stale zero-length shim at `C:\Users\jfrie\.local\bin\codememory.exe`, so CLI verification via bare command still showed the older subcommand set.
- **Fix:** Verified the repo code path via `python -m codememory.cli ...` and the fresh user-site entrypoint via `C:\Users\jfrie\AppData\Roaming\Python\Python313\Scripts\codememory.exe ...`. No repo code change was required.

## User Constraint Overrides

- Phase 7 wave 2 was serialized internally because both `07-02` and `07-03` touched `src/codememory/web/pipeline.py`, even though phases 06 and 07 overall were still advanced in parallel.

## Self-Check

PASSED

- `ResearchScheduler` is importable and covered by unit tests.
- CLI and MCP schedule surfaces are wired and verified.
- `search_web_memory`, `search_conversations`, and `get_conversation_context` now accept `as_of`.
- Phase 06-04 verification still passes alongside the Phase 07 changes.
