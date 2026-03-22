# Deferred Items — Phase 02 Web Research Core

## Pre-existing Test Isolation Issue (out of scope for 02-03)

**Found during:** Plan 02-03 full suite run
**Symptom:** 2 tests fail when full suite runs but pass in isolation

### Affected tests
- `tests/test_web_pipeline.py::TestResearchIngestionPipelineFindingFlow::test_ingest_finding_flow`
- `tests/test_web_pipeline.py::TestSourceRegistration::test_source_registration`

### Root cause
The `SOURCE_REGISTRY` global dict in `codememory.core.registry` gets cleared by another test
running earlier in the suite (likely `tests/test_registry.py` which resets it). When
`pipeline.py` is first imported it calls `register_source(...)` at module level, but if the
registry is cleared after that import, the entries are gone for subsequent tests.

### Error messages
```
AssertionError: assert 'deep_research_agent' in {}  # registry was cleared
AssertionError: assert 'Finding' in ['Memory', 'Research']  # labels wrong due to empty registry
```

### Fix approach (deferred)
- Add `autouse` fixture in `conftest.py` to reset SOURCE_REGISTRY before each test, or
- Re-import `pipeline.py` in fixture to trigger re-registration, or
- Use `importlib.reload()` to re-run module-level registration

This issue existed before Plan 02-03 (verified by running `pytest --ignore=tests/test_web_tools.py`).
