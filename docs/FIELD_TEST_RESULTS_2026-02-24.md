# Field Test Results (2026-02-24)

## Context

- Environment: cloned repo `radiology-ai-video-v2`
- Package source: TestPyPI install in local venv
- Neo4j: local Docker instance
- MCP startup path: wrapper script (old version, pre-`--repo` support)

Wrapper used during test:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
set -a
source .env
set +a
exec codememory serve --port 8090
```

## Results

### 1. Semantic Retrieval Quality

- Query: `HeyGen video generation` (limit 3)
- Top results included relevant backend and frontend entities:
  - `HeyGenService` (score ~0.76)
  - `generate_avatar_clip` (score ~0.74)
  - `VideoBrain` (score ~0.70)
- Outcome: strong relevance for cross-stack lookup.

### 2. End-to-End Tooling Flow

- Query flow: semantic search -> file dependency inspection -> impact analysis
- Representative frontend target: `frontend/src/components/XRayIngestion.tsx`
- Observed outcomes:
  - file info extraction worked
  - impact analysis worked (reported isolated impact in this case)
  - dependency extraction for TSX was weak at test time (`No imports found`)

## Findings

- Core retrieval and graph traversal are functioning end-to-end.
- A dependency-parsing gap was identified for JS/TS/TSX import edges.

## Follow-up Implemented After This Test

- Added JS/TS/TSX import extraction and linking in `pass_3_imports`.
- Added per-file rebuild of `IMPORTS` edges during full index to avoid stale relationships.
- Added unit coverage for JS/TS import extraction and TSX relative-path candidate resolution.

## Re-Validation Plan

1. Re-run `codememory index` on the same repo.
2. Re-run `get_file_dependencies` on `frontend/src/components/XRayIngestion.tsx`.
3. Confirm non-empty `imports` for files with known TSX imports.
4. Spot-check additional TS/TSX files for false positives/negatives.

---

## Validation Run (User Reported, 2026-02-24)

### Environment/State Fix

- During indexing, authentication initially failed with Neo4j auth/rate-limit style errors.
- Root cause: `.codememory/config.json` password mismatch (`"1"` vs expected `"radiology-app"` from `.env`).
- After correcting config, indexing resumed successfully.

### Graph Size Snapshot

- Node count: `649`
- Relationship count: `1384`

### Test Outcomes

1. Python dependency accuracy: **PASS**
   - Semantic search surfaced `new-backend/app/.../job_store.py` for DB-related logic.
   - `get_file_dependencies` returned meaningful importers/imports for that file.
   - `identify_impact` reported broad downstream impact (`22` affected files, depth up to `3`).

2. Prune behavior regression: **PASS**
   - Added `frontend/_archive/` to `.codememory/.graphignore`.
   - Re-indexed and verified:
   - `MATCH (f:File) WHERE f.path CONTAINS "frontend/_archive" RETURN count(f);` -> `0`

3. Reindex dedupe behavior: **PASS**
   - Re-running `codememory index` with no source changes produced:
   - Embedding API Calls: `0`
   - Tokens Used: `0`
   - Estimated Cost: `$0.0000`
   - Processed entities: `0`

4. Graph health checks: **PASS**
   - Orphan chunks: `0`
   - Duplicate function signatures: none
   - `IMPORTS` edges: `169`
   - `CALLS` edges: `506`

### Summary

- Ingestion, prune/deletion, dedupe, and core graph integrity checks all passed.
- The graph appears healthy for continued MCP/tool validation.

---

## Validation Run (User Reported, v0.1.3, 2026-02-24)

### 1. TS/JSX Dependency Extraction: **PASS**

- Target file: `frontend/src/components/XRayIngestion.tsx`
- Prior issue (`No imports found`) is resolved.
- `get_file_dependencies` returned:
  - Imports: `ParticleBrain.tsx`, `trustStore.ts`, `config.ts`, `types/index.ts`, `mockData.ts`
  - Imported by: `App.tsx`

### 2. Tool Quality Flow (MCP): **PASS**

- Query: `HeyGen video generation`
  - Top hit: `new-backend/app/services/heygen_service.py:HeyGenService` (score `0.76`)
  - Relevance: excellent for external API service location.
  - `get_file_info`: class signature + 4 functions detected (including `generate_avatar_clip`).
  - `get_file_dependencies`: detected `app/core/config.py` import.
  - `identify_impact` (depth 3): `9` affected files, including `pipeline_service.py` and unit tests.

- Query: `PDF parsing`
  - Top hits:
    - `new-backend/app/services/pdf_service.py` (score `0.70`)
    - `frontend/.../PDFViewer.tsx` (score `0.69`)
  - Relevance: strong cross-language retrieval (backend parser + frontend parsing path).
  - `get_file_info` (`PDFViewer.tsx`): found `HighlightedText()`, `ExtractedTextView()`, `parseReportSections()`.
  - `get_file_dependencies`: mapped `Skeleton.tsx` imports.
  - `identify_impact`: mapped dependency from `LaserLinkWorkspace.tsx`.

### 3. Prune Behavior Regression: **PASS**

- `.codememory/.graphignore` included `frontend/_archive/`.
- Verification query:
  - `MATCH (f:File) WHERE f.path CONTAINS "frontend/_archive" RETURN count(f);`
  - Result: `0`

### 4. Reindex Dedupe / Cost Regression: **PASS**

- Re-ran `codememory index` with no local changes.
- Result:
  - Embedding API Calls: `0`
  - Tokens: `0`
  - Cost: `$0.0000 USD`
  - Processed entities: `0`

### 5. Graph Health Checks: **PASS**

- Orphan chunks: `0`
- Duplicate signatures (`count > 1`): empty
- `IMPORTS` edges: `224` (up from `169` in prior run, consistent with TS import extraction fix)
- `CALLS` edges: `506`

### v0.1.3 Conclusion

- Regression checks for TS/JSX imports, pruning, dedupe, and graph integrity all passed.
- MCP retrieval quality remained strong across backend/frontend and Python/TypeScript contexts.
