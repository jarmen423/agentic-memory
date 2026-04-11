# am-proxy

Transparent stdio proxy that wraps agent CLIs and passively POSTs conversation turns to **am-server** (`POST /ingest/conversation`).

## Install

```bash
pip install -e packages/am-proxy
# or
pipx install am-proxy
```

## Quick usage

**Do not expect a prompt.** `am-proxy` reads **JSON-RPC lines from stdin** and forwards them to the agent. If you run it in a plain terminal with nothing piped in, it will **wait on stdin** (this is normal). Use it as the **agent binary in your IDE**, or pipe a client that speaks the protocol.

```bash
# One-time: print editor-oriented snippets
am-proxy setup

# Proxy OpenAI Codex (defaults to `codex app-server` for stdio — not the interactive TUI)
am-proxy --agent codex --project my-project

# Explicit child args (passed through to `codex`)
am-proxy --agent codex --project my-project -- resume Radiology
am-proxy --agent codex --project my-project -- app-server --listen stdio://
```

The leading `--` is treated as a separator for `am-proxy` users and is **not**
forwarded to the child process.

### Windows

If `codex` on your PATH resolves to **`codex.ps1`**, the proxy resolves a launchable **`codex.cmd`** (npm global layout) when possible. You can also pass the full path:

```text
am-proxy --agent "C:\Users\YOU\AppData\Roaming\npm\codex.cmd" --project my-project
```

### am-server URL and auth

Defaults target **`http://127.0.0.1:8765`** (same default port as `python -m am_server.server`). Override with flags or `~/.config/am-proxy/config.toml`:

```toml
[am_proxy]
endpoint = "http://127.0.0.1:8765"
api_key = "same-as-AM_SERVER_API_KEY"
default_project_id = "default"
```

CLI overrides: `am-proxy --endpoint URL --api-key KEY ...`

## How it works

- **ACP-style agents** (`threads/message`, …): unchanged routing.
- **OpenAI Codex App Server** (`thread/*`, `turn/start`, `item/completed`, …): mapped to the same ingest payloads. See [docs/AM_PROXY_CODEX.md](../../docs/AM_PROXY_CODEX.md).

There is **no** Codex `--acp` flag in current OpenAI Codex CLI; use **`codex app-server`** (default when you pass no extra args) or another documented subcommand.

## Development

```bash
cd packages/am-proxy
pytest tests/ -q
```
