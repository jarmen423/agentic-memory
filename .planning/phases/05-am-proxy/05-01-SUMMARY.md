---
phase: 05-am-proxy
plan: "01"
subsystem: infra
tags: [am-proxy, hatchling, pyproject, dataclass, toml, httpx, asyncio, python-package]

# Dependency graph
requires: []
provides:
  - packages/am-proxy/ standalone Python package scaffold with hatchling src layout
  - ProxyConfig dataclass with TOML loader (load_config, missing file safe)
  - AGENT_CONFIGS registry mapping claude/codex/gemini/opencode/kiro to binaries
  - pytest conftest with test_config and debug_config fixtures
affects:
  - 05-02
  - 05-03

# Tech tracking
tech-stack:
  added:
    - hatchling (build backend for am-proxy package)
    - httpx>=0.27.0 (async HTTP for fire-and-forget ingest POSTs)
    - tomli>=2.0.0 (Python 3.10 backport for TOML parsing; stdlib tomllib used on 3.11+)
    - pytest-asyncio>=0.21.0 (asyncio_mode=auto for async test support)
  patterns:
    - Standalone package in packages/ subdir with no imports from main codememory package
    - tomllib/tomli conditional import pattern for Python 3.10/3.11+ compatibility
    - ProxyConfig dataclass with all-defaults (missing config file never raises)
    - Passthrough fallback in get_agent_config() for unknown agent names

key-files:
  created:
    - packages/am-proxy/pyproject.toml
    - packages/am-proxy/README.md
    - packages/am-proxy/src/am_proxy/__init__.py
    - packages/am-proxy/src/am_proxy/config.py
    - packages/am-proxy/src/am_proxy/agents.py
    - packages/am-proxy/tests/__init__.py
    - packages/am-proxy/tests/conftest.py
  modified:
    - .planning/phases/05-am-proxy/05-01-PLAN.md (status: complete)

key-decisions:
  - "am-proxy is a fully standalone package in packages/ with no imports from codememory or am_server"
  - "ProxyConfig uses dataclasses.dataclass (not Pydantic) to keep the package lightweight"
  - "get_agent_config() returns a passthrough AgentConfig for unknown names rather than raising"
  - "tomllib/tomli conditional import placed at module top-level with type: ignore[no-redef]"

patterns-established:
  - "packages/ subdirectory pattern for standalone tools that ship independently from the main agentic-memory package"
  - "Malformed TOML in load_config() silently falls back to defaults (bare except Exception)"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-03-25
---

# Phase 5 Plan 01: Package Scaffolding + Config + Agents Summary

**Standalone am-proxy package scaffold with hatchling src layout, ProxyConfig TOML loader with safe defaults, and AGENT_CONFIGS registry for five known ACP agent CLIs**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-25T03:49:35Z
- **Completed:** 2026-03-25T03:55:00Z
- **Tasks:** 4
- **Files modified:** 7

## Accomplishments

- Created packages/am-proxy/ from scratch as a fully installable standalone Python package (hatchling, src layout, entry point am-proxy = am_proxy.cli:main)
- Implemented ProxyConfig dataclass with 6 fields and load_config() that reads [am_proxy] TOML section with complete defaults — missing or malformed files never raise
- Implemented AGENT_CONFIGS with 5 entries (claude/codex/gemini/opencode/kiro), case-insensitive get_agent_config(), and detect_installed_agents() via shutil.which
- Wired pytest infrastructure with conftest.py providing test_config and debug_config fixtures; pytest collection succeeds with exit 5 (no test functions yet, as expected)

## Task Commits

Each task was committed atomically:

1. **Task 1: Package directory tree and pyproject.toml** - `8d3fe8e` (feat)
2. **Task 2: config.py TOML loader** - `97824aa` (feat)
3. **Task 3: agents.py registry** - `dad043b` (feat)
4. **Task 4: Test infrastructure** - `2cf1ff6` (feat)

## Files Created/Modified

- `packages/am-proxy/pyproject.toml` - Hatchling build config, entry point, conditional tomli dep, asyncio_mode=auto
- `packages/am-proxy/README.md` - Minimal usage documentation
- `packages/am-proxy/src/am_proxy/__init__.py` - Package init with __version__
- `packages/am-proxy/src/am_proxy/config.py` - ProxyConfig dataclass + load_config() TOML loader
- `packages/am-proxy/src/am_proxy/agents.py` - AgentConfig dataclass, AGENT_CONFIGS dict, get_agent_config(), detect_installed_agents()
- `packages/am-proxy/tests/__init__.py` - Empty package marker
- `packages/am-proxy/tests/conftest.py` - test_config and debug_config fixtures

## Decisions Made

- Used `dataclasses.dataclass` for ProxyConfig rather than Pydantic — keeps am-proxy dependency footprint minimal (no pydantic required)
- `get_agent_config()` returns passthrough `AgentConfig(binary=name, source_agent=name)` for unknowns, so arbitrary agent CLIs can be proxied without config updates
- Placed the `tomllib/tomli` conditional import at module level with `# type: ignore[no-redef]` per plan spec

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. The package installed cleanly, all module imports worked, and main package tests showed zero regressions (218 passed, 2 skipped for Neo4j).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- packages/am-proxy/ is fully installed in editable mode and importable
- ProxyConfig and AGENT_CONFIGS provide the data contracts needed by proxy.py (05-02) and cli.py (05-03)
- Shared test fixtures in conftest.py are ready for test modules in subsequent plans

## Self-Check: PASSED

All created files verified present. All task commits verified in git log.

| Check | Result |
|-------|--------|
| packages/am-proxy/pyproject.toml | FOUND |
| packages/am-proxy/README.md | FOUND |
| packages/am-proxy/src/am_proxy/__init__.py | FOUND |
| packages/am-proxy/src/am_proxy/config.py | FOUND |
| packages/am-proxy/src/am_proxy/agents.py | FOUND |
| packages/am-proxy/tests/__init__.py | FOUND |
| packages/am-proxy/tests/conftest.py | FOUND |
| Commit 8d3fe8e | FOUND |
| Commit 97824aa | FOUND |
| Commit dad043b | FOUND |
| Commit 2cf1ff6 | FOUND |

---
*Phase: 05-am-proxy*
*Completed: 2026-03-25*
