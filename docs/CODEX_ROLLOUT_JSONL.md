# Codex rollout JSONL (session files)

This document locks the **on-disk transcript format** used by the [openai/codex](https://github.com/openai/codex) CLI so Agentic Memory can **tail** session files for passive ingestion (see `packages/am-codex-watch`, adapter `codex_rollout`). For the multi-CLI adapter model, see [SESSION_ARTIFACT_ADAPTERS.md](SESSION_ARTIFACT_ADAPTERS.md).

## Location

Codex stores rollout files under the user’s Codex home, typically:

- **macOS / Linux:** `~/.codex/sessions/` (and optionally `~/.codex/archived_sessions/`)
- **Windows:** `%USERPROFILE%\.codex\sessions\`

Files are often named like `rollout-<ISO-ish-timestamp>-<thread-id>.jsonl` (exact naming is defined upstream).

## Line shape (`RolloutLine`)

Each line is one JSON object. Upstream defines a `RolloutLine` with a top-level `timestamp` and a **flattened** `RolloutItem`:

- `RolloutItem` is serialized with `tag = "type"`, `content = "payload"`, `rename_all = "snake_case"`.
- Variants include: `session_meta`, `response_item`, `compacted`, `turn_context`, `event_msg`.

Relevant excerpt from `codex-rs/protocol` (conceptual):

```text
RolloutLine { timestamp, + flattened RolloutItem }
RolloutItem::SessionMeta(SessionMetaLine)   -> type: "session_meta"
RolloutItem::ResponseItem(ResponseItem)     -> type: "response_item"
...
```

## Ingest mapping (Agentic Memory)

`am-codex-watch` **only** turns **`response_item` → `message`** rows into conversation turns:

- **`role`** `user` / `assistant`: text is taken from `payload.content[]` items (`input_text`, `output_text`; images are skipped).
- **Other** `ResponseItem` variants (tools, reasoning, etc.) are **ignored** for v1 to avoid duplicating noisy tool traces.

**Session id:** Prefer `session_meta.payload.id` (thread id) when seen; otherwise parse a UUID from the rollout **filename**.

## Flush / live tail behavior

The upstream rollout recorder is designed to **persist session rollouts to JSONL** and flushes as the session progresses (implementation may batch; lines should **append** during an active session). The watcher therefore uses **per-file byte offsets** so restarts resume without re-ingesting old lines.

If a Codex version buffers entire sessions before writing, ingestion would appear **only after flush**—that is a Codex behavior, not something the watcher can fix.

## Privacy

These files live in the **user profile** and may contain **prompts, code, and secrets**. Run `am-codex-watch` only on machines and accounts where posting to `am-server` is acceptable.
