# Tool-Use Telemetry and Manual Annotation

This document describes the SQLite telemetry and manual annotation workflow for classifying MCP tool usage as `prompted` or `unprompted`.

## What This Feature Does

When the MCP server runs, each MCP tool call is logged to a local SQLite database with timing and status metadata.  
You can then run a separate CLI command to manually tag a response's tool-use burst as:

- `prompted`: tool usage was explicitly requested by your prompt.
- `unprompted`: tool usage happened without explicit prompt request.

This is designed for personal research workflows and post-hoc labeling.

## Storage

Default DB path:

- `<repo>/.codememory/telemetry.sqlite3`

Override with:

- `CODEMEMORY_TELEMETRY_DB=/absolute/path/to/telemetry.sqlite3`

Disable telemetry capture:

- `CODEMEMORY_TELEMETRY_ENABLED=0`

## Captured Tool-Call Fields

`tool_calls` rows include:

- `id` (auto-increment integer)
- `ts_utc`, `epoch_ms`
- `tool_name`
- `duration_ms`
- `success` (0/1)
- `error_type` (if failed)
- `client_id` (from `CODEMEMORY_CLIENT`, default `unknown`)
- `repo_root`
- `annotation_id`, `annotation_mode`, `prompt_prefix` (filled when labeled)

## CLI Annotation Commands

Basic usage:

```bash
codememory --prompted "check our auth"
codememory --unprompted "check our auth"
```

### Matching Behavior

The annotation command:

1. Creates a pending annotation entry.
2. Waits for the latest unannotated tool-use burst to become idle.
3. Applies annotation to matching tool calls.
4. Removes pending annotation if no matching tool calls are found.

This enables your workflow of running the annotation command right after an agent response finishes.

### Useful Flags

```bash
# Label specific IDs directly
codememory --unprompted "check our auth" --tool-call-id 101 --tool-call-id 102

# Optional custom annotation ID
codememory --unprompted "check our auth" --annotation-id auth-run-1

# Tune matching windows
codememory --unprompted "check our auth" \
  --wait-seconds 60 \
  --idle-seconds 4 \
  --lookback-seconds 240 \
  --recent-seconds 120

# Scope to one client stream
codememory --unprompted "check our auth" --client opencode
```

## Multi-Client Recommendation

Set `CODEMEMORY_CLIENT` differently per tool/runtime (for example `opencode`, `kilocode`, `codex`) to improve burst matching and analysis quality when multiple clients are active.

## Example Research Query (SQLite)

```sql
SELECT annotation_mode, tool_name, COUNT(*) AS calls
FROM tool_calls
WHERE annotation_mode IS NOT NULL
GROUP BY annotation_mode, tool_name
ORDER BY calls DESC;
```
