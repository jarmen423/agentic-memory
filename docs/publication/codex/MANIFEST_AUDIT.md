# Codex Manifest Audit

Current as of April 12, 2026.

This note records the current audit of the local Codex plugin bundle:

- [`.codex-plugin/plugin.json`](D:/code/agentic-memory/.codex-plugin/plugin.json)
- [`.mcp.json`](D:/code/agentic-memory/.mcp.json)

## Bundle summary

- Plugin name: `agentic-memory`
- Display name: `Agentic Memory`
- Version: `0.1.4`
- Hosted Codex MCP endpoint: `https://mcp.agentmemorylabs.com/mcp-codex`
- Surface intent: bounded public MCP contract only

## Metadata present

- Product name and developer name
- Description and longer install-facing explanation
- Homepage / website URL
- Privacy policy URL
- Terms of service URL
- Repository URL
- License
- Prompt examples
- Capability tags: `Interactive`, `Read`, `Write`

## Contract alignment checks

- `.mcp.json` points to `/mcp-codex`, not `/mcp`, `/mcp-openai`, or `/mcp-full`.
- The bundle language describes the public plugin surface, not the self-hosted full tool set.
- The public website, privacy, and terms URLs match the shared publication URL set used by the OpenAI and Anthropic packets.

## Current gaps / notes

- No separate Codex support URL is encoded in the current bundle files; support routing is currently expected to resolve from the shared publication/support surface and later top-level docs.
- The bundle is suitable for local/preflight install validation, but broader self-serve marketplace/distribution behavior still depends on the upstream OpenAI publication path captured in `W15-PUB-02`.
- Final discovery behavior after public publication should be recorded in the publication status log during `W15-PUB-07`.

## Exit criteria for W15-PUB-03

- Bundle JSON parses cleanly.
- Local install/checklist docs exist for Codex-specific preflight.
- Hosted handshake and auth expectations are documented against `/mcp-codex`.
- Remaining self-serve publication assumptions are explicit rather than implicit.
