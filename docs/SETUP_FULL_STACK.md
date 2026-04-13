# Full-Stack Local Setup

This document is the self-hosted full-stack path.

If you want the managed hosted beta path instead, stop here and use:

- `D:\code\agentic-memory\docs\INSTALLATION.md`
- `D:\code\agentic-memory\docs\openclaw\DEPLOYMENT_RUNBOOK.md`

This runbook starts the full local stack used by the current Phase 10 implementation:

1. Neo4j
2. SpacetimeDB
3. `am-temporal-kg` publish and bindings generation when needed
4. `am-sync-neo4j` when you want Neo4j shadow sync from SpacetimeDB
5. `am-server`
6. REST or MCP search verification
7. Product control-plane smoke tests for packaging and dogfooding

## Prerequisites

- Docker running locally
- SpacetimeDB CLI installed
- Python environment available at `.venv-agentic-memory`
- Node dependencies installed with `npm install`
- Python package installed in editable mode (run once after cloning or after adding new modules):
  ```powershell
  .\.venv-agentic-memory\Scripts\pip.exe install -e .
  ```
- A populated `.env` file for Neo4j, auth, and provider credentials

## 1. Start Neo4j

From the repo root:

```powershell
docker compose up -d neo4j
```

Expected endpoints:

- Browser: `http://127.0.0.1:7474`
- Bolt: `bolt://127.0.0.1:7687`

## 2. Start SpacetimeDB

Choose an explicit host/port and keep `STDB_URI` aligned with it for every
later command. Do not rely on a saved `local` alias or assume `3000` is free.

Example using `3001`:

```bash
spacetime start --listen-addr 127.0.0.1:3001
```

Then export the same URI before the publish/generate/sync steps:

```powershell
$env:STDB_URI="http://127.0.0.1:3001"
```

## 3. Publish `am-temporal-kg` when needed

Republish when:

- you started a fresh SpacetimeDB instance
- the temporal module changed
- generated bindings are missing or stale

From the repo root:

```bash
$env:STDB_URI="http://127.0.0.1:3001"
npm run publish:local --workspace am-temporal-kg
npm run generate:bindings --workspace am-temporal-kg
```

Those workspace scripts now require `STDB_URI` and handle the SpacetimeDB CLI
server targeting for you. `spacetime generate` does not support `--server`, so
do not copy older docs that show `spacetime generate --server ...`; that form
is not valid.

## 4. Start `am-sync-neo4j` when the scenario needs shadow sync

Set:

- `STDB_URI`
- `STDB_MODULE_NAME`
- `STDB_BINDINGS_MODULE`
- `NEO4J_URI`
- `NEO4J_USER`
- `NEO4J_PASSWORD`

Example:

```powershell
$env:STDB_URI="http://127.0.0.1:3001"
$env:STDB_MODULE_NAME="agentic-memory-temporal"
$env:STDB_BINDINGS_MODULE="D:\code\agentic-memory\packages\am-temporal-kg\generated-bindings\index.ts"
npm run start --workspace am-sync-neo4j
```

This worker is still shadow-mode. It mirrors temporal rows into Neo4j but does not replace the existing ingestion flows.

## 5. Start `am-server`

From the repo root:

```powershell
.\.venv-agentic-memory\Scripts\dotenv.exe -f .env run -- .\.venv-agentic-memory\Scripts\python.exe -m am_server.server
```

Expected base URL:

- `http://127.0.0.1:8765`

## 6. Verify the app surface

Health:

```powershell
curl.exe "http://127.0.0.1:8765/health"
```

Unified search:

```powershell
curl.exe -H "Authorization: Bearer dev-key" "http://127.0.0.1:8765/search/all?q=phase%208&project_id=proj-smoke"
```

Conversation search:

```powershell
curl.exe -H "Authorization: Bearer dev-key" "http://127.0.0.1:8765/search/conversations?q=phase%208&project_id=proj-smoke"
```

## 7. Verify the product control plane

Use these endpoints and commands when validating the packaging layer and
repeatable install loops:

```powershell
curl.exe -H "Authorization: Bearer dev-key" "http://127.0.0.1:8765/product/status"
```

```powershell
agentic-memory product-status --json
agentic-memory product-event-record --event install_completed --actor dogfood --json
```

If you want to validate the browser-based desktop shell, start it against the same backend:

```powershell
python -m desktop_shell --backend-url http://127.0.0.1:8765
```

For the full dogfooding checklist and release gate, see:
[docs/PRODUCT_DOGFOODING.md](PRODUCT_DOGFOODING.md)

## Minimal smoke sequence after a reboot

Use this order:

1. `docker compose up -d neo4j`
2. `spacetime start`
3. republish and regenerate bindings if SpacetimeDB is fresh
4. start `am-sync-neo4j` only if you need the shadow sync path
5. start `am-server`
6. hit `/health`, then `/search/all`

## Common failures

- `Couldn't connect to 127.0.0.1:7687`
Neo4j is not up yet, or Bolt is not bound.
- `{"results":[]}` on a conversation query
Check `project_id`, `as_of`, and whether the turn was ingested under a valid conversation `source_key`.
- provider auth failures on ingest
Check the embedding provider key for the module and the extraction provider key separately.
- temporal data not appearing
Check `STDB_URI`, module publish state, generated bindings, and whether `am-sync-neo4j` is running for the scenario you are testing.
