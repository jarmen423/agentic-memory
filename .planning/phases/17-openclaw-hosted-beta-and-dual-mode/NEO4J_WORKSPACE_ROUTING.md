# Neo4j routing vs one URL (operator private graph)

## Implemented (narrow scope)

OpenClaw routes can use **two Bolt targets** while the plugin still uses **one**
public backend URL:

| Traffic | Neo4j |
|---------|--------|
| Workspaces listed in `AM_OPERATOR_WORKSPACE_IDS` | `NEO4J_OPERATOR_URI` (+ optional `NEO4J_OPERATOR_USER` / `NEO4J_OPERATOR_PASSWORD`) |
| Everyone else | `NEO4J_URI` (shared / main users) |

Routing is implemented in:

- `src/am_server/neo4j_routing.py` — env parsing and `use_operator_neo4j(workspace_id)`
- `src/am_server/dependencies.py` — `get_operator_*` singletons,
  `pipelines_for_openclaw_workspace`, `graph_for_openclaw_workspace`
- `src/am_server/routes/openclaw.py` — ingest, search, read use the resolvers

Startup warms operator pipelines when both `NEO4J_OPERATOR_URI` and
`AM_OPERATOR_WORKSPACE_IDS` are non-empty (`src/am_server/app.py` lifespan).

## Environment variables

```dotenv
# Shared graph (default for all workspaces)
NEO4J_URI=bolt://...
NEO4J_USER=neo4j
NEO4J_PASSWORD=...

# Operator private graph (only for listed workspace ids)
NEO4J_OPERATOR_URI=bolt://127.0.0.1:7667
# Optional; default to NEO4J_USER / NEO4J_PASSWORD when unset:
# NEO4J_OPERATOR_USER=
# NEO4J_OPERATOR_PASSWORD=

# Comma or whitespace separated — your OpenClaw workspace_id only:
AM_OPERATOR_WORKSPACE_IDS=your-workspace-id-here
```

## Not implemented

- Arbitrary per-tenant databases for every customer (only the operator list).
- Non-OpenClaw routes (MCP tools, other REST) still use the default singleton
  pipelines unless separately extended.

## Operational note

Use the **same** `https://backend.agentmemorylabs.com` in OpenClaw for both
you and new users; the server routes by **workspace_id** on each request.

## Agent handoff (persistent memory for future sessions)

Use this section as the durable summary when resuming work on hosted OpenClaw
and Neo4j routing.

- **Policy:** Two physical Bolt graphs only — shared (`NEO4J_URI`) and optional
  operator private (`NEO4J_OPERATOR_URI`). Only workspace IDs in
  `AM_OPERATOR_WORKSPACE_IDS` hit the operator graph; everyone else uses the
  shared graph. This is **not** arbitrary per-customer databases.
- **Code map:** `src/am_server/neo4j_routing.py` (env + `use_operator_neo4j`);
  `src/am_server/dependencies.py` (`get_operator_*`, `pipelines_for_openclaw_workspace`,
  `graph_for_openclaw_workspace`); `src/am_server/routes/openclaw.py` (ingest,
  search, read use those resolvers); `src/am_server/app.py` lifespan warms
  operator pipelines when operator URI and allowlist are both set.
- **Deploy examples:** `deploy/systemd/am-server.env.example` and
  `.env.production.example` document Bolt **7667** on the live VM and optional
  operator env block.
- **Limitation:** Non-OpenClaw routes (e.g. other REST, MCP tools) still use
  the default singleton pipelines unless extended later.
- **Verification:** `python -m pytest tests/test_neo4j_routing.py`
