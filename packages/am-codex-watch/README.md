# am-codex-watch

Tails **session artifact** files that coding agent CLIs write locally (starting with **OpenAI Codex** rollout JSONL under `~/.codex/sessions`) and POSTs **user/assistant** turns to Agentic Memory **`am-server`** at `POST /ingest/conversation`.

The package uses a pluggable **`SessionArtifactAdapter`** registry so additional CLIs can be added without duplicating tail/offset/HTTP logic. See [`docs/SESSION_ARTIFACT_ADAPTERS.md`](../../docs/SESSION_ARTIFACT_ADAPTERS.md) and [`docs/CODEX_ROLLOUT_JSONL.md`](../../docs/CODEX_ROLLOUT_JSONL.md) (Codex format).

## Install

From the repo root (editable):

```bash
pip install -e packages/am-codex-watch
```

Dependencies: `httpx`, `watchdog`.

## Configuration

Optional TOML: `~/.config/am-codex-watch/config.toml`

```toml
[am_codex_watch]
endpoint = "http://127.0.0.1:8765"
api_key = "YOUR_AM_SERVER_API_KEY"
default_project_id = "default"
# adapters = ["codex_rollout"]       # default; future built-in ids go here
# roots = ["/only/these"]            # optional: replaces adapter default roots
# extra_roots = ["/also/watch"]      # optional: union with adapter roots
```

## Usage

```bash
# Long-running watcher (Ctrl+C to stop)
am-codex-watch

# One-shot scan of matching artifacts (no filesystem watch)
am-codex-watch --once --debug
```

CLI overrides: `--endpoint`, `--api-key`, `--config /path/to/config.toml`.

## Behavior

- **Built-in adapters:** `codex_rollout` → `source_key=chat_codex_rollout`, `source_agent=codex`.
- **Ingestion mode:** `passive`.
- **Turn indices** are namespaced per `(source_key, session_id)` so multiple adapters cannot collide.
- **Per-file byte offsets** live in `~/.config/am-codex-watch/state.json`.

## Related

- **IDE + App Server:** [`packages/am-proxy`](../am-proxy) wraps `codex app-server` for editor-driven sessions.
- **OpenClaw:** [`packages/am-openclaw`](../am-openclaw) uses native plugin hooks to `POST /openclaw/memory/ingest-turn`.
