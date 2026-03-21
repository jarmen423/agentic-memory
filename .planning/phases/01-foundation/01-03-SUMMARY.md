---
phase: 01-foundation
plan: "03"
subsystem: core-abstractions
tags: [abc, neo4j, graph-writer, merge, config-validator, embedding, tdd]

requires:
  - phase: 01-01
    provides: SOURCE_REGISTRY, ConnectionManager
  - phase: 01-02
    provides: EmbeddingService with PROVIDERS dict and fixed dimensions

provides:
  - BaseIngestionPipeline ABC (DOMAIN_LABEL + ingest() + node_labels() contract)
  - GraphWriter with MERGE-based Memory node, Entity node, and relationship writes
  - ConfigValidator that catches provider/dimension mismatches at startup
  - core __init__.py exporting all public interfaces

affects: [02-web-research, 03-web-scheduling, 04-conversation-memory, 05-integration]

tech-stack:
  added: []
  patterns:
    - "MERGE on composite key (source_key, content_hash) for idempotent Memory node writes"
    - "MERGE on (name, type) for idempotent Entity node writes"
    - "namespace property: written only when provided, never set to None when absent"
    - "GraphWriter parameterizes all values — never interpolates into Cypher strings"
    - "ABC enforcement: DOMAIN_LABEL class variable + @abstractmethod ingest()"

key-files:
  created:
    - src/codememory/core/base.py
    - src/codememory/core/graph_writer.py
    - src/codememory/core/config_validator.py
    - tests/test_base.py
    - tests/test_config_validator.py
  modified:
    - src/codememory/core/__init__.py

key-decisions:
  - "Namespace property written only when provided (not set to None) — avoids unintentional nulls on nodes without namespace"
  - "Gemini MRL allows any output_dimensionality — ConfigValidator logs warning but does not raise"
  - "GraphWriter namespace handled via conditional Cypher string branch (not post-hoc SET) — cleaner than a single template with conditional SET logic"

patterns-established:
  - "TDD RED commit before implementation: test(01-03) prefix used consistently"
  - "All Cypher writes use parameterized queries — values never interpolated into string"
  - "Entity type label capitalized via .capitalize() for consistent :Entity:Technology pattern"

requirements-completed:
  - FOUND-BASE-PIPELINE
  - FOUND-GRAPH-WRITER
  - FOUND-CONFIG-VALIDATOR

duration: 5min
completed: 2026-03-21
---

# Phase 1 Plan 3: Core Abstraction Layer Summary

**BaseIngestionPipeline ABC + GraphWriter MERGE patterns + ConfigValidator dimension mismatch detection, with TDD coverage across 25 unit tests**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-21T06:50:16Z
- **Completed:** 2026-03-21T06:55:02Z
- **Tasks:** 2
- **Files modified:** 5 created, 1 modified

## Accomplishments

- BaseIngestionPipeline ABC enforces DOMAIN_LABEL class variable and ingest() abstract method; node_labels() resolves from SOURCE_REGISTRY with fallback
- GraphWriter writes Memory nodes via MERGE on (source_key, content_hash) composite key with all required metadata fields; handles namespace presence/absence correctly
- GraphWriter upserts Entity nodes via MERGE on (name, type) and writes Memory->Entity relationships via MATCH+MERGE
- ConfigValidator catches unknown providers and dimension mismatches for fixed-dimension providers (OpenAI, Nemotron) at startup; allows Gemini MRL with a warning
- core __init__.py now exports all 9 public symbols via `__all__`

## Task Commits

Each task was committed atomically using TDD (RED then GREEN):

1. **Task 1 RED: BaseIngestionPipeline + GraphWriter failing tests** - `a4dd1bb` (test)
2. **Task 1 GREEN: BaseIngestionPipeline + GraphWriter implementation** - `40aeb87` (feat)
3. **Task 2 RED: ConfigValidator failing tests** - `803ebd0` (test)
4. **Task 2 GREEN: ConfigValidator + core __init__.py exports** - `57429ca` (feat)

**Plan metadata:** (docs commit below)

_Note: TDD tasks have two commits each (test RED → feat GREEN)_

## Files Created/Modified

- `src/codememory/core/base.py` - BaseIngestionPipeline ABC with DOMAIN_LABEL, ingest(), node_labels()
- `src/codememory/core/graph_writer.py` - GraphWriter with write_memory_node(), upsert_entity(), write_relationship()
- `src/codememory/core/config_validator.py` - validate_embedding_config() with LABEL_DIMENSION_MAP and MRL-aware provider logic
- `src/codememory/core/__init__.py` - Full public export surface via __all__ (9 symbols)
- `tests/test_base.py` - 15 unit tests for BaseIngestionPipeline and GraphWriter
- `tests/test_config_validator.py` - 10 unit tests for ConfigValidator

## Decisions Made

- **Namespace property conditional branch:** namespace is handled via a two-branch Cypher approach (one with `m.namespace = $namespace` in ON CREATE SET, one without) rather than a single template with a dynamic SET. This avoids the risk of setting namespace to None on CREATE when no namespace was provided.
- **Gemini MRL dimension flexibility:** ConfigValidator only warns (does not raise) when Gemini is configured with non-default dimensions, because Gemini supports Matryoshka Representation Learning via output_dimensionality. OpenAI and Nemotron have fixed dimensions and always raise on mismatch.
- **Entity type label capitalization:** `.capitalize()` applied to entity_type for consistent `:Entity:Technology` Neo4j label pattern.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Core abstraction layer complete: BaseIngestionPipeline, GraphWriter, ConfigValidator all tested and exported
- All memory modules (code, web, chat) can now subclass BaseIngestionPipeline
- GraphWriter ready for use in ingestion pipeline implementations (Plans 02 onward)
- ConfigValidator ready to be called at application startup to catch config errors early
- 25 unit tests pass; all prior tests continue to pass

---
*Phase: 01-foundation*
*Completed: 2026-03-21*
