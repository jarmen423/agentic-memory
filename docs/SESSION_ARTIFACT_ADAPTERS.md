# Session artifact adapters (multi-CLI passive ingest)

Agentic Memory can ingest **terminal / IDE-adjacent** coding agent sessions without a single universal wire format. This document explains **integration tiers**, the **`SessionArtifactAdapter`** contract used by [`packages/am-codex-watch`](../packages/am-codex-watch), and how to add support for another CLI.

## Integration tiers (orthogonal)

| Tier | Mechanism | When to use |
|------|-----------|-------------|
| **1 – Host hooks** | Runtime calls your code each turn (e.g. OpenClaw plugin) | Highest fidelity when the host supports plugins |
| **2 – Stdio proxy** | Known JSON-RPC / App Server / ACP on stdin/stdout ([`am-proxy`](../packages/am-proxy)) | IDE + agent subprocess with a documented protocol |
| **3 – Session artifacts** | Tail files or DBs the tool writes locally (`am-codex-watch`) | Interactive TUI when transcripts are **durable on disk** |
| **4 – Explicit MCP / tools** | Agent calls `add_message` or similar | No passive path; agent opts in per turn |

**Not supported for passive v1:** scraping raw terminal output (PTY), which is brittle and high-risk for secrets.

## Adapter contract (`SessionArtifactAdapter`)

Each CLI with a **stable, documented** on-disk format can ship a small adapter (built into the package or, later, via entry points). An adapter provides:

- **`adapter_id`** — Stable string (e.g. `codex_rollout`).
- **`source_key` / `source_agent`** — Must match [`ConversationIngestionPipeline`](../src/agentic_memory/chat/pipeline.py) registration (`chat_*` keys); register new keys when you need analytics separation.
- **`watch_roots(home)`** — Default directories to recurse (e.g. `~/.codex/sessions`).
- **`matches_file(path)`** — Select files this adapter owns (avoid ingesting unrelated JSONL).
- **`session_hint_from_path(path)`** — Optional thread id from filename.
- **`parse_line(...)`** — Emit `session_id` updates and `message` envelopes (`role`, `content`, `timestamp`) for **user/assistant** turns only, or `skip`.

Shared infrastructure handles **byte offsets**, **debounced watching**, **`POST /ingest/conversation`**, and **turn indexing** namespaced by **`(source_key, session_id)`** so two CLIs cannot collide.

## Configuration (`~/.config/am-codex-watch/config.toml`)

```toml
[am_codex_watch]
endpoint = "http://127.0.0.1:8765"
api_key = "…"
# adapters = ["codex_rollout"]   # default; add more as they exist
# roots = ["/override/only/these"]   # optional: replaces adapter default roots
# extra_roots = ["/more/paths"]      # optional: union with adapter roots
```

## Adding a new CLI

1. **Spike:** Capture real session files; confirm append behavior and schema.
2. Implement **`SessionArtifactAdapter`** in `packages/am-codex-watch/src/am_codex_watch/adapters/`.
3. Register in **`BUILTIN_ADAPTERS`** in [`registry.py`](../packages/am-codex-watch/src/am_codex_watch/adapters/registry.py).
4. Register **`source_key`** in [`pipeline.py`](../src/agentic_memory/chat/pipeline.py) if not reusing `chat_cli`.
5. Extend **`iter_artifact_files`** if the format is not `*.jsonl` (e.g. SQLite needs a different reader in a follow-up).
6. Document format (like [CODEX_ROLLOUT_JSONL.md](CODEX_ROLLOUT_JSONL.md)).

## Privacy

Artifact paths often live under the **user profile** and may contain prompts, code, and secrets. Only run watchers on accounts and endpoints you trust.
