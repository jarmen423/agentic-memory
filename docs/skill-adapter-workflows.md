# Skill Adapter Workflows

This document covers operator workflows for the `agentic-memory-adapter` skill.
It is shell-first for deterministic execution and escalates to MCP tools for
graph analysis steps (`deps`, `impact`).

## Prerequisites

- `codememory` CLI installed and available on `PATH`
- Repo initialized (`.codememory/config.json` exists) when running indexing/search
- Neo4j reachable from the machine running commands
- Optional for semantic search: `OPENAI_API_KEY`

Helper scripts used below:
- `skills/agentic-memory-adapter/scripts/run_codememory.sh`
- `skills/agentic-memory-adapter/scripts/health_check.sh`

## Copy-Paste Setup Snippets

### Linux

```bash
REPO="/home/$USER/code/my-repo"
ADAPTER="./skills/agentic-memory-adapter/scripts/run_codememory.sh"
HEALTH="./skills/agentic-memory-adapter/scripts/health_check.sh"
"$ADAPTER" --repo "$REPO" -- status
```

### macOS

```bash
REPO="/Users/$USER/code/my-repo"
ADAPTER="./skills/agentic-memory-adapter/scripts/run_codememory.sh"
HEALTH="./skills/agentic-memory-adapter/scripts/health_check.sh"
"$ADAPTER" --repo "$REPO" -- status
```

### WSL

```bash
REPO="/mnt/c/Users/<you>/code/my-repo"
ADAPTER="./skills/agentic-memory-adapter/scripts/run_codememory.sh"
HEALTH="./skills/agentic-memory-adapter/scripts/health_check.sh"
"$ADAPTER" --repo "$REPO" -- status
```

## Workflow 1: Index + Prune

`codememory index` runs the ingestion pipeline and pass-1 pruning logic for
excluded/stale files. Use this after large file moves/deletes or ignore-rule
changes.

```bash
REPO="/abs/path/to/repo"
./skills/agentic-memory-adapter/scripts/run_codememory.sh \
  --repo "$REPO" \
  --timeout 180 \
  --retries 1 \
  -- index

./skills/agentic-memory-adapter/scripts/run_codememory.sh --repo "$REPO" -- status
```

## Workflow 2: Search + Deps

1. Run quick semantic search via CLI:

```bash
REPO="/abs/path/to/repo"
./skills/agentic-memory-adapter/scripts/run_codememory.sh \
  --repo "$REPO" \
  -- search "where is auth token validation?" --limit 5
```

2. Escalate to MCP dependency analysis:

```bash
REPO="/abs/path/to/repo"
codememory serve --repo "$REPO" --env-file "$REPO/.env" --port 8000
```

3. In MCP client:
- `search_codebase(query="auth token validation", limit=5)`
- `get_file_dependencies(file_path="src/codememory/cli.py")`

## Workflow 3: Impact Before Refactor

Use this before changing shared files.

1. Ensure MCP server is running for the target repo:

```bash
REPO="/abs/path/to/repo"
codememory serve --repo "$REPO" --env-file "$REPO/.env" --port 8000
```

2. In MCP client:
- `identify_impact(file_path="src/codememory/ingestion/graph.py", max_depth=3)`
- Optional follow-up: `get_file_dependencies(...)` for top impacted files

3. Decide refactor scope:
- High fan-out impact: split change into smaller commits and add validation checkpoints
- Low fan-out impact: proceed with focused refactor

## Workflow 4: Health Checks

```bash
REPO="/abs/path/to/repo"
./skills/agentic-memory-adapter/scripts/health_check.sh --repo "$REPO"
```

Optional semantic check:

```bash
./skills/agentic-memory-adapter/scripts/health_check.sh \
  --repo "$REPO" \
  --search-query "entrypoint"
```

## Troubleshooting Matrix

| Symptom | Likely Cause | Remediation | Verify |
|---|---|---|---|
| `Could not connect to Neo4j` or endpoint unreachable | Neo4j not running or wrong URI | Start Neo4j, confirm `NEO4J_URI` host/port | `health_check.sh --repo "$REPO"` |
| Neo4j auth error | Wrong `NEO4J_USER` / `NEO4J_PASSWORD` | Update shell env or repo config, then retry | `run_codememory.sh --repo "$REPO" -- status` |
| `OpenAI API key not configured` on search | Missing key in env or `.env` | Set `OPENAI_API_KEY` in shell or repo `.env` | `run_codememory.sh --repo "$REPO" -- search "test"` |
| Search/deps results look outdated | Stale graph after file moves/deletes | Re-run `index` to refresh and prune stale nodes | `status` plus a targeted `search`/MCP tool call |

## Notes

- Keep `REPO` explicit to avoid accidental operations in the wrong directory.
- Use CLI adapter for fast checks; use MCP tools for dependency and impact reasoning.
