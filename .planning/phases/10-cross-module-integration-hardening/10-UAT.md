---
phase: 10-cross-module-integration-hardening
status: in_progress
updated: 2026-04-01T18:30:00Z
summary:
  passed: 4
  pending: 2
  blocked: 0
---

# Phase 10 UAT

## Goal

Close the cross-module integration and hardening phase with:

- unified search available through MCP and REST
- config-driven embedding-provider selection in live runtime paths
- request correlation and structured fallback logging
- full-stack startup and operator documentation
- an integration suite for app-surface unified search and fallback behavior

## Checks

### Test 1

- name: REST unified search returns normalized cross-module results
- status: pass
- method: automated
- evidence:
  - `tests/integration/test_full_stack_search.py::test_search_all_returns_code_and_temporal_web_results`
  - `tests/test_am_server.py::test_search_all_endpoint_returns_unified_results`

### Test 2

- name: Unified search survives partial module failure
- status: pass
- method: automated
- evidence:
  - `tests/integration/test_full_stack_search.py::test_search_all_surfaces_partial_module_failures`
  - `tests/test_unified_search.py::test_search_all_memory_records_partial_module_failures`

### Test 3

- name: Live web/chat embedding runtime is config-driven and Nemotron-selectable
- status: pass
- method: automated
- evidence:
  - `tests/test_embedding_runtime.py`
  - `tests/test_cli.py::test_resolve_scheduler_dependencies_uses_web_embedding_runtime`
  - `tests/test_am_server.py::test_get_pipeline_uses_web_embedding_runtime`
  - `tests/test_am_server.py::test_get_conversation_pipeline_uses_chat_embedding_runtime`

### Test 4

- name: Request correlation and structured fallback logging exist on app paths
- status: pass
- method: automated
- evidence:
  - `tests/test_am_server.py::test_health_includes_request_id_header`
  - `tests/test_am_server.py::test_search_conversations_temporal_failure_logs_structured_fallback`
  - `tests/test_web_tools.py::TestSearchWebMemory::test_search_web_memory_logs_structured_fallback`
  - `tests/test_retry.py`

### Test 5

- name: New contributor can follow committed full-stack docs from a fresh terminal sequence
- status: pending
- method: manual
- required steps:
  - follow `docs/SETUP_FULL_STACK.md`
  - start Neo4j
  - start SpacetimeDB
  - publish/generate temporal module if needed
  - start `am-server`
  - verify `/health` and `/search/all`

### Test 6

- name: Live local full-stack run proves unified search and fallback behavior with actual services
- status: pending
- method: manual
- required steps:
  - run the documented stack with local services
  - ingest or seed representative code, research, and conversation data
  - verify `/search/all`
  - verify conversation or research fallback with temporal bridge unavailable

## Notes

- Phase 10 implementation work is materially complete for `10-01` and `10-02`.
- The remaining closeout is mostly operational verification and documentation-driven reproducibility.
