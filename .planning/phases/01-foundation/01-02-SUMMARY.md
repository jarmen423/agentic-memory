---
phase: 01-foundation
plan: 02
subsystem: core
tags: [embedding, entity-extraction, groq, gemini, openai, nemotron, tdd]
dependency_graph:
  requires: []
  provides:
    - codememory.core.embedding.EmbeddingService
    - codememory.core.entity_extraction.EntityExtractionService
    - codememory.core.entity_extraction.build_embed_text
  affects:
    - src/codememory/core/embedding.py
    - src/codememory/core/entity_extraction.py
tech_stack:
  added: []
  patterns:
    - Provider dispatch via class-level PROVIDERS dict
    - Groq JSON mode with temperature=0.0 and entity type filtering
    - Entity-enriched embedding text format
key_files:
  created:
    - src/codememory/core/embedding.py
    - src/codememory/core/entity_extraction.py
    - tests/test_embedding.py
    - tests/test_entity_extraction.py
  modified: []
decisions:
  - "Used gemini-embedding-2-preview per PLAN spec (not gemini-embedding-001 from RESEARCH.md)"
  - "ENTITY_EXTRACTION_PROMPT uses escaped braces {{}} for .format() compatibility"
  - "embed_batch for Gemini loops individually (SDK lacks native batch support)"
metrics:
  duration_minutes: 7
  completed_date: "2026-03-21"
  tasks_completed: 2
  files_created: 4
  files_modified: 0
---

# Phase 1 Plan 02: AI Service Layer Summary

**One-liner:** Provider-dispatching EmbeddingService (OpenAI/Gemini/Nemotron) and Groq-based EntityExtractionService with JSON mode, type filtering, and entity-enriched embedding text.

---

## What Was Built

### Task 1: EmbeddingService (`src/codememory/core/embedding.py`)

A single class dispatches embedding calls to three providers based on a string key:

- **OpenAI** — `text-embedding-3-large` at 3072d via standard OpenAI SDK
- **Gemini** — `gemini-embedding-2-preview` at 3072d (configurable) via `google-genai` SDK; always passes `output_dimensionality` explicitly (Pitfall 2 prevention)
- **Nemotron** — `nvidia/nv-embedqa-e5-v5` at 4096d via OpenAI SDK with `base_url` override to NVIDIA NIM endpoint

The `embed()` method provides a unified interface. `embed_batch()` uses a single API call for OpenAI/Nemotron and loops for Gemini (SDK limitation). The `model_info` property returns `{provider, model, dimensions}` for downstream metadata population.

### Task 2: EntityExtractionService + build_embed_text (`src/codememory/core/entity_extraction.py`)

Groq-based entity extraction with:

- JSON mode (`response_format={"type": "json_object"}`) and `temperature=0.0` for deterministic structured output
- Prompt explicitly constrains to `allowed_types` list (default: project, person, business, technology, concept)
- 8000-char truncation budget guard before LLM call
- Fallback: if response uses wrong key (e.g., "results" instead of "entities"), scans `data.values()` for first list (Pitfall 4 prevention)
- Post-extraction filter ensures only `allowed_types` survive even if model disobeys

`build_embed_text(chunk_text, entities)` prepends entity context per locked decision in CONTEXT.md:
```
Context: Python (technology), FastAPI (technology)

<chunk text here>
```

---

## Test Coverage

| File | Tests | Framework |
|------|-------|-----------|
| `tests/test_embedding.py` | 12 tests | pytest with unittest.mock |
| `tests/test_entity_extraction.py` | 12 tests | pytest with unittest.mock |

All tests use mocked API clients — no real API calls required.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ENTITY_EXTRACTION_PROMPT curly brace escaping**
- **Found during:** Task 2 GREEN phase (test run)
- **Issue:** Prompt template contained `{"entities": []}` which caused `KeyError` when calling `.format(allowed_types=...)` since Python's `.format()` interprets `{...}` as placeholders
- **Fix:** Escaped literal braces to `{{"entities": []}}` in the prompt string
- **Files modified:** `src/codememory/core/entity_extraction.py`
- **Commit:** 73b0b52

---

## Key Decisions

1. **Gemini model name:** Used `gemini-embedding-2-preview` per PLAN.md acceptance criteria (criteria explicitly requires this string). RESEARCH.md recommends `gemini-embedding-001` (GA) but the plan spec takes precedence. Can be updated when plan is revised.

2. **Gemini batch embedding:** `embed_batch()` loops over texts individually for Gemini. The `google-genai` SDK does not provide a simple native batch interface that returns per-text vectors.

3. **Prompt brace escaping:** Python `.format()` requires literal `{` and `}` in template strings to be doubled as `{{` and `}}`. This is a Python idiom, not an API constraint.

---

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `src/codememory/core/embedding.py` exists | FOUND |
| `src/codememory/core/entity_extraction.py` exists | FOUND |
| `tests/test_embedding.py` exists | FOUND |
| `tests/test_entity_extraction.py` exists | FOUND |
| Commit 943752d (RED test_embedding) | FOUND |
| Commit 26b180f (feat embedding) | FOUND |
| Commit 138af5c (RED test_entity_extraction) | FOUND |
| Commit 73b0b52 (feat entity_extraction) | FOUND |
| All 24 tests pass | PASSED |
