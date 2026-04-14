# Codex Install Checklist

Current as of April 12, 2026.

This checklist is the operator path for validating the local Codex plugin bundle before broader publication/distribution claims are made.

## Files under test

- [`.codex-plugin/plugin.json`](D:/code/agentic-memory/.codex-plugin/plugin.json)
- [`.mcp.json`](D:/code/agentic-memory/.mcp.json)

## Install assumptions

- Codex is running with access to the repo-root plugin bundle.
- The hosted endpoint is reachable:
  - `https://mcp.agentmemorylabs.com/mcp-codex`
- The public publication URLs resolve:
  - `https://mcp.agentmemorylabs.com/publication/agentic-memory`
  - `https://mcp.agentmemorylabs.com/publication/privacy`
  - `https://mcp.agentmemorylabs.com/publication/terms`

## Preflight steps

1. Parse both JSON files locally:
   - `Get-Content .codex-plugin/plugin.json | ConvertFrom-Json | Out-Null`
   - `Get-Content .mcp.json | ConvertFrom-Json | Out-Null`
2. Confirm the MCP bundle points only at `/mcp-codex`.
3. Confirm the plugin metadata still describes the bounded public surface and not the self-hosted full tool set.
4. Confirm website, privacy, and terms URLs match the shared publication surfaces.

## Local install validation

1. Make the plugin visible to the local Codex environment using the repo bundle.
2. Confirm `Agentic Memory` appears with the expected display name and description.
3. Confirm the install path resolves the MCP bundle file without manual edits.
4. Confirm there is no reference to `/mcp-full` or internal-only tools.

## Post-install checks

- The surfaced tool set should correspond to the frozen public contract:
  - `search_codebase`
  - `get_file_dependencies`
  - `trace_execution_path`
  - `search_all_memory`
  - `search_web_memory`
  - `memory_ingest_research`
  - `search_conversations`
  - `get_conversation_context`
  - `add_message`
- The bundle should describe the product as a hosted memory/search integration for Codex, not as a local indexer or admin console.

## Remaining blockers

- Final self-serve distribution still depends on upstream OpenAI publication and any resulting Codex discovery path.
- Support/contact routing is still carried by shared publication assets rather than Codex-specific metadata.
