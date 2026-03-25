---
phase: 07-temporal-schema
plan: 03
subsystem: temporal-schema
tags:
  - claim-extraction
  - groq
  - spo-triples
  - web-pipeline
requires:
  - 07-01-SUMMARY.md
provides:
  - Groq-backed ClaimExtractionService
  - Non-blocking claim extraction pass during report ingest
  - Direct Entity-to-Entity claim relationship writes
affects:
  - src/codememory/core/claim_extraction.py
  - src/codememory/web/pipeline.py
  - tests/test_claim_extraction.py
  - tests/test_web_pipeline.py
tech_stack:
  - Python 3.10+
  - Groq JSON mode
  - Neo4j Cypher
  - pytest
key_files:
  created:
    - src/codememory/core/claim_extraction.py
    - tests/test_claim_extraction.py
  modified:
    - src/codememory/web/pipeline.py
    - tests/test_web_pipeline.py
decisions:
  - Keep claim extraction independent from NER so claim failures do not block report ingest.
  - Default claim subject/object entity types to `unknown` because the claim schema does not carry typed entities.
  - Allow the report pipeline to auto-initialize claim extraction from `GROQ_API_KEY` while still supporting explicit test injection.
metrics:
  completed_at: 2026-03-25T18:47:00-04:00
  duration: "~15m"
  task_count: 2
  file_count: 4
commits:
  - 57782ba
---

# Phase 7 Plan 03: Claim Extraction + Report Pipeline Integration Summary

Plan `07-03` upgraded research ingest from entity-only wiring to an additional claim extraction pass that writes direct Entity-to-Entity relationships.

## Completed Work

### Task 1: ClaimExtractionService

- Added [claim_extraction.py](D:/code/agentic-memory/src/codememory/core/claim_extraction.py) with `ClaimExtractionService`.
- Added a closed default predicate catalog: `KNOWS`, `WORKS_AT`, `RESEARCHED`, `REFERENCES`, `USES`, `LEADS`, `PART_OF`, `LOCATED_IN`, `CREATED_BY`, `CONTRADICTS`.
- Implemented deterministic Groq JSON-mode extraction with `response_format={"type": "json_object"}` and `temperature=0.0`.
- Added normalization that remaps out-of-catalog predicates to `REFERENCES`.
- Added the 8000-character truncation guard and error wrapping to `RuntimeError`.

### Task 2: Claim extraction pass in ResearchIngestionPipeline

- Updated [web/pipeline.py](D:/code/agentic-memory/src/codememory/web/pipeline.py) to support an optional `claim_extractor` dependency and auto-initialize it from `GROQ_API_KEY` when available.
- Added a non-blocking second pass in `_ingest_report()` that calls `ClaimExtractionService.extract()` after the existing NER/entity wiring.
- Added `_write_claim()` in [web/pipeline.py](D:/code/agentic-memory/src/codememory/web/pipeline.py) to MERGE subject/object entities and write direct temporal claim relationships with `ON CREATE` / `ON MATCH` handling.
- Left `_ingest_finding()` unchanged for claim extraction, per scope.

## Verification

Executed and passed:

```powershell
python -m pytest tests/test_claim_extraction.py tests/test_web_pipeline.py -q
rg -n "ClaimExtractionService|claim_extractor|_write_claim" src/codememory/web/pipeline.py src/codememory/core/claim_extraction.py
```

Observed results:

- `41 passed` across the claim extraction and web pipeline suites
- `ClaimExtractionService`, `claim_extractor`, and `_write_claim` are present in the expected files

## Deviations from Plan

### Auto-fixed Issues

**1. Existing ResearchIngestionPipeline construction did not expose Groq credentials directly**
- **Found during:** implementation
- **Issue:** The current pipeline constructor receives an already-built `EntityExtractionService`, not raw Groq config, so the plan’s direct `ClaimExtractionService(...)` initialization path did not fit the repo’s existing call shape.
- **Fix:** Added an optional injected `claim_extractor` parameter and an environment-backed fallback initialization path. This kept all current callers working without widening the file scope beyond the plan.

## User Constraint Overrides

- `.planning/STATE.md` and `.planning/ROADMAP.md` were intentionally left untouched because shared phase tracking remained orchestrator-owned during parallel execution.

## Self-Check

PASSED

- `ClaimExtractionService` exists and is importable
- `_ingest_report()` calls the claim extractor without breaking the existing NER path
- Claim failures are logged and do not abort report ingest
