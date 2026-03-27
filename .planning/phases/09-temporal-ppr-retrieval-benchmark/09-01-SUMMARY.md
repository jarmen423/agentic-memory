# 09-01 Summary: Python <-> SpacetimeDB Bridge and Shadow Writes

**Date:** 2026-03-26  
**Status:** Complete

## Delivered

- Added `src/codememory/temporal/bridge.py` with:
  - `TemporalBridge`
  - `TemporalBridgeError`
  - `TemporalBridgeUnavailableError`
  - `get_temporal_bridge()`
- Added `src/codememory/temporal/__init__.py`
- Added `packages/am-temporal-kg/scripts/query_temporal.ts`
  - long-lived stdio JSON-lines helper
  - `retrieve`
  - `ingest_claim`
  - `ingest_relation`
- Added `packages/am-temporal-kg/tsconfig.scripts.json`
- Updated `packages/am-temporal-kg/package.json`
  - new `bridge` script
  - script typecheck coverage
- Wired best-effort temporal shadow writes into:
  - `src/codememory/chat/pipeline.py`
  - `src/codememory/web/pipeline.py`
- Injected the cached bridge into pipeline factories in:
  - `src/am_server/dependencies.py`
  - `src/codememory/server/tools.py`
  - `src/codememory/server/app.py`

## Behavior

- Python now keeps one cached helper process instead of spawning a Node process per request.
- Missing temporal env config disables the bridge cleanly instead of crashing ingest paths.
- Conversation ingest mirrors entity relations with:
  - `sourceKind = conversation_turn`
  - `sourceId = {session_id}:{turn_index}`
- Research ingest mirrors:
  - chunk relations with `sourceKind = research_chunk`
  - finding relations with `sourceKind = research_finding`
  - report-level extracted claims using stable `research_chunk` evidence ids
- All temporal shadow writes are best-effort and explicitly non-blocking.

## Verification

- `npm run typecheck --workspace am-temporal-kg`
- `python -m pytest tests/test_temporal_bridge.py tests/test_conversation_pipeline.py tests/test_web_pipeline.py -x -q`

Both passed.
