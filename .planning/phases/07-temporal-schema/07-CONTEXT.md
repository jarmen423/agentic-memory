# Phase 7: Temporal Schema + Claim Extraction + Research Scheduling — Context

**Gathered:** 2026-03-25
**Status:** Ready for research and planning

<domain>
## Phase Boundary

Phase 7 adds time as a first-class dimension to the knowledge graph, upgrades entity NER to full
SPO triple extraction, and delivers research scheduling. It extends all existing Neo4j pipelines
(code, web, conversation) with temporal relationship properties, introduces a new
`ClaimExtractionService`, and ships the `ResearchScheduler` with APScheduler + SQLite job store.

This phase does NOT change the embedding strategy, vector indexes, REST API auth, or node schema.
All changes are either: (a) new properties on existing relationships, (b) new relationship types
created by claim extraction, or (c) new service classes and CLI commands.

</domain>

<decisions>
## Implementation Decisions

### A. Temporal Schema — Relationship Properties

**Locked: All temporal state lives on relationships, not nodes.**

Every Neo4j relationship in the graph gains five new first-class properties:

| Property | Type | Required | Default | Meaning |
|----------|------|----------|---------|---------|
| `valid_from` | ISO-8601 string | Yes | `ingested_at` of source node | Earliest time the claim is valid |
| `valid_to` | ISO-8601 string or null | No | `null` | Latest valid time; `null` = still valid |
| `confidence` | float 0.0–1.0 | Yes | `1.0` | Probability the claim is correct |
| `support_count` | int | Yes | `1` | Number of independent evidence instances |
| `contradiction_count` | int | Yes | `0` | Number of contradicting evidence instances |

These apply to ALL relationship types:
- `ABOUT`, `MENTIONS`, `BELONGS_TO` (entity wiring — all three pipelines)
- `HAS_CHUNK`, `PART_OF` (research pipeline)
- `HAS_TURN`, `PART_OF` (conversation pipeline)
- `CITES` (research pipeline)
- All new claim relationships (`KNOWS`, `WORKS_AT`, `RESEARCHED`, etc.)

**New at ingestion time:** every `write_relationship()` call passes `valid_from = now`, `confidence = 1.0`, `support_count = 1`, `contradiction_count = 0` unless caller overrides.

---

### B. Backfill Strategy

**Locked: Use `ingested_at` from source Memory node as fallback `valid_from` on existing relationships.**

Cypher backfill semantics:
- `valid_from` = `ingested_at` from the source Memory node (MATCH traversal to parent node)
- `confidence` = `0.5` (lower than freshly extracted claims to signal lower trust)
- `valid_to` = `null` (assume still valid unless contradicted)
- `support_count` = `1`, `contradiction_count` = `0`

Backfill runs as a **one-time migration command** (`codememory migrate-temporal`), not at
`chat-init` / `web-init` time. Reason: init commands should be fast and idempotent; a full-graph
backfill is a one-shot operation best run explicitly. The command should be safe to re-run
(idempotent: skip relationships that already have `valid_from`).

---

### C. GraphWriter Temporal Methods

Three new methods on `GraphWriter`:

1. `write_temporal_relationship(from_key, from_hash, to_name, to_type, rel_type, valid_from, valid_to, confidence, support_count, contradiction_count)` — replaces the existing `write_relationship()` for temporal writes. Old `write_relationship()` preserved for backward compat; new method is the canonical path from Phase 7 onwards.

2. `update_relationship_validity(from_key, from_hash, to_name, to_type, rel_type, valid_to)` — sets `valid_to` on an existing relationship to mark it as no longer valid. Used when a contradiction is confirmed.

3. `increment_contradiction(from_key, from_hash, to_name, to_type, rel_type)` — increments `contradiction_count` by 1 on a relationship. Does NOT change `valid_to` — contradiction is flagged but relationship stays live until explicitly invalidated.

**Cypher MERGE pattern for temporal relationships (critical detail):**

MERGE on a relationship checks ALL properties in the pattern. Do NOT include `valid_from` or other temporal fields in the MERGE pattern itself — they are metadata, not identity. Correct pattern:

```cypher
MATCH (m {source_key: $source_key, content_hash: $content_hash})
MATCH (e {name: $entity_name, type: $entity_type})
MERGE (m)-[r:{rel_type}]->(e)
ON CREATE SET r.valid_from = $valid_from,
              r.valid_to = $valid_to,
              r.confidence = $confidence,
              r.support_count = $support_count,
              r.contradiction_count = $contradiction_count
ON MATCH SET  r.support_count = r.support_count + 1,
              r.confidence = CASE WHEN $confidence > r.confidence THEN $confidence
                                  ELSE r.confidence END
```

This pattern: (a) merges on relationship type + endpoint node identity only, (b) sets temporal fields on CREATE, (c) increments support_count and upgrades confidence on MATCH.

---

### D. Claim Extraction — Format

**Locked claim dict schema:**

```python
{
    "subject": str,       # entity name — resolved to existing/new Entity node
    "predicate": str,     # one of the closed catalog predicates
    "object": str,        # entity name — resolved to existing/new Entity node
    "valid_from": str | None,   # ISO-8601; None means extract couldn't determine
    "valid_to": str | None,     # ISO-8601; None means still valid or unknown
    "confidence": float   # 0.0–1.0; LLM-reported confidence in claim truth
}
```

**Subject and object resolution:** Both `subject` and `object` are entity names. After extraction,
resolve each against existing Entity nodes via `upsert_entity()`. The relationship is written
between the resolved Entity nodes (Entity → Entity), not Memory → Entity. This creates a
pure entity-to-entity knowledge graph layer.

**Extraction granularity:** Per-document (not per-chunk). Same rationale as entity NER: one call
covers the full document for better cross-chunk entity resolution. Document text is truncated to
8000 chars (same as existing `EntityExtractionService` budget guard).

---

### E. Predicate Catalog

**Locked: Closed set. LLM instructed to use ONLY these predicates.**

| Predicate | Meaning | Example |
|-----------|---------|---------|
| `KNOWS` | Person-to-person acquaintance | Alice KNOWS Bob |
| `WORKS_AT` | Person/agent works at business | Alice WORKS_AT Acme Corp |
| `RESEARCHED` | Agent/person researched a topic | Alice RESEARCHED "vector databases" |
| `REFERENCES` | Any node references another | Report REFERENCES "GPT-4" |
| `USES` | Technology/tool usage | Project USES FastAPI |
| `LEADS` | Person leads project/team | Alice LEADS "Project X" |
| `PART_OF` | Membership or containment | Module PART_OF Project |
| `LOCATED_IN` | Geographic or organizational location | Office LOCATED_IN "San Francisco" |
| `CREATED_BY` | Authorship or creation | Library CREATED_BY "John" |
| `CONTRADICTS` | One claim contradicts another | Claim A CONTRADICTS Claim B |

**"Other" fallback:** Any claim that does not fit these predicates is mapped to `REFERENCES`
(the catch-all). LLM is explicitly told this in the prompt.

**Extensibility:** The catalog is loaded from config (list under `extraction.claim_predicates`).
The default is the closed set above. Users can extend via config without code changes.

---

### F. Two Separate Groq Calls Per Document

**Locked: NER and claim extraction are two separate Groq calls.**

Rationale: Mixing entity lists and SPO triples in one JSON schema leads to brittle output.
Separate calls with clear schemas are more reliable with Groq JSON mode.

Call order:
1. `EntityExtractionService.extract(text)` — existing NER call, unchanged
2. `ClaimExtractionService.extract(text)` — new claims call

Both calls are made at the pipeline level, not inside each service. Each pipeline's `ingest()`
calls both services sequentially. The results are independent; entity NER failure should not
block claim extraction and vice versa.

---

### G. ClaimExtractionService

New class at `src/codememory/core/claim_extraction.py`.

```python
class ClaimExtractionService:
    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile",
                 predicates: list[str] | None = None) -> None: ...

    def extract(self, document_text: str) -> list[dict[str, Any]]:
        """Returns list of claim dicts: [{subject, predicate, object,
           valid_from, valid_to, confidence}]"""
```

Uses Groq `response_format={"type": "json_object"}` with `temperature=0.0`.
Returns `{"claims": [...]}` — same "claims" key convention as NER uses "entities".

**Groq structured outputs note:** As of 2025, Groq strict mode supports `json_schema` on
`moonshotai/kimi-k2-instruct` and Llama 4 Scout, but the existing codebase uses
`llama-3.3-70b-versatile` with `json_object` mode (best-effort). Continue with `json_object`
mode for consistency; schema description goes in the system prompt.

---

### H. Research Scheduling — Schedule Storage

**Locked: APScheduler 3.x (stable) with SQLite job store; Schedule node also in Neo4j.**

APScheduler version: `3.11.2` (latest stable as of 2026-03-25). Version 4 is still alpha — do not use.

APScheduler SQLite setup:
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

SCHEDULES_DB = Path("~/.config/agentic-memory/schedules.db").expanduser()

jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{SCHEDULES_DB}")}
scheduler = BackgroundScheduler(jobstores=jobstores, daemon=True)
```

**SQLite single-process constraint:** APScheduler docs warn against sharing SQLite job stores
across multiple processes. This is acceptable — the scheduler runs in one process (the
`am-server` FastAPI server). Docker restarts are handled: job IDs are stable, so restart
re-attaches existing jobs from the DB.

**:Schedule node schema in Neo4j:**
```
(:Schedule {
    schedule_id: str,        ← UUIDv4, primary key
    template: str,           ← e.g. "Research {topic} focusing on {angle}"
    variables: [str],        ← list of variable names: ["{topic}", "{angle}"]
    cron_expr: str,          ← standard cron expression e.g. "0 9 * * 1"
    project_id: str,
    created_at: str,         ← ISO-8601
    last_run_at: str | null,
    run_count: int           ← starts at 0
})
```

Schedule nodes are created/updated in Neo4j at the same time as APScheduler job registration.
They serve as a queryable record of what schedules exist, separate from the job store DB.

---

### I. LLM Variable Fill

**Locked: Same Groq model as entity/claim extraction. Prompt includes recent RESEARCHED edges.**

Input to the LLM fill call:
1. The template string (e.g. `"Research {topic} focusing on {angle}"`)
2. Variable names (`topic`, `angle`)
3. Last 10 `RESEARCHED` edges from Neo4j for the project, ordered by `valid_from` DESC
4. Instruction: "Choose values that have NOT been recently covered based on the research history"

The LLM returns a JSON object: `{"topic": "...", "angle": "..."}`.

The filled template becomes the Brave Search query. After the search + ingest, the pipeline
writes a `RESEARCHED` edge with `valid_from = now`.

---

### J. `as_of` Temporal Filter

**Locked: All search MCP tools gain optional `as_of: str | None` parameter.**

Filter semantics when `as_of` is provided:
```cypher
WHERE r.valid_from <= $as_of
  AND (r.valid_to IS NULL OR r.valid_to >= $as_of)
```

Default when `as_of` is `None`: no temporal filter applied (current behavior preserved).

This applies to: `search_conversations`, `search_web_memory`, `search_codebase` (Phase 10 unified
search), and `get_conversation_context`.

---

### K. Circuit Breakers for Scheduling

The scheduler must not blow through API budgets on failures:

- **Brave Search**: if 3 consecutive runs fail (non-2xx), circuit opens for 1 hour
- **Groq variable fill**: if call fails, skip run and log error (no retry loop)
- **ResearchIngestionPipeline**: existing CircuitBreaker pattern from `ingestion/graph.py` applies
- **Cost cap**: configurable `max_runs_per_day` per schedule (default: 5); enforced in
  `ResearchScheduler.run_research_session()` by checking `run_count`

---

### L. CLI Commands

Two new commands:

```
codememory web-schedule --template "Research {topic} on {angle}" \
    --variables topic angle \
    --cron "0 9 * * 1" \
    --project-id my-project

codememory web-run-research --schedule-id <uuid>   # manual trigger
codememory web-run-research --project-id my-project --template "..."  # ad hoc
```

`web-schedule` writes the `:Schedule` node and registers with APScheduler.
`web-run-research` triggers `ResearchScheduler.run_research_session()` synchronously.

### M. MCP Tools

Three new tools:

| Tool | Description |
|------|-------------|
| `schedule_research` | Create a recurring research schedule |
| `run_research_session` | Trigger a single research run immediately |
| `list_research_schedules` | List all schedules for a project |

---

### N. Module Location

New files (all in `src/codememory/`):
- `core/claim_extraction.py` — `ClaimExtractionService`
- `core/scheduler.py` — `ResearchScheduler`

Extended files:
- `core/graph_writer.py` — 3 new temporal methods
- `core/entity_extraction.py` — no changes (NER call unchanged)
- `web/pipeline.py` — add claim extraction pass; populate temporal fields
- `chat/pipeline.py` — populate temporal fields on existing relationship writes
- `cli.py` — add `web-schedule`, `web-run-research` subparsers
- `server/tools.py` — add 3 MCP tools + `as_of` param on existing search tools
- `pyproject.toml` — add `apscheduler`, `sqlalchemy` deps

**Code pipeline (`ingestion/graph.py`):** Only `ABOUT`, `MENTIONS`, `BELONGS_TO` are written
via `write_relationship()`. These are wired through the base class. The code pipeline does not
call claim extraction (code ASTs are structured differently). Temporal fields will be populated
via temporal migration method.

---

### Claude's Discretion

- Exact Cypher for backfill migration command
- `ClaimExtractionService` prompt wording (as long as it constrains to catalog predicates and
  requests JSON `{"claims": [...]}`)
- APScheduler `BackgroundScheduler` vs `AsyncIOScheduler` — use `BackgroundScheduler` (sync
  FastAPI endpoint calls into async paths via `run_in_executor`; scheduler runs on background
  thread)
- Cost cap enforcement details (run_count tracking location)
- Unit test fixtures for temporal writes

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1–4 outputs (extend these)
- `src/codememory/core/graph_writer.py` — all existing MERGE patterns; add temporal methods here
- `src/codememory/core/entity_extraction.py` — `EntityExtractionService` pattern to replicate for claims
- `src/codememory/web/pipeline.py` — `ResearchIngestionPipeline` — add claim extraction pass here
- `src/codememory/chat/pipeline.py` — `ConversationIngestionPipeline` — add temporal fields here
- `src/codememory/ingestion/graph.py` — `CircuitBreaker` pattern for scheduler circuit breakers
- `src/codememory/server/tools.py` — MCP tool pattern; add new scheduling tools here
- `src/codememory/cli.py` — add `web-schedule`, `web-run-research` subparsers

### Prior phase contexts
- `.planning/phases/01-foundation/01-CONTEXT.md` — graph schema, entity taxonomy, ingestion flow
- `.planning/phases/02-web-research-core/02-CONTEXT.md` — ResearchIngestionPipeline patterns
- `.planning/phases/04-conversation-memory-core/04-CONTEXT.md` — ConversationIngestionPipeline patterns

### Planning docs
- `.planning/ROADMAP.md` — Phase 7 spec and dependency graph
- `.planning/codebase/CONVENTIONS.md` — Black, Ruff, MyPy strict, Google docstrings

</canonical_refs>

<code_context>
## Existing Code Insights

### Relationship Types Currently in the Codebase

All relationships that need temporal properties added:

**Via `GraphWriter.write_relationship()` (ABOUT, MENTIONS, BELONGS_TO):**
- Written in `web/pipeline.py` for Chunk and Finding nodes
- Written in `chat/pipeline.py` for Turn nodes
- Written in `ingestion/graph.py` (code module) — though this module has its own internal
  Cypher; check for any `write_relationship()` delegation

**Research-specific relationships (dedicated GraphWriter methods):**
- `HAS_CHUNK` — `write_has_chunk_relationship()`
- `PART_OF` — `write_part_of_relationship()`
- `CITES` — `write_cites_relationship()`

**Conversation-specific relationships:**
- `HAS_TURN` — `write_has_turn_relationship()`
- `PART_OF` — `write_part_of_turn_relationship()`

**Code module internal relationships (in `ingestion/graph.py`, not via GraphWriter):**
- `DEFINES` — file defines class/function
- `HAS_METHOD` — class has method
- `DESCRIBES` — comment describes code element
- `IMPORTS` — module import relationship
- `CALLS` — function call relationship
- `PART_OF_PR` — git pull request membership

The code module relationships are written with raw Cypher in `graph.py`, not through `GraphWriter`.
They will get temporal fields via the backfill migration only, not via the temporal write path
(too invasive to refactor `graph.py` in Phase 7).

### `write_relationship()` Current Signature
```python
def write_relationship(
    self,
    source_key: str,
    content_hash: str,
    entity_name: str,
    entity_type: str,
    rel_type: str = "ABOUT",
) -> None:
```

New `write_temporal_relationship()` adds `valid_from`, `valid_to`, `confidence`,
`support_count`, `contradiction_count` parameters.

### Entity Extraction Model
Current default: `llama-3.3-70b-versatile`. Claim extraction uses the same model and API key.

### APScheduler not yet in dependencies
`pyproject.toml` does not include APScheduler or SQLAlchemy. Both must be added:
- `apscheduler>=3.10.0,<4.0` — pin below v4 (alpha, API unstable)
- `sqlalchemy>=2.0.0` — required by APScheduler SQLite job store

</code_context>

<deferred>
## Deferred Ideas (OUT OF SCOPE for Phase 7)

- **SpacetimeDB integration** — Phase 8. Phase 7 writes temporal data to Neo4j only.
- **Temporal PPR retrieval** — Phase 9. Phase 7 adds the data; Phase 9 queries it differently.
- **Cross-module temporal ranking** — Phase 10.
- **Confidence decay over time** — temporal relevance scoring deferred to Phase 9 PPR.
- **Automated contradiction resolution** — flagging contradictions is Phase 7; resolving them
  (deciding which claim wins) is Phase 9 / Phase 8 maintenance layer.
- **Claim deduplication across documents** — v1 creates one claim relationship per extraction;
  support_count increment handles duplicates via MERGE ON MATCH.
- **Entity deduplication ("React" vs "ReactJS")** — deferred per Phase 1 CONTEXT.md.
- **Open predicate catalog / normalization** — Phase 7 uses closed set only.
- **Streaming research (SSE)** — batch Brave Search is sufficient.

</deferred>

---

*Phase: 07-temporal-schema*
*Context gathered: 2026-03-25*
