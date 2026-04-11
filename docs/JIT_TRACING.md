# JIT Tracing and CALLS Pivot

This document explains the current code-behavior strategy in Agentic Memory.

The short version:

- normal indexing builds durable structural graph data only
- repo-wide `CALLS` construction is no longer mandatory
- behavioral tracing now happens just in time when an operator or MCP client asks for it

---

## Why the design changed

The older Phase 11 direction tried to build a repo-wide function call graph during
every normal code-ingestion run.

That looked attractive on paper, but in real repositories it created a bad tradeoff:

- indexing became slower and more fragile
- TypeScript semantic analysis could time out on larger repos
- Python and TypeScript analyzers often produced lots of diagnostics but few useful surviving edges
- the ingestion path paid this cost even when the agent never needed call-path information

The current design treats behavioral tracing as an on-demand exploration tool
instead of a mandatory ingestion tax.

---

## Current default code pipeline

Normal code ingestion now stops after Pass 3:

1. `Pass 0` database setup
2. `Pass 1` structure scan and changed-file detection
3. `Pass 2` entity extraction and embedding creation
4. `Pass 3` import graph construction

What this gives the graph cheaply and reliably:

- `File`
- `Function`
- `Class`
- `Chunk`
- `DEFINES`
- `HAS_METHOD`
- `IMPORTS`
- semantic code chunks for retrieval

What it deliberately does **not** do during normal indexing:

- repo-wide `CALLS` reconstruction

This applies to both:

- `agentic-memory index`
- `agentic-memory watch`

---

## What replaced mandatory Pass 4

Two explicit paths now exist:

### 1. Experimental manual path

If you still want the older analyzer-backed repo-wide `CALLS` build, run:

```bash
agentic-memory build-calls
```

This keeps the legacy/experimental pass available for diagnostics and comparison
without forcing it into every normal indexing run.

### 2. JIT tracing path

If you want to understand what one function likely does, run:

```bash
agentic-memory trace-execution path/to/file.py:qualified_name --json
```

Or use the MCP tool:

- `trace_execution_path(...)`

This is now the preferred path for behavioral exploration.

---

## JIT tracing model

JIT tracing is intentionally bounded and conservative.

It does **not** attempt to compute a whole-repo execution graph before the agent
can work. Instead, it traces one requested function root at a time.

### Resolution flow

When the user provides a symbol, the resolver tries:

1. exact function `signature`
2. unique repo-local `qualified_name`
3. unique repo-local short `name`

If the symbol is ambiguous, the resolver returns candidates instead of guessing.

### Context package

Once the root function is resolved, the graph gathers a bounded context package:

- root function metadata and source code
- owning file imports
- reverse imports for the owning file
- same-file sibling functions
- same-file classes and methods
- candidate functions from directly imported files

This package gives the tracing model enough local evidence to reason about likely
behavior without requiring a whole warmed language-server session.

### Model behavior

The tracing service uses the configured extraction LLM to emit structured edges.

The model is constrained to select only from graph-provided candidate signatures.
That means the LLM can help map behavior, but it cannot invent new repo-local
functions outside the candidate set.

### Edge types

JIT tracing does not flatten every relationship into one generic edge.

Current edge/result types:

- `direct_call`
- `callback`
- `message_flow`
- `unresolved`

This is important because many useful relationships in real repos are not simple
AST-level function calls.

---

## Cache model

JIT trace results are cached separately from trusted structural graph edges.

### Cache nodes

- `CodeTraceRun`

### Derived cached relationships

- `JIT_CALLS_DIRECT`
- `JIT_CALLS_CALLBACK`
- `JIT_MESSAGE_FLOW`

### Why the cache is separate

The structural graph and the JIT trace cache have different trust models.

Structural graph:

- deterministic
- cheap enough to compute during normal ingestion
- intended as durable graph truth

JIT traces:

- derived on demand
- provenance-rich
- confidence-scored
- useful for exploration and retrieval expansion
- not treated as unconditional graph truth

### Cache invalidation

Version 1 cache validity is simple:

- reuse cached trace only when the root file `ohash` still matches
- otherwise recompute

The CLI also exposes:

- `--force-refresh`

---

## CLI surfaces

### Normal indexing

```bash
agentic-memory index
agentic-memory watch
```

Behavior:

- builds structural code graph
- does not build repo-wide `CALLS`

### Explicit old path

```bash
agentic-memory build-calls
```

Behavior:

- runs the experimental repo-wide analyzer-backed `CALLS` flow
- useful for diagnostics and comparison

### On-demand tracing

```bash
agentic-memory trace-execution src/app.py:run_checkout
agentic-memory trace-execution src/app.py:run_checkout --max-depth 3 --json
agentic-memory trace-execution checkout --force-refresh
```

Behavior:

- resolves one function root
- traces likely behavior recursively through direct-call edges
- includes callback/message-flow edges in the result
- returns ambiguity candidates instead of guessing

### Diagnostics

```bash
agentic-memory call-status
agentic-memory debug-py-calls path/to/file.py --repo /path/to/repo --json
agentic-memory debug-ts-calls path/to/file.ts --repo /path/to/repo --json
```

These remain useful for inspecting the older analyzer-backed path.

---

## MCP surface

The MCP server now exposes:

- `trace_execution_path(start_symbol, max_depth=2, force_refresh=False, repo_id=None)`

This gives AI agents a behavioral exploration tool that can be invoked only when
needed, instead of paying the cost up front during indexing.

---

## Recommended usage

### Use normal indexing for:

- bootstrapping a repo
- keeping files, entities, chunks, and imports current
- powering baseline code search and dependency views

### Use JIT tracing for:

- "what does this function call?"
- "what likely happens after this entry point?"
- "what callback path leads back into this handler?"
- "trace a small execution neighborhood for this task"

### Use `build-calls` only for:

- experiments
- diagnostics
- comparisons against JIT tracing
- investigating analyzer behavior on a specific repo

---

## Product rationale

This pivot changes the architecture from:

- exhaustive pre-computation

to:

- durable structural indexing plus agentic just-in-time exploration

That is a better fit for real agent work because:

- imports and structure are cheap and reliable
- behavioral tracing is only paid for when needed
- ambiguity can be handled interactively instead of silently degrading ingestion
- retrieval can expand into behavioral context without pretending the entire repo
  already has a perfect global call graph

---

## Future work

This design leaves room for stronger deterministic symbol infrastructure later.

Most likely follow-up directions:

- SCIP-backed symbol and reference ingestion where available
- stronger candidate generation for JIT tracing
- broader cache invalidation beyond root-file `ohash`
- optional retrieval-time reuse of high-confidence cached trace edges

For now, the important boundary is:

- structural graph is mandatory
- behavioral tracing is on demand
