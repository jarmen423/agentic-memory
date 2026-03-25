---
phase: 07-temporal-schema
plan: 02
subsystem: temporal-schema
tags:
  - neo4j
  - temporal-backfill
  - cli
  - ingestion-pipeline
requires:
  - 07-01-SUMMARY.md
provides:
  - Temporal relationship writes in web and conversation ingestion paths
  - One-shot migrate-temporal CLI command for legacy relationship backfill
affects:
  - src/codememory/web/pipeline.py
  - src/codememory/chat/pipeline.py
  - src/codememory/cli.py
  - tests/test_web_pipeline.py
  - tests/test_conversation_pipeline.py
  - tests/test_cli.py
tech_stack:
  - Python 3.10+
  - Neo4j Cypher
  - argparse
  - pytest
key_files:
  modified:
    - src/codememory/web/pipeline.py
    - src/codememory/chat/pipeline.py
    - src/codememory/cli.py
    - tests/test_web_pipeline.py
    - tests/test_conversation_pipeline.py
    - tests/test_cli.py
decisions:
  - Reuse each pipeline's existing `_now()` timestamp as the temporal write source.
  - Backfill legacy `PART_OF` relationships with two label-scoped statements so research and conversation topologies are both covered explicitly.
  - Keep `migrate-temporal` idempotent by guarding every statement with `WHERE r.valid_from IS NULL`.
metrics:
  completed_at: 2026-03-25T18:34:00-04:00
  duration: "~20m"
  task_count: 2
  file_count: 6
commits:
  - 29beae5
---

# Phase 7 Plan 02: Temporal Pipeline Wiring + Backfill CLI Summary

Plan `07-02` moved temporal metadata from the GraphWriter contract into the actual ingestion paths and added a migration command to backfill legacy edges.

## Completed Work

### Task 1: Temporal writes in web and chat pipelines

- Updated [web/pipeline.py](D:/code/agentic-memory/src/codememory/web/pipeline.py) so report/finding entity wiring now uses `write_temporal_relationship()`.
- Updated [web/pipeline.py](D:/code/agentic-memory/src/codememory/web/pipeline.py) so `write_has_chunk_relationship()`, `write_part_of_relationship()`, and `write_cites_relationship()` all receive `valid_from` and `confidence`.
- Updated [chat/pipeline.py](D:/code/agentic-memory/src/codememory/chat/pipeline.py) so conversation entity wiring now uses `write_temporal_relationship()`.
- Updated [chat/pipeline.py](D:/code/agentic-memory/src/codememory/chat/pipeline.py) so `write_has_turn_relationship()` and `write_part_of_turn_relationship()` receive temporal kwargs.
- Aligned the pipeline tests to assert the new temporal call path instead of the legacy `write_relationship()` contract.

### Task 2: `migrate-temporal` CLI command

- Added `_temporal_backfill_statements()` to [cli.py](D:/code/agentic-memory/src/codememory/cli.py) with 14 ordered, idempotent Cypher statements.
- Added `cmd_migrate_temporal()` to [cli.py](D:/code/agentic-memory/src/codememory/cli.py), including per-statement progress logging and a clear `ServiceUnavailable` error path.
- Registered the `migrate-temporal` subcommand in the main argparse parser and dispatch block.
- Added CLI tests covering parser registration, the happy path, and the Neo4j unavailable path.

## Verification

Executed and passed:

```powershell
python -m pytest tests/test_web_pipeline.py tests/test_conversation_pipeline.py tests/test_cli.py -q
python -m codememory.cli migrate-temporal --help
```

Observed results:

- `86 passed` across the focused web, conversation, and CLI suites
- `migrate-temporal` help rendered successfully via `python -m codememory.cli`

Additional spot-check:

```powershell
rg -n "write_temporal_relationship|write_relationship" src/codememory/web/pipeline.py src/codememory/chat/pipeline.py
```

Observed result:

- Only `write_temporal_relationship` remains in the web and chat pipelines

## Deviations from Plan

### Auto-fixed Issues

**1. The installed `codememory` console script in the shell was stale**
- **Found during:** CLI verification
- **Issue:** `codememory migrate-temporal --help` still reflected an older installed entrypoint even though the source parser had been updated.
- **Fix:** Verified the source-path CLI directly with `python -m codememory.cli migrate-temporal --help`. A later editable reinstall will refresh the console script once the remaining CLI work lands.

## User Constraint Overrides

- `.planning/STATE.md` and `.planning/ROADMAP.md` were intentionally left untouched because shared phase tracking remained orchestrator-owned during parallel execution.

## Self-Check

PASSED

- No `write_relationship()` calls remain in the web or chat pipelines
- `migrate-temporal` is registered in parser tests and executes 14 statements in the mocked CLI path
- Focused pipeline and CLI regression suites passed
