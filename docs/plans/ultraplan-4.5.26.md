# Ultraplan 4.5.26: Multi-Repo Collision Fix via repo_id Partitioning

## Context

**Immediate motivation:** Worktree paths (`.kilo/worktrees/...`, `.claude/worktrees/...`) are polluting search results right now — confirmed by the Obsidian doc (4 copies of 2 functions in top-8 results). This is a multi-repo collision problem that exists in production today.

**Architecture decision:** Multiple databases are unavailable on this Aura instance (only neo4j + system). Shared database with repo_id partitioning is the only viable path — which also matches the git graph's existing pattern in `git_graph.py`.

## What's Already Done

Tier 1 graph enrichment is implemented — `semantic_search()` already returns `file_path`, `calls_out`, `called_by`, `methods`, `file_imports`, `siblings` (see `graph.py:1110-1141`). The plan does NOT need to re-implement this.

## Hardened Completion Bar

- [x] `repo_id` on all code/memory identities written by ingestion and memory CRUD
- [x] Composite uniqueness constraints replacing global ones
- [x] Query-time filtering by `repo_id` in code search and memory search
- [x] `search_memory_nodes()` incoming relations
- [x] Application-level reranking in `semantic_search()`
- [x] All ingestion passes scoped when `repo_root` / `repo_id` is active
- [x] All code-domain reads scoped when `repo_root` / `repo_id` is active
- [x] Memory read/search/backfill paths scoped when `repo_root` / `repo_id` is active
- [x] CLI and MCP both propagate repo context consistently
- [ ] GDS/Leiden path (future work only; not part of migration completion)

---

## Current vs Target Architecture

| Aspect | Current | Target |
|--------|---------|--------|
| **File** | `{path}` ← global unique | `{repo_id, path}` ← composite unique |
| **Function** | `{sig}` ← global unique | `{repo_id, sig}` |
| **Class** | `{qual}` ← global unique | `{repo_id, qual}` |
| **Memory** | `{name}` ← global unique | `{repo_id, name}` |
| **Chunk** | (no id) | (filter via `entity.repo_id`) |
| **init_graph()** | no `repo_root` passed | `repo_root=repo_root` passed |
| **Schema** | `self.repo_id = None` | `self.repo_id = str(repo_root.resolve())` |
| **semantic_search()** | ANN top-k (no filter) | ANN top-(limit×3) → WHERE repo_id → rerank → return top-limit |
| **search_memory_nodes()** | outgoing relations only | outgoing + incoming relations; filter by repo_id |

---

## Critical Files

| File | Purpose |
|------|---------|
| `src/codememory/ingestion/graph.py` | All schema, ingestion, and search changes |
| `src/codememory/server/app.py` | `init_graph()` at line 136 (pass `repo_root`) |
| `src/codememory/ingestion/git_graph.py` | Reference model for `repo_id = str(repo_root)` |

---

## Step-by-Step Implementation

### Step 1 — Wire repo_id into KnowledgeGraphBuilder

**File:** `graph.py:128-190` (`__init__`)

In `__init__`, after `self.repo_root = repo_root`, add:

```python
self.repo_id: Optional[str] = str(repo_root.resolve()) if repo_root else None
```

This mirrors the git graph pattern exactly (`git_graph.py:98`).

---

### Step 2 — Pass repo_root from init_graph()

**File:** `app.py:171-176` (`init_graph`)

Change the `KnowledgeGraphBuilder` instantiation to:

```python
graph = KnowledgeGraphBuilder(
    uri=uri,
    user=user,
    password=password,
    openai_key=openai_key,
    repo_root=repo_root,   # ← add this
)
```

`repo_root` is already resolved by lines 144-149 in the same function.

---

### Step 3 — Schema: composite constraints + Repository anchor

**File:** `graph.py:275-309` (`setup_database`)

Add a migration sub-step that:

- Drops old global constraints (with `IF EXISTS`)
- Creates composite ones (with `IF NOT EXISTS`)

**New constraint set** (replace the current 3 in queries):

```cypher
DROP CONSTRAINT file_path_unique IF EXISTS
DROP CONSTRAINT function_sig_unique IF EXISTS
DROP CONSTRAINT class_name_unique IF EXISTS

CREATE CONSTRAINT file_repo_path_unique IF NOT EXISTS
  FOR (f:File) REQUIRE (f.repo_id, f.path) IS UNIQUE

CREATE CONSTRAINT function_repo_sig_unique IF NOT EXISTS
  FOR (fn:Function) REQUIRE (fn.repo_id, fn.signature) IS UNIQUE

CREATE CONSTRAINT class_repo_qual_unique IF NOT EXISTS
  FOR (c:Class) REQUIRE (c.repo_id, c.qualified_name) IS UNIQUE

CREATE CONSTRAINT repo_id_unique IF NOT EXISTS
  FOR (r:Repository) REQUIRE r.repo_id IS UNIQUE
```

Also add a Repository anchor node upsert at the end of `setup_database()`:

```cypher
MERGE (r:Repository {repo_id: $repo_id})
SET r.root_path = $root_path, r.updated_at = datetime()
```

Only run this if `self.repo_id` is set.

> **Note:** The composite constraints won't prevent MERGE from working — they just enforce uniqueness at the `(repo_id, property)` level. Existing nodes without `repo_id` must be backfilled before dropping the old constraints. Add a `_backfill_repo_id()` method (see Step 4).

---

### Step 4 — Backfill existing nodes + migration method

**File:** `graph.py` — new method `migrate_repo_id()` on `KnowledgeGraphBuilder`

Called automatically from `setup_database()` when `self.repo_id` is not `None`, before dropping old constraints:

```python
def _backfill_repo_id(self, session):
    """Set repo_id on all File/Function/Class/Memory nodes that lack it."""
    if not self.repo_id:
        return
    for label in ("File", "Function", "Class", "Memory"):
        session.run(
            f"MATCH (n:{label}) WHERE n.repo_id IS NULL SET n.repo_id = $repo_id",
            repo_id=self.repo_id,
        )
```

**Call order inside `setup_database()`:**

1. `_backfill_repo_id(session)`
2. Drop old constraints
3. Create composite constraints
4. Upsert Repository node

---

### Step 5 — Ingestion passes: stamp repo_id on new nodes

**File:** `graph.py`

All `MERGE` statements that create `File`, `Function`, and `Class` nodes need `repo_id` added to both the identity key and the `SET` clause.

**Pass 1** (`pass_1_structure_scan`, ~line 451):

```cypher
-- Change identity from path alone to (repo_id, path)
MERGE (f:File {repo_id: $repo_id, path: $path})
SET f.name = $name, f.ohash = $ohash, f.last_updated = datetime()
```

Also update the lookup `MATCH (f:File {path: $path})` at line 443 and `_delete_file_subgraph` at line 242 to include `repo_id` in the match if `self.repo_id` is set.

**Pass 2** (`pass_2_entity_definition`, ~line 563):

```cypher
-- Class:
MERGE (c:Class {repo_id: $repo_id, qualified_name: $sig})
SET c.name = $name, c.code = $code

-- Function:
MERGE (fn:Function {repo_id: $repo_id, signature: $sig})
SET fn.name = $name, fn.code = $code
```

**Pass 3** (`pass_3_imports`, check file lines ~817+):

Update `MATCH (f:File {path: ...})` lookups to include `repo_id` when available.

**Pass 4** (`pass_4_call_graph`):

Same — update `MATCH (fn:Function {signature: ...})` to scope by `repo_id`.

**Chunk nodes:** No change needed — Chunk identity uses `randomUUID()`. Filtering goes via `entity.repo_id` after the `[:DESCRIBES]` hop.

---

### Step 6 — Memory schema: composite constraint

**File:** `graph.py:311-340` (`setup_memory_schema`)

Replace:

```python
"CREATE CONSTRAINT memory_name_unique IF NOT EXISTS "
f"FOR (m:{self.MEMORY_LABEL}) REQUIRE m.name IS UNIQUE"
```

With:

```python
"DROP CONSTRAINT memory_name_unique IF EXISTS",
"CREATE CONSTRAINT memory_repo_name_unique IF NOT EXISTS "
f"FOR (m:{self.MEMORY_LABEL}) REQUIRE (m.repo_id, m.name) IS UNIQUE",
```

Also backfill Memory nodes the same way in `_backfill_repo_id`.

---

### Step 7 — create_memory_entities(): stamp repo_id

**File:** `graph.py:1366-1426`

Change the `MERGE` identity from `{name: $name}` to `{repo_id: $repo_id, name: $name}` and add `repo_id` to the `ON CREATE SET` block:

```cypher
MERGE (m:Memory {repo_id: $repo_id, name: $name})
ON CREATE SET
    m.repo_id = $repo_id,
    ...
```

The `repo_id` param will be `self.repo_id` (passed through `_execute_create()`).

Similar change needed in `delete_memory_entities()`, `create_memory_relations()`, `add_memory_observations()`, `delete_memory_observations()` — all `MATCH on Memory.name` need to scope by `repo_id`.

---

### Step 8 — semantic_search(): repo filtering + over-fetch

**File:** `graph.py:1040` — add `repo_id: Optional[str] = None` parameter

```python
def semantic_search(self, query: str, limit: int = 5, repo_id: Optional[str] = None) -> List[Dict]:
    active_repo = repo_id or self.repo_id
    overfetch = limit * 3  # safe for ≤5 repos; scale up for more
```

**Vector path** — insert post-yield WHERE after `YIELD node as chunk, score`:

```cypher
CALL db.index.vector.queryNodes('code_embeddings', $overfetch, $vec)
YIELD node as chunk, score
MATCH (chunk)-[:DESCRIBES]->(entity)
WHERE entity.repo_id = $repo_id    -- post-yield filter (confirmed working on this Aura)
...existing graph expansions...
ORDER BY score DESC
LIMIT $limit
```

When `active_repo` is `None`, omit the `WHERE` clause entirely (backward-compatible for single-repo installs without `repo_id` stamped yet).

**Fulltext fallback** — same pattern: add `WHERE node.repo_id = $repo_id` after the fulltext `YIELD` if `active_repo` is set.

---

### Step 9 — search_memory_nodes(): repo filtering + incoming relations

**File:** `graph.py:1695`

Add `repo_id: Optional[str] = None` parameter.

Current query only fetches outgoing:

```cypher
OPTIONAL MATCH (node:Memory)-[r]->(target:Memory)
...
collect(outgoing) as outgoing_relations
```

Add incoming:

```cypher
OPTIONAL MATCH (node:Memory)-[r_out]->(target:Memory)
OPTIONAL MATCH (source:Memory)-[r_in]->(node:Memory)
...
collect(DISTINCT CASE WHEN target IS NULL THEN NULL ELSE {target: target.name, relation_type: type(r_out)} END) as outgoing_relations,
collect(DISTINCT CASE WHEN source IS NULL THEN NULL ELSE {source: source.name, relation_type: type(r_in)} END) as incoming_relations
```

Add repo filter: `WHERE node.repo_id = $repo_id` in the subquery (or as a post-filter in Python) when `active_repo` is set.

Update return value to include `incoming_relations` in the row dict.

Update `_format_memory_entity_results()` in `app.py:360` to display incoming relations.

---

### Step 10 — Application-level reranking

**File:** `graph.py` — new private method `_rerank_results()`

```python
def _rerank_results(self, results: List[Dict], limit: int) -> List[Dict]:
    """
    Structural reranking after repo-filtered vector retrieval.
    Structural bonuses from graph connectivity (CALLS properties are empty,
    so use edge existence only).
    """
    for r in results:
        structural = 0.0
        if r.get("calls_out"):
            structural += 0.05  # has outgoing calls
        if r.get("called_by"):
            structural += 0.05  # is called by others (more central)
        if r.get("methods"):
            structural += 0.03  # is a class with methods
        r["final_score"] = r.get("score", 0.0) * 0.9 + structural
    results.sort(key=lambda x: x["final_score"], reverse=True)
    return results[:limit]
```

Call `_rerank_results()` at the end of `_execute_search()` in `semantic_search()`, after the repo-filtered results come back and before returning.

Add `final_score` to the formatted output in `tools.py` if it differs meaningfully from `score`.

---

### Step 11 — GDS/Leiden: what to do when Aura creds are available

**No code changes now.** Document in a code comment in `graph.py` near `semantic_search()`:

#### To unlock when `gds.graph.project` is available:

- **PageRank reranking** — replace the structural bonus heuristic in `_rerank_results()` with a GDS-computed pagerank property on Function/Class nodes. Run `gds.pageRank.write()` periodically (or post-ingestion) per repo, write to `entity.pagerank`. Then: `final_score = 0.7*vector + 0.2*pagerank + 0.1*structural`.

- **Leiden clustering** — run `gds.leiden.write()` per repo, write `community_id` to nodes. Use community membership as an additional grouping/filtering signal in search results (e.g., "found 3 results from cluster auth, 2 from cluster api").

- **Activation:** `gds.aura.api.credentials(clientId, clientSecret)` — one-time Aura console config step, then `gds.graph.project` becomes available.

#### Available now without GDS:

- `vector.similarity.cosine()` — pairwise reranking in Cypher
- BFS expansion: manually hop 1-2 levels on `CALLS` from seed results, collect neighbors as additional context

---

## Migration Notes

The constraint change is the trickiest part. **Execution order matters:**

1. `_backfill_repo_id()` — set `repo_id` on all existing nodes
2. DROP old constraints — free the global uniqueness
3. CREATE composite ones — new identity model
4. UPSERT Repository node — anchor

This is safe for a single-repo installation: all existing nodes get the same `repo_id` and the composite uniqueness is equivalent to the old global uniqueness for that one repo.

For the watcher (`watcher.py`): no direct changes needed — it calls `run_pipeline()` which calls the passes that will now stamp `repo_id`.

---

## Verification

- **Worktree pollution fix:** run `semantic_search("metrics.py websocket")`, confirm results show only `realtime_api/websocket/metrics.py` paths, not `.kilo/worktrees/...` paths
- **Composite constraints:** `SHOW CONSTRAINTS` in Neo4j Browser — should show `(repo_id, path)` pair, no global `f.path` alone
- **Incoming memory relations:** run `search_memory_nodes("...")` on a node with known incoming edges — confirm `incoming_relations` field is populated
- **Reranking:** confirm `final_score` field appears in results and callable functions (with `called_by`) score higher than isolated utilities with the same vector score
- **Backward compat:** single-repo install where `CODEMEMORY_REPO` is not set should still work — `repo_id=None` path skips `WHERE` filter

---
## Completion Status

Hardened on: 2026-04-07

- Multi-repo `repo_id` migration is considered complete only when:
  - ingestion passes are repo-scoped
  - code-domain reads are repo-scoped
  - memory CRUD/search/read/backfill paths are repo-scoped
  - both CLI and MCP propagate repo context consistently
- GDS/Leiden remains future work and is not required for repo isolation completion.
