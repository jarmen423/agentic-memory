# Phase 7: Temporal Schema + Claim Extraction + Research Scheduling — Research

**Researched:** 2026-03-25
**Domain:** Neo4j temporal relationships, Groq claim extraction, APScheduler 3.x
**Confidence:** HIGH (standard stack verified against official docs; code patterns verified against codebase)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. Temporal fields on relationships: `valid_from` (required, ISO string), `valid_to` (optional, null = still valid), `confidence` (float 0-1, default 1.0), `support_count` (int, default 1), `contradiction_count` (int, default 0)
2. Backfill strategy: Existing relationships get `valid_from = ingested_at` from the source Memory node, `confidence = 0.5`, `valid_to = null`. Runs as a separate `migrate-temporal` command, not at init time.
3. Claim extraction format: `{subject: str, predicate: str, object: str, valid_from: str|None, valid_to: str|None, confidence: float}` — subject/object are entity names resolved to Entity nodes. Produces Entity→Entity relationships.
4. Predicate catalog: Closed set — `KNOWS`, `WORKS_AT`, `RESEARCHED`, `REFERENCES`, `USES`, `LEADS`, `PART_OF`, `LOCATED_IN`, `CREATED_BY`, `CONTRADICTS`. "Other" maps to `REFERENCES`. Extensible via config.
5. Two separate Groq calls per document: NER call (existing) + claims call (new). Independent failures.
6. Schedule storage: APScheduler 3.x with SQLite job store at `~/.config/agentic-memory/schedules.db`. Schedule also stored as `:Schedule` node in Neo4j.
7. LLM variable fill: Same Groq model. Prompt includes template, variable names, last 10 `RESEARCHED` edges, instruction to avoid covered topics.
8. `as_of` parameter: All search MCP tools accept `as_of: str | None`. Filter: `valid_from <= as_of AND (valid_to IS NULL OR valid_to >= as_of)`.

### Claude's Discretion

- Exact Cypher for backfill migration command
- `ClaimExtractionService` prompt wording (constrain to catalog, return `{"claims": [...]}`)
- Use `BackgroundScheduler` (sync), not `AsyncIOScheduler`
- Cost cap enforcement details
- Unit test fixtures

### Deferred Ideas (OUT OF SCOPE)

- SpacetimeDB integration (Phase 8)
- Temporal PPR retrieval (Phase 9)
- Cross-module temporal ranking (Phase 10)
- Confidence decay over time (Phase 9)
- Automated contradiction resolution (Phase 8/9)
- Open predicate catalog / normalization
- Entity deduplication ("React" vs "ReactJS")
</user_constraints>

---

## Summary

Phase 7 adds temporal validity intervals to all Neo4j relationships, introduces SPO claim extraction
as a secondary pass after existing NER, and delivers research scheduling via APScheduler 3.x with
a SQLite job store.

The core insight is that Neo4j MERGE on relationships matches on ALL properties in the pattern —
so temporal fields (`valid_from`, etc.) must NOT be in the MERGE pattern itself, only in ON CREATE /
ON MATCH SET clauses. This is the single most important implementation detail for the temporal
schema work.

Groq with `json_object` mode (best-effort schema) is the correct choice for claim extraction, as
the codebase already uses `llama-3.3-70b-versatile` with this mode and it handles the required
predicate-constrained extraction reliably. Strict `json_schema` mode is available on Kimi K2 and
Llama 4 Scout but changing models would break consistency with Phase 1–4.

APScheduler 3.11.2 (stable, December 2025) is the correct pinned version. Version 4.0 is still
in alpha (`4.0.0a6`, April 2025) with backward-incompatible changes and is explicitly unsuitable
for production use.

**Primary recommendation:** Extend `write_relationship()` into `write_temporal_relationship()`,
implement `ClaimExtractionService` mirroring `EntityExtractionService`, and use
`BackgroundScheduler` with `SQLAlchemyJobStore` for persistent cron scheduling.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `neo4j` | already in deps | Temporal MERGE patterns | All other pipelines use it |
| `groq` | `>=0.10.0` (already in deps) | Claim extraction LLM calls | Existing NER service uses same client |
| `apscheduler` | `>=3.10.0,<4.0` | Cron job scheduling with persistence | v4 is alpha; v3 is stable and well-documented |
| `sqlalchemy` | `>=2.0.0` | APScheduler SQLite job store backend | Required by `SQLAlchemyJobStore`; SQLite via `sqlite:///path` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `httpx` | `>=0.27.0` (already in deps) | Brave Search HTTP calls in scheduler | Already in deps for Phase 2 `brave_search` tool |
| `uuid` | stdlib | Schedule node `schedule_id` generation | No extra dep needed |
| `pathlib` | stdlib | Schedules DB path expansion | `Path("~/.config/agentic-memory/schedules.db").expanduser()` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| APScheduler 3.x | APScheduler 4.x | v4 is alpha; API unstable; do not use in production |
| APScheduler 3.x | Celery | Celery needs a broker (Redis/RabbitMQ); massively over-engineered for single-process scheduling |
| APScheduler 3.x | rq-scheduler | Requires Redis; same overkill concern |
| `json_object` mode | `json_schema` strict mode | Strict mode requires changing model to Kimi K2 or Llama 4 Scout; breaks consistency |

**Installation (new deps only):**
```bash
pip install "apscheduler>=3.10.0,<4.0" "sqlalchemy>=2.0.0"
```

**Verified versions (npm view equivalent for PyPI):**
- APScheduler latest stable: `3.11.2` (released 2025-12-22) — confirmed via PyPI
- APScheduler v4 latest: `4.0.0a6` (alpha, 2025-04-27) — do NOT use
- SQLAlchemy: `2.0.x` series stable — required for APScheduler's SQLite job store

---

## Architecture Patterns

### Recommended Project Structure

```
src/codememory/
├── core/
│   ├── graph_writer.py      # + 3 temporal methods
│   ├── entity_extraction.py # unchanged
│   ├── claim_extraction.py  # NEW: ClaimExtractionService
│   └── scheduler.py         # NEW: ResearchScheduler
├── web/
│   └── pipeline.py          # + claim extraction pass + temporal fields
├── chat/
│   └── pipeline.py          # + temporal fields on relationship writes
├── ingestion/
│   └── graph.py             # unchanged (backfill handles temporal migration)
├── server/
│   └── tools.py             # + 3 schedule MCP tools + as_of param
└── cli.py                   # + web-schedule, web-run-research subparsers
```

---

### Pattern 1: Temporal MERGE on Relationships (CRITICAL)

**What:** MERGE on a Neo4j relationship matches the ENTIRE pattern including properties. If any
property in the MERGE pattern differs, a NEW relationship is created instead of matching the
existing one. Therefore, temporal metadata fields (`valid_from`, etc.) must NEVER appear in the
MERGE pattern — only in ON CREATE / ON MATCH SET.

**When to use:** Every relationship write in Phase 7 and beyond.

**Example — write_temporal_relationship():**
```python
# Source: Neo4j Cypher docs https://neo4j.com/docs/cypher-manual/current/clauses/merge/
cypher = (
    "MATCH (m {source_key: $source_key, content_hash: $content_hash})\n"
    "MATCH (e {name: $entity_name, type: $entity_type})\n"
    f"MERGE (m)-[r:{rel_type}]->(e)\n"
    "ON CREATE SET r.valid_from = $valid_from,\n"
    "              r.valid_to = $valid_to,\n"
    "              r.confidence = $confidence,\n"
    "              r.support_count = $support_count,\n"
    "              r.contradiction_count = $contradiction_count\n"
    "ON MATCH SET  r.support_count = r.support_count + 1,\n"
    "              r.confidence = CASE WHEN $confidence > r.confidence\n"
    "                                  THEN $confidence\n"
    "                                  ELSE r.confidence END"
)
```

**Why ON MATCH increments support_count:** Re-ingesting the same document should strengthen the
relationship (more evidence), not reset it. Confidence takes the maximum of existing and new.

---

### Pattern 2: ClaimExtractionService — mirrors EntityExtractionService

**What:** New service at `core/claim_extraction.py` with same constructor signature as
`EntityExtractionService`. Uses Groq `json_object` mode with predicate catalog in system prompt.

**Example:**
```python
CLAIM_EXTRACTION_PROMPT = """\
Extract factual claims from the text as Subject-Predicate-Object triples.
Return a JSON object with key "claims" containing a list of objects, each with:
  "subject": entity name (person, project, technology, business, or concept)
  "predicate": MUST be one of: {predicates}
  "object": entity name (same types as subject)
  "valid_from": ISO-8601 date if claim has a known start time, else null
  "valid_to": ISO-8601 date if claim is no longer valid, else null
  "confidence": float 0.0-1.0 for your confidence this claim is true

Use REFERENCES as catch-all if no other predicate fits.
Only extract claims clearly present in the text.
If no claims found, return {{"claims": []}}."""

class ClaimExtractionService:
    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        predicates: list[str] | None = None,
    ) -> None:
        self._client = Groq(api_key=api_key)
        self.model = model
        self.predicates = predicates or [
            "KNOWS", "WORKS_AT", "RESEARCHED", "REFERENCES",
            "USES", "LEADS", "PART_OF", "LOCATED_IN", "CREATED_BY", "CONTRADICTS",
        ]

    def extract(self, document_text: str) -> list[dict[str, Any]]:
        # Same pattern as EntityExtractionService: truncate to 8000 chars,
        # json_object mode, temperature=0.0, filter to valid predicates
        ...
```

---

### Pattern 3: APScheduler 3.x with SQLite Job Store

**What:** `BackgroundScheduler` (sync) runs in a background thread within the same `am-server`
process. Jobs persist across restarts via SQLite.

**Example:**
```python
# Source: APScheduler 3.x docs https://apscheduler.readthedocs.io/en/3.x/userguide.html
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from pathlib import Path

SCHEDULES_DB = Path("~/.config/agentic-memory/schedules.db").expanduser()
SCHEDULES_DB.parent.mkdir(parents=True, exist_ok=True)

jobstores = {
    "default": SQLAlchemyJobStore(url=f"sqlite:///{SCHEDULES_DB}")
}
scheduler = BackgroundScheduler(jobstores=jobstores, daemon=True)
scheduler.start()

# Add a cron job
scheduler.add_job(
    func=run_research_job,         # sync callable
    trigger="cron",
    id=schedule_id,                # stable UUID — safe to re-add on restart
    replace_existing=True,         # idempotent restart handling
    hour=9, minute=0, day_of_week="mon",  # or pass cron_expr via CronTrigger
    kwargs={"schedule_id": schedule_id, "project_id": project_id},
)
```

**Async call from sync scheduler:** APScheduler runs jobs in a thread pool. To call an async
pipeline method from the sync job function, use `asyncio.run()` in the job function:
```python
def run_research_job(schedule_id: str, project_id: str) -> None:
    """Sync wrapper — APScheduler calls this in a thread."""
    import asyncio
    asyncio.run(_async_run_research(schedule_id, project_id))
```

**CronTrigger from expression string:** If the cron expr comes from user input as a string
(`"0 9 * * 1"`), parse it with:
```python
from apscheduler.triggers.cron import CronTrigger
trigger = CronTrigger.from_crontab("0 9 * * 1")
```

---

### Pattern 4: Backfill Cypher for Existing Relationships

**What:** One-time migration that adds `valid_from` and other temporal fields to existing
relationships that pre-date Phase 7.

**Example — for :ABOUT and :MENTIONS (generalizes to other types):**
```cypher
-- Backfill :ABOUT relationships using Memory node's ingested_at
MATCH (m)-[r:ABOUT]->(e)
WHERE r.valid_from IS NULL
MATCH (m)
SET r.valid_from = m.ingested_at,
    r.valid_to = null,
    r.confidence = 0.5,
    r.support_count = 1,
    r.contradiction_count = 0
```

**Important:** The `WHERE r.valid_from IS NULL` guard makes this idempotent — safe to re-run.
Run equivalent statements for every relationship type: `ABOUT`, `MENTIONS`, `BELONGS_TO`,
`HAS_CHUNK`, `PART_OF`, `HAS_TURN`, `CITES`, and the code module relationships
(`DEFINES`, `HAS_METHOD`, `DESCRIBES`, `IMPORTS`, `CALLS`, `PART_OF_PR`).

For code module relationships the Memory node is the ancestor — use pattern matching to reach it:
```cypher
-- Code module: DEFINES relationship (CodeFile)-[:DEFINES]->(CodeClass)
-- No direct Memory node — use source node's own properties if available
-- or set valid_from to a fixed "schema migration" timestamp
MATCH ()-[r:DEFINES]->()
WHERE r.valid_from IS NULL
SET r.valid_from = "2026-03-25T00:00:00+00:00",
    r.confidence = 0.5,
    r.support_count = 1,
    r.contradiction_count = 0
```

---

### Pattern 5: `as_of` Filter in MCP Tool Cypher

**What:** Add temporal filter to vector search queries when `as_of` is provided.

**Example fragment for `search_conversations`:**
```python
# When as_of is provided, filter the ABOUT/MENTIONS relationships in post-retrieval graph traversal
# For pure vector search, as_of filters what gets returned after the kNN step:

def _apply_temporal_filter(results: list[dict], as_of: str | None) -> list[dict]:
    """Post-filter vector search results to those with valid relationships at as_of."""
    if as_of is None:
        return results
    # Filter: only return nodes that have at least one valid_from <= as_of
    # relationship (proxy: check the node's ingested_at or the ABOUT rel)
    return [r for r in results if r.get("ingested_at", "") <= as_of]
```

Note: Full temporal filtering requires a graph traversal after vector search. For Phase 7, a
simpler heuristic (filter by node `ingested_at`) is acceptable. The full relationship-level
temporal filter (`r.valid_from <= as_of AND (r.valid_to IS NULL OR r.valid_to >= as_of)`) is
more correct but requires a hybrid query (vector kNN + graph filter), which is Phase 9 scope.

**Phase 7 acceptable approach:** Apply `as_of` as a node-level filter on `ingested_at` in the
initial vector search. Document this limitation in code comments.

---

### Anti-Patterns to Avoid

- **Including temporal fields in MERGE relationship pattern** — creates duplicate relationships
  instead of matching existing ones. Always MERGE on relationship type + endpoint identity only.
- **Using APScheduler v4** — alpha, API unstable, not for production.
- **Sharing SQLite APScheduler DB across multiple processes** — single-process only.
- **Running `asyncio.run()` inside an already-running event loop** — use `nest_asyncio` or
  restructure to sync if calling from APScheduler job. The safest pattern: make the job function
  fully synchronous and instantiate a fresh event loop with `asyncio.run()`.
- **Claim extraction per-chunk** — per-document is the right granularity for cross-chunk entity
  resolution (same as NER). Per-chunk would miss claims that span chunk boundaries.
- **Truncating claim prompt input below 8000 chars** — use the same 8000-char budget guard as
  NER. Longer inputs can exceed Groq context efficiently.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Persistent job scheduling | Custom SQLite cron table + polling loop | `apscheduler[sqlalchemy]` | Handles missed runs, timezone-aware, SIGTERM recovery |
| Cron expression parsing | Custom parser | `apscheduler.triggers.cron.CronTrigger.from_crontab()` | Standard syntax, already validated |
| Async-in-sync bridging | `loop = asyncio.get_event_loop(); loop.run_until_complete()` | `asyncio.run()` | `run_until_complete` on existing loop causes RuntimeError in Python 3.10+ |
| Temporal filter queries | Custom date comparison logic | Neo4j `WHERE r.valid_from <= $as_of` Cypher | Cypher handles ISO-8601 string comparison natively when strings are in correct format |

**Key insight:** APScheduler v3 + SQLite is a ~10-line setup for persistent cron. The only
complexity is bridging its sync job execution into async pipeline code — solved by `asyncio.run()`
in the job wrapper function.

---

## R1: GraphWriter Temporal Relationship Methods — Findings

### All Relationship Types Requiring Temporal Fields

**Written via `GraphWriter.write_relationship()` (ABOUT, MENTIONS, BELONGS_TO):**
- `web/pipeline.py` lines 225–232 — chunk entity wiring
- `web/pipeline.py` lines 340–348 — finding entity wiring
- `chat/pipeline.py` lines 203–212 — turn entity wiring

**Written via dedicated GraphWriter methods (need temporal params added):**
- `write_has_chunk_relationship()` → `:HAS_CHUNK` property `order` stays, add temporal fields
- `write_part_of_relationship()` → `:PART_OF` no properties today, add temporal fields
- `write_cites_relationship()` → `:CITES` has `rel_props` dict, add temporal fields to it
- `write_has_turn_relationship()` → `:HAS_TURN` property `order` stays, add temporal fields
- `write_part_of_turn_relationship()` → no properties today, add temporal fields

**Code module relationships (in `ingestion/graph.py`, raw Cypher):**
- `:DEFINES`, `:HAS_METHOD`, `:DESCRIBES`, `:IMPORTS`, `:CALLS`, `:PART_OF_PR`
- These are NOT routed through `GraphWriter` — backfill migration handles them only

### Critical MERGE Pattern Detail

Verified against [Neo4j Cypher docs](https://neo4j.com/docs/cypher-manual/current/clauses/merge/):
MERGE on a relationship checks the ENTIRE pattern including any properties specified inline.
A relationship MERGE with properties in the pattern will create a new relationship if those
properties don't exactly match — even if a relationship of that type already exists between
the same nodes.

**Correct pattern:** MERGE on type + endpoints only; SET all properties in ON CREATE / ON MATCH.
**Wrong pattern:** `MERGE (a)-[r:TYPE {valid_from: $vf}]->(b)` — creates duplicate on re-ingest.

Confidence: HIGH — verified against official Neo4j documentation.

---

## R2: Groq Claim Extraction — Findings

### JSON Schema Design

**Recommended response schema for claim extraction:**
```json
{
  "claims": [
    {
      "subject": "Alice",
      "predicate": "WORKS_AT",
      "object": "Acme Corp",
      "valid_from": "2024-01-01T00:00:00Z",
      "valid_to": null,
      "confidence": 0.95
    }
  ]
}
```

Groq `json_object` mode (best-effort) with `{"type": "json_object"}` response format. The
schema description lives in the system prompt. This is consistent with `EntityExtractionService`
which uses the same pattern.

### Claim Extraction Quality Limits

Based on Groq documentation and the existing NER pattern (8000-char truncation):
- Per-document extraction on texts up to 8000 chars produces reliable results with
  `llama-3.3-70b-versatile` at temperature=0.0
- Expected claim count per document: 2–15 claims (dependent on text richness)
- Quality degrades for texts >8000 chars — budget guard preserved from NER

**Strict mode option:** Groq now supports `json_schema` strict mode on `moonshotai/kimi-k2-instruct`
and Llama 4 Scout. This would provide stronger guarantees but requires model switch.
Decision: stay with `llama-3.3-70b-versatile` + `json_object` for consistency.

Confidence: MEDIUM — based on Groq docs + existing NER pattern. Actual claim quality
should be validated with sample documents before deploying.

### Per-chunk vs Per-document

**Decision: per-document** (locked in CONTEXT.md). Reasoning:
- Cross-chunk claims (e.g., a subject named in paragraph 1, predicate in paragraph 3) require
  the full document context to resolve
- Same reasoning as NER: one call per document
- Per-chunk would be cheaper on large documents but would miss cross-boundary claims

---

## R3: APScheduler with SQLite — Findings

### Correct APScheduler v3 Setup

Version: `3.11.2` (stable, December 2025). [PyPI](https://pypi.org/project/APScheduler/)
Version 4 (`4.0.0a6`, April 2025) is alpha — do NOT use in production.

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger

db_path = Path("~/.config/agentic-memory/schedules.db").expanduser()
db_path.parent.mkdir(parents=True, exist_ok=True)

jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{db_path}")}
scheduler = BackgroundScheduler(jobstores=jobstores, daemon=True)
scheduler.start()
```

**Note:** `daemon=True` ensures the scheduler thread doesn't block server shutdown.

### Cron Job with Async Function

APScheduler v3 `BackgroundScheduler` runs jobs synchronously in a thread pool. To call an
async pipeline method:

```python
def _sync_research_job(schedule_id: str, project_id: str) -> None:
    """APScheduler job wrapper — sync entry point for async pipeline call."""
    import asyncio
    # asyncio.run() creates a NEW event loop — safe from thread pool context
    asyncio.run(_async_research_run(schedule_id, project_id))

scheduler.add_job(
    func=_sync_research_job,
    trigger=CronTrigger.from_crontab("0 9 * * 1"),
    id=schedule_id,
    replace_existing=True,       # idempotent across server restarts
    kwargs={"schedule_id": schedule_id, "project_id": project_id},
    misfire_grace_time=3600,     # allow up to 1h late execution after restart
)
```

**`replace_existing=True`** is critical for restart idempotency: on `am-server` restart, the
code that registers all schedules from Neo4j calls `add_job()` again with same ID — without
this flag, it raises `ConflictingIdError`.

### APScheduler v3 vs v4

| Feature | v3.11.2 (use this) | v4.0.0a6 (do not use) |
|---------|---------------------|------------------------|
| Status | Stable | Alpha, breaking changes |
| Job store API | `SQLAlchemyJobStore(url=...)` | Changed |
| Async support | `AsyncIOScheduler` separate class | Unified via AnyIO |
| Python requirement | `>=3.8` | Changed |
| Production use | Yes | No |

Confidence: HIGH — verified against [APScheduler docs](https://apscheduler.readthedocs.io/en/3.x/userguide.html) and PyPI.

---

## R4: Neo4j Schedule Node Schema — Findings

The proposed schema is correct and sufficient. One addition: `is_active` flag for soft-disable.

```
(:Schedule {
    schedule_id: str,        ← UUIDv4, primary key
    template: str,           ← "Research {topic} focusing on {angle}"
    variables: [str],        ← ["{topic}", "{angle}"] — list of variable placeholder names
    cron_expr: str,          ← standard cron e.g. "0 9 * * 1"
    project_id: str,
    created_at: str,         ← ISO-8601
    last_run_at: str | null, ← updated after each successful run
    run_count: int,          ← starts at 0, incremented per run
    is_active: bool          ← true by default; false = paused without deletion
})
```

**Cypher for MERGE on schedule_id:**
```cypher
MERGE (s:Schedule {schedule_id: $schedule_id})
ON CREATE SET s += $props
ON MATCH SET s.last_run_at = $last_run_at, s.run_count = s.run_count + 1
```

**Connection from Schedule to researched Memory nodes (optional for Phase 7):**
After each scheduler run, the pipeline already writes `RESEARCHED` edges (Entity → Entity via
claim extraction). The Schedule node does NOT need relationships to every Memory node it produces
— the `RESEARCHED` edges in the entity graph are the coverage tracker.

Confidence: HIGH — schema derived from APScheduler job store patterns and prior context decisions.

---

## R5: Backfill Migration — Findings

### Cypher Backfill for :ABOUT and :MENTIONS

```cypher
// Backfill :ABOUT relationships
// Source: neo4j.com Cypher docs — MATCH + conditional SET pattern
MATCH (m)-[r:ABOUT]->(e)
WHERE r.valid_from IS NULL
SET r.valid_from = COALESCE(m.ingested_at, "2026-01-01T00:00:00+00:00"),
    r.valid_to = null,
    r.confidence = 0.5,
    r.support_count = 1,
    r.contradiction_count = 0

// Backfill :MENTIONS relationships (same pattern)
MATCH (m)-[r:MENTIONS]->(e)
WHERE r.valid_from IS NULL
SET r.valid_from = COALESCE(m.ingested_at, "2026-01-01T00:00:00+00:00"),
    r.valid_to = null,
    r.confidence = 0.5,
    r.support_count = 1,
    r.contradiction_count = 0
```

`COALESCE` handles the edge case where `m.ingested_at` is null (shouldn't happen in practice
but defensive against corrupt nodes). The fallback timestamp is a reasonable "schema baseline."

### All Relationship Types Needing Backfill

Run equivalent statements for all of these:
```
:ABOUT, :MENTIONS, :BELONGS_TO              # entity wiring (all pipelines)
:HAS_CHUNK, :PART_OF (research)             # research structure
:HAS_TURN, :PART_OF (conversation)          # conversation structure
:CITES                                       # citation edges
:DEFINES, :HAS_METHOD, :DESCRIBES           # code structure
:IMPORTS, :CALLS, :PART_OF_PR               # code dependencies
```

For code module relationships, the source node does not have `ingested_at` — use a fixed
baseline timestamp representing the date the backfill migration is run.

### When to Run

**Locked: Separate `codememory migrate-temporal` command.** Not at init time.

The command should:
1. Run all backfill Cypher statements (one per relationship type)
2. Print counts of relationships updated per type
3. Be idempotent (safe to re-run due to `WHERE r.valid_from IS NULL` guard)
4. Complete in one transaction per relationship type (batch approach acceptable for performance)

Confidence: HIGH — Cypher pattern verified against Neo4j documentation. `COALESCE` is standard Cypher.

---

## Common Pitfalls

### Pitfall 1: MERGE on Relationship with Temporal Properties in Pattern

**What goes wrong:** Developer writes `MERGE (a)-[r:ABOUT {valid_from: $vf}]->(b)`. On second
ingest of the same document, a NEW `:ABOUT` relationship is created because the timestamp
differs from the first — now there are two parallel ABOUT edges between the same nodes.

**Why it happens:** Neo4j MERGE matches the entire pattern. Properties in the MERGE clause are
part of the identity check.

**How to avoid:** Never put temporal/metadata properties inside the MERGE relationship pattern.
MERGE only on relationship type + endpoint node identity. Add all properties in ON CREATE SET.

**Warning signs:** Multiple `:ABOUT` edges between the same node pair in the graph.

---

### Pitfall 2: APScheduler v4 Import Errors

**What goes wrong:** `pip install apscheduler` installs v4 (once it goes stable) or a newer
pre-release. v4 has a completely different API — `BackgroundScheduler` and `SQLAlchemyJobStore`
import paths changed.

**Why it happens:** No version pin.

**How to avoid:** Always pin `apscheduler>=3.10.0,<4.0` in `pyproject.toml`.

**Warning signs:** `ImportError: cannot import name 'BackgroundScheduler'` or
`ModuleNotFoundError: No module named 'apscheduler.schedulers.background'`.

---

### Pitfall 3: asyncio.run() Inside Running Event Loop

**What goes wrong:** MCP tool (async) calls `ResearchScheduler.run_now()` which internally
calls `asyncio.run()`. In Python 3.10+, calling `asyncio.run()` inside a running event loop
raises `RuntimeError: This event loop is already running`.

**Why it happens:** FastAPI/MCP servers run their own event loop. APScheduler job wrappers
use `asyncio.run()` which is safe in thread-pool context (new loop) but not from within
an already-running coroutine.

**How to avoid:** The MCP tool should call `ResearchScheduler.run_now()` as a sync method
via `loop.run_in_executor(None, scheduler.run_now, schedule_id)` — the same pattern used
in `am_server/routes/research.py` for pipeline calls. The scheduler method itself is sync
and creates its own loop internally.

**Warning signs:** `RuntimeError: This event loop is already running` in server logs.

---

### Pitfall 4: Backfill Missing Relationship Types

**What goes wrong:** Migration runs on `:ABOUT` and `:MENTIONS` but forgets `:HAS_CHUNK`,
`:PART_OF`, `:HAS_TURN`, `:CITES`, and code module relationships. These relationships have
`valid_from IS NULL` forever, breaking temporal queries after Phase 8/9.

**Why it happens:** Developer only thinks about the "main" entity relationships.

**How to avoid:** The migration command must have an exhaustive list of all relationship types.
Verify with: `MATCH ()-[r]->() WHERE r.valid_from IS NULL RETURN type(r), count(r)` after
running the migration to confirm zero un-backfilled relationships.

**Warning signs:** Post-migration `as_of` queries return no results for research/code content.

---

### Pitfall 5: Claim Extraction Writing Duplicate Entity Nodes

**What goes wrong:** `ClaimExtractionService` returns `{subject: "React", ...}` but entity NER
already created `:Entity:Technology {name: "React"}`. Claim extraction calls `upsert_entity()`
which should MERGE — but if the claim extraction produces `{subject: "ReactJS", ...}` (variant
spelling), a second Entity node is created.

**Why it happens:** LLMs produce variant spellings of the same entity.

**How to avoid:** For Phase 7, accept duplicates — entity deduplication is explicitly deferred
(per Phase 1 CONTEXT.md). Claim extraction uses `upsert_entity()` which MERGEs on `(name, type)` —
same exact name = same node. Document this known limitation.

**Warning signs:** Multiple Entity nodes with similar names in the graph.

---

### Pitfall 6: Schedule Jobs Lost on Server Restart Without `replace_existing=True`

**What goes wrong:** Server restarts, the startup code re-registers all Schedule nodes from
Neo4j into APScheduler. `add_job()` is called with the same `id`. Without `replace_existing=True`,
APScheduler raises `ConflictingIdError` because the job already exists in the SQLite store.

**Why it happens:** APScheduler persists jobs in SQLite across restarts — the job is still there
when the server starts back up.

**How to avoid:** Always pass `replace_existing=True` in `add_job()`.

**Warning signs:** `ConflictingIdError` in server startup logs; schedules stop firing.

---

## Code Examples

### write_temporal_relationship() — Full Implementation Pattern

```python
def write_temporal_relationship(
    self,
    source_key: str,
    content_hash: str,
    entity_name: str,
    entity_type: str,
    rel_type: str,
    valid_from: str,
    valid_to: str | None = None,
    confidence: float = 1.0,
    support_count: int = 1,
    contradiction_count: int = 0,
) -> None:
    """Write a temporal relationship from a Memory node to an Entity node.

    Uses MERGE on relationship type + endpoint identity only — temporal
    fields are NOT part of the MERGE pattern (would cause duplicate rels).
    ON MATCH increments support_count and takes max confidence.

    Args:
        source_key: source_key of the source Memory node.
        content_hash: content_hash of the source Memory node.
        entity_name: name of the target Entity node.
        entity_type: type of the target Entity node.
        rel_type: Relationship type (e.g. "ABOUT", "MENTIONS").
        valid_from: ISO-8601 start of validity interval.
        valid_to: ISO-8601 end of validity, or None if still valid.
        confidence: Probability claim is correct (0.0–1.0).
        support_count: Initial evidence count (default 1).
        contradiction_count: Initial contradiction count (default 0).
    """
    # Source: Neo4j Cypher MERGE docs
    # CRITICAL: temporal fields NOT in MERGE pattern — prevents duplicate relationships
    cypher = (
        "MATCH (m {source_key: $source_key, content_hash: $content_hash})\n"
        "MATCH (e {name: $entity_name, type: $entity_type})\n"
        f"MERGE (m)-[r:{rel_type}]->(e)\n"
        "ON CREATE SET r.valid_from = $valid_from,\n"
        "              r.valid_to = $valid_to,\n"
        "              r.confidence = $confidence,\n"
        "              r.support_count = $support_count,\n"
        "              r.contradiction_count = $contradiction_count\n"
        "ON MATCH SET  r.support_count = r.support_count + 1,\n"
        "              r.confidence = CASE WHEN $confidence > r.confidence\n"
        "                                  THEN $confidence\n"
        "                                  ELSE r.confidence END"
    )
    with self._conn.session() as session:
        session.run(
            cypher,
            source_key=source_key,
            content_hash=content_hash,
            entity_name=entity_name,
            entity_type=entity_type,
            valid_from=valid_from,
            valid_to=valid_to,
            confidence=confidence,
            support_count=support_count,
            contradiction_count=contradiction_count,
        )
```

### ClaimExtractionService — Groq json_object mode

```python
# Source: Groq docs https://console.groq.com/docs/structured-outputs
# Using json_object mode (best-effort) — consistent with EntityExtractionService

response = self._client.chat.completions.create(
    model=self.model,
    messages=[
        {"role": "system", "content": prompt},   # includes schema description + predicate list
        {"role": "user", "content": truncated_text},
    ],
    response_format={"type": "json_object"},
    temperature=0.0,
)

data: dict[str, Any] = json.loads(response.choices[0].message.content)

# Same fallback pattern as EntityExtractionService (Pitfall 4 from RESEARCH)
claims = data.get("claims")
if claims is None:
    claims = next((v for v in data.values() if isinstance(v, list)), [])

# Filter to valid predicates only
filtered = [
    c for c in claims
    if isinstance(c, dict) and c.get("predicate") in self.predicates
]
```

### ResearchScheduler — startup registration from Neo4j

```python
def _reload_schedules_from_neo4j(self) -> None:
    """On startup: re-register all active Schedule nodes into APScheduler.

    Called once at scheduler init to restore jobs from persistent Neo4j state.
    Uses replace_existing=True to handle restarts idempotently.
    """
    with self._conn.session() as session:
        result = session.run(
            "MATCH (s:Schedule {is_active: true}) RETURN s"
        )
        for record in result:
            node = record["s"]
            self._register_apscheduler_job(
                schedule_id=node["schedule_id"],
                cron_expr=node["cron_expr"],
                project_id=node["project_id"],
            )

def _register_apscheduler_job(
    self, schedule_id: str, cron_expr: str, project_id: str
) -> None:
    """Register (or re-register) a cron job in APScheduler."""
    trigger = CronTrigger.from_crontab(cron_expr)
    self._scheduler.add_job(
        func=self._sync_job_wrapper,
        trigger=trigger,
        id=schedule_id,
        replace_existing=True,     # safe across restarts
        misfire_grace_time=3600,   # 1h window for missed runs post-restart
        kwargs={"schedule_id": schedule_id, "project_id": project_id},
    )
```

---

## Project Constraints (from CLAUDE.md)

CLAUDE.md was not present at `D:/code/agentic-memory/CLAUDE.md`. Constraints come from
`.planning/codebase/CONVENTIONS.md`:

| Constraint | Rule |
|------------|------|
| Formatting | Black, line length 100 |
| Linting | Ruff with E, F, I, N, W, UP, B, C4, SIM rules |
| Type checking | MyPy strict mode — all functions fully typed |
| Docstrings | Google-style required on all public classes and functions |
| Logging | `logger = logging.getLogger(__name__)` module-level; use emoji indicators |
| Error handling | Never bare `except:`; always catch specific exception types |
| Imports | stdlib → third-party → relative; no star imports |
| Neo4j sessions | `with self._conn.session() as session:` context manager always |
| Private methods | Prefixed with `_` |
| Test files | `test_<module>.py` naming; `@pytest.mark.unit` / `@pytest.mark.integration` |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Temporal on nodes (valid_from as node property) | Temporal on relationships (edges carry validity) | STAR-RAG / temporal GraphRAG pattern (2024) | Enables point-in-time queries without full graph rewrite |
| Entity NER only (name + type) | NER + SPO triples (claim extraction) | Emerging standard in knowledge graph literature (2024–2025) | Richer entity relationships; queryable by predicate |
| APScheduler v3 | APScheduler v4 (planned) | v4 still alpha as of 2026-03-25 | No change yet — stick with v3 |
| Groq json_object (best-effort) | Groq json_schema strict mode | Strict mode added 2024–2025, limited model support | Available on Kimi K2 / Llama 4 Scout; not on llama-3.3-70b-versatile |

---

## Open Questions

1. **Claim extraction on code documents**
   - What we know: `ingestion/graph.py` does its own entity wiring via raw Cypher; it does not
     call `EntityExtractionService`. The code pipeline's "entities" are structurally defined
     (class names, function names) not LLM-extracted.
   - What's unclear: Should `ClaimExtractionService` run on code chunks in Phase 7, or skip it?
   - Recommendation: Skip code pipeline claim extraction in Phase 7. Code structure is already
     encoded in `DEFINES`, `CALLS`, `IMPORTS` relationships. SPO triples from code text would
     be low quality. Revisit in Phase 10.

2. **`as_of` filter implementation depth**
   - What we know: Full temporal graph filter (`r.valid_from <= as_of AND ...`) requires hybrid
     vector+graph queries. Phase 7 scope is adding the data, not the full query optimization.
   - What's unclear: Is a node-level `ingested_at` proxy sufficient for Phase 7, or do we need
     relationship-level filtering?
   - Recommendation: Implement node-level filter for Phase 7 (simple, no query refactor needed).
     Document that full relationship-level temporal filter is Phase 9 scope. Mark with `# TODO(P9)`.

3. **`ResearchScheduler` lifecycle in FastAPI**
   - What we know: The scheduler must start when `am-server` starts and stop cleanly on shutdown.
   - What's unclear: Where to initialize the scheduler (startup event vs module-level singleton)?
   - Recommendation: Use FastAPI lifespan context (`@asynccontextmanager`) to start/stop the
     `BackgroundScheduler`. Store as app state (`app.state.scheduler`). This is the standard
     FastAPI pattern for long-lived resources.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `apscheduler` | ResearchScheduler | Not in deps | — | Add to pyproject.toml |
| `sqlalchemy` | APScheduler SQLite store | Not in deps | — | Add to pyproject.toml |
| `neo4j` driver | All temporal writes | In deps | existing | — |
| `groq` | ClaimExtractionService | In deps (`>=0.10.0`) | existing | — |
| `httpx` | Brave Search in scheduler | In deps (`>=0.27.0`) | existing | — |

**Missing dependencies with no fallback:**
- `apscheduler>=3.10.0,<4.0` — required for scheduler; no alternative in scope
- `sqlalchemy>=2.0.0` — required by APScheduler SQLite job store

**Missing dependencies with fallback:**
- None — all other deps are already present

---

## Sources

### Primary (HIGH confidence)
- [APScheduler 3.x User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — scheduler setup, SQLite job store, cron trigger
- [APScheduler on PyPI](https://pypi.org/project/APScheduler/) — version verification (3.11.2 stable, 4.0.0a6 alpha)
- [Neo4j Cypher MERGE docs](https://neo4j.com/docs/cypher-manual/current/clauses/merge/) — MERGE on relationships, property matching behavior
- [Groq Structured Outputs docs](https://console.groq.com/docs/structured-outputs) — json_object vs json_schema modes, model support
- `src/codememory/core/graph_writer.py` — codebase ground truth, all existing relationship write patterns
- `src/codememory/core/entity_extraction.py` — ClaimExtractionService pattern to mirror
- `src/codememory/web/pipeline.py` — all ABOUT/MENTIONS write sites
- `src/codememory/chat/pipeline.py` — all ABOUT/MENTIONS write sites
- `.planning/phases/01-foundation/01-CONTEXT.md` — base schema locked decisions
- `.planning/phases/04-conversation-memory-core/04-CONTEXT.md` — conversation schema locked decisions

### Secondary (MEDIUM confidence)
- APScheduler docs async section — `asyncio.run()` in thread pool context (observed pattern, not explicitly stated in docs for this exact case)
- Groq json_object best-effort reliability — based on existing EntityExtractionService working in production; no formal benchmark

### Tertiary (LOW confidence)
- Claim extraction quality estimates (2–15 claims per document) — estimated from NER experience; no formal benchmark

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — APScheduler version verified via PyPI; Groq mode verified via docs; Neo4j MERGE behavior verified via official docs
- Architecture: HIGH — all patterns derived from existing codebase structure + official library docs
- Pitfalls: HIGH — MERGE relationship pitfall is officially documented; APScheduler version pitfall is documented in release notes

**Research date:** 2026-03-25
**Valid until:** 2026-06-25 (90 days — APScheduler v4 may go stable; Groq strict mode may expand model support)
