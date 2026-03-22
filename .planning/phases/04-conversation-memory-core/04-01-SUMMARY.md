---
phase: "04"
plan: "04-01"
subsystem: conversation-memory-core
tags: [graph-writer, neo4j, vector-index, bug-fix, migration, tests]
dependency_graph:
  requires: []
  provides: [GraphWriter.write_session_node, GraphWriter.write_has_turn_relationship, GraphWriter.write_part_of_turn_relationship, ConnectionManager.fix_vector_index_dimensions]
  affects: [04-02, 04-03, 04-04]
tech_stack:
  added: []
  patterns: [MERGE-on-composite-key, ON-CREATE-ON-MATCH, CASE-expression-max-tracking, DROP-IF-EXISTS-migration]
key_files:
  created:
    - tests/test_conversation_graph_writer.py
  modified:
    - src/codememory/core/connection.py
    - src/codememory/core/graph_writer.py
decisions:
  - "fix_vector_index_dimensions() as separate method: IF NOT EXISTS in setup_database() cannot correct already-existing indexes; migration method does DROP + CREATE unconditionally"
  - "CASE expression for last_turn_index: avoids race condition from Python-side max() computation; max tracking happens atomically in Cypher"
  - "Session matched by session_id alone (not composite): session_id is the natural unique key for conversation grouping; project_id is a property, not part of the identity key"
metrics:
  duration_minutes: 4
  completed_date: "2026-03-22"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 2
  files_created: 1
---

# Phase 4 Plan 1: GraphWriter Extensions + Vector Index Bug Fix Summary

**One-liner:** Fixed 3072d->768d vector index bug for Gemini embeddings, added Session MERGE method with CASE-based last_turn_index tracking, and three conversation topology GraphWriter methods with full unit test coverage.

## Tasks Completed

| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | Fix vector index DDL + add fix_vector_index_dimensions() | 2174836 | Done |
| 2 | Add write_session_node, write_has_turn_relationship, write_part_of_turn_relationship to GraphWriter | 366d429 | Done |
| 3 | Create tests/test_conversation_graph_writer.py with 12 unit tests | fafbd09 | Done |

## What Was Built

### Task 1: Vector Index Bug Fix (`connection.py`)

Changed `research_embeddings` and `chat_embeddings` DDL from 3072 to 768 dimensions in `setup_database()`. `code_embeddings` (OpenAI text-embedding-3-large) correctly remains at 3072d.

Added `fix_vector_index_dimensions()` migration helper that:
- Drops both indexes with `IF EXISTS` (no-op on fresh DBs)
- Recreates unconditionally at 768d
- Required because `IF NOT EXISTS` in `setup_database()` silently skips correction of already-created wrong-dimension indexes

### Task 2: GraphWriter Conversation Methods (`graph_writer.py`)

Three new methods appended after `write_part_of_relationship` — no existing methods modified:

**`write_session_node(props, turn_index, started_at)`**
- MERGE on `session_id` with `Memory:Conversation:Session` labels
- ON CREATE: sets full props, `started_at`, `turn_count=1`, `last_turn_index=turn_index`
- ON MATCH: CASE expression tracks `max(existing, new)` for `last_turn_index`; increments `turn_count`

**`write_has_turn_relationship(session_id, turn_source_key, turn_content_hash, order)`**
- Mirrors `write_has_chunk_relationship` pattern for conversation topology
- MATCH Session by `session_id`; MATCH Turn by `(source_key, content_hash)`
- MERGE `:HAS_TURN {order: $order}` for idempotent ordered relationship

**`write_part_of_turn_relationship(turn_source_key, turn_content_hash, session_id)`**
- Reverse arc: Turn -> Session via `:PART_OF`
- Enables bidirectional traversal per CONTEXT.md schema

### Task 3: Unit Tests (`tests/test_conversation_graph_writer.py`)

12 tests across 4 classes:
- `TestWriteSessionNode` (4 tests): MERGE key, ON CREATE/ON MATCH, CASE expression, turn_index param
- `TestWriteHasTurnRelationship` (3 tests): HAS_TURN+order, Session match, composite Turn key
- `TestWritePartOfTurnRelationship` (3 tests): PART_OF cypher, Session match, composite Turn key
- `TestGraphWriterExistingMethodsUnchanged` (2 tests): regression guard for write_memory_node and write_relationship

All mocked — no live Neo4j required.

## Verification Results

```
pytest tests/test_conversation_graph_writer.py -v   → 12 passed
pytest tests/test_web_pipeline.py -v                → 31 passed (regression)
pytest tests/test_connection.py -v                  → 6 passed (regression)
```

Total: 49 tests, 0 failures.

## Deviations from Plan

None — plan executed exactly as written.

## Decisions Made

1. **`fix_vector_index_dimensions()` as separate method:** IF NOT EXISTS in `setup_database()` cannot correct already-existing indexes. A migration method that does DROP + CREATE unconditionally is the only way to fix databases that ran the old DDL. This matches exactly the plan specification.

2. **CASE expression for `last_turn_index`:** The CASE expression tracking max value happens atomically inside Cypher, avoiding a Python-side read-modify-write race condition when multiple turns are ingested concurrently.

3. **Session identity key = `session_id` alone:** `project_id` is stored as a property but is not part of the MERGE key. A session_id is globally unique by convention (caller-owned); adding project_id would break idempotency if a turn arrived with a mismatched project_id value.

## Self-Check: PASSED

Files verified:
- `src/codememory/core/connection.py` — exists, contains `fix_vector_index_dimensions` and `768` for research/chat indexes
- `src/codememory/core/graph_writer.py` — exists, contains all three new methods
- `tests/test_conversation_graph_writer.py` — exists, 12 tests pass

Commits verified:
- `2174836` — fix(04-01): correct vector index dimensions + add migration helper
- `366d429` — feat(04-01): add three conversation topology methods to GraphWriter
- `fafbd09` — test(04-01): add unit tests for GraphWriter conversation extensions
