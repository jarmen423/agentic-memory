---
phase: 07-temporal-schema
plan: 01
subsystem: temporal-schema
tags:
  - neo4j
  - temporal-relationships
  - graph-writer
  - apscheduler
requires: []
provides:
  - Temporal GraphWriter helpers for Memory->Entity relationships
  - Temporal metadata on dedicated relationship write methods
  - Scheduler dependencies for later phase 07 plans
affects:
  - src/codememory/core/graph_writer.py
  - pyproject.toml
  - tests/test_conversation_graph_writer.py
  - tests/test_web_pipeline.py
tech_stack:
  - Python 3.10+
  - Neo4j Cypher
  - APScheduler 3.x
  - SQLAlchemy
key_files:
  modified:
    - pyproject.toml
    - src/codememory/core/graph_writer.py
    - tests/test_conversation_graph_writer.py
    - tests/test_web_pipeline.py
decisions:
  - Preserve the legacy write_relationship() API unchanged for backward compatibility.
  - MERGE temporal relationships only on endpoints plus relationship type; temporal fields belong in ON CREATE and ON MATCH.
  - Extend dedicated relationship writers with temporal defaults so later pipeline wiring can opt in without changing call shape again.
metrics:
  completed_at: 2026-03-25T18:20:00-04:00
  duration: "~25m"
  task_count: 2
  file_count: 4
commits:
  - 1fdfe01
  - fff022c
---

# Phase 7 Plan 01: Temporal GraphWriter + Scheduler Dependency Summary

Plan `07-01` established the temporal write contract for the graph layer and added the scheduler dependencies needed by later Phase 7 work.

## Completed Work

### Task 1: APScheduler and SQLAlchemy dependencies

- Added `apscheduler>=3.10.0,<4.0` to [pyproject.toml](D:/code/agentic-memory/pyproject.toml).
- Added `sqlalchemy>=2.0.0` to [pyproject.toml](D:/code/agentic-memory/pyproject.toml).
- Verified the APScheduler install resolves to the expected 3.x line.

### Task 2: Temporal GraphWriter helpers

- Added `write_temporal_relationship()` to [graph_writer.py](D:/code/agentic-memory/src/codememory/core/graph_writer.py) using the required MERGE-on-endpoints pattern with temporal fields in `ON CREATE SET` and support/confidence updates in `ON MATCH SET`.
- Added `update_relationship_validity()` and `increment_contradiction()` for temporal maintenance operations.
- Extended `write_cites_relationship()`, `write_has_chunk_relationship()`, `write_part_of_relationship()`, `write_has_turn_relationship()`, and `write_part_of_turn_relationship()` with temporal defaults (`valid_from`, `confidence`) and support/confidence update logic.
- Preserved the old `write_relationship()` implementation unchanged.
- Completed the temporal regression coverage in [tests/test_conversation_graph_writer.py](D:/code/agentic-memory/tests/test_conversation_graph_writer.py) and aligned the existing `PART_OF` writer assertions in [tests/test_web_pipeline.py](D:/code/agentic-memory/tests/test_web_pipeline.py).

## Verification

Executed and passed:

```powershell
python -c "import apscheduler; from apscheduler.schedulers.background import BackgroundScheduler; from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore; print(apscheduler.__version__)"
python -m pytest tests/test_conversation_graph_writer.py -q
python -m pytest tests/test_base.py tests/test_web_pipeline.py tests/test_conversation_graph_writer.py -q
```

Observed results:

- `3.11.2`
- `22 passed` in `tests/test_conversation_graph_writer.py`
- `68 passed` across `tests/test_base.py`, `tests/test_web_pipeline.py`, and `tests/test_conversation_graph_writer.py`

## Deviations from Plan

### Auto-fixed Issues

**1. Existing GraphWriter tests assumed the pre-temporal `PART_OF` MERGE form**
- **Found during:** targeted regression run
- **Issue:** The legacy assertions in `tests/test_conversation_graph_writer.py` and `tests/test_web_pipeline.py` hard-coded `MERGE (..)-[:PART_OF]->(..)`, which no longer matches the required temporal relationship variable form.
- **Fix:** Updated those assertions to validate the temporal `MERGE (..)-[rel:PART_OF]->(..)` shape instead of weakening the implementation.
- **Files modified:** `tests/test_conversation_graph_writer.py`, `tests/test_web_pipeline.py`

## User Constraint Overrides

- `.planning/STATE.md` and `.planning/ROADMAP.md` were intentionally left untouched because shared tracking remained orchestrator-owned during parallel phase execution.

## Self-Check

PASSED

- Found `write_temporal_relationship`, `update_relationship_validity`, and `increment_contradiction` in `GraphWriter`
- Found `apscheduler>=3.10.0,<4.0` and `sqlalchemy>=2.0.0` in `pyproject.toml`
- Verified targeted temporal and graph-writer regression tests passed
