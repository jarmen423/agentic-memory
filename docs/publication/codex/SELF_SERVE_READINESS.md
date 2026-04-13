# Codex Self-Serve Readiness Notes

Current as of April 12, 2026.

This note separates what is already true for the Codex path from what still depends on broader platform publication.

## Ready now

- Repo-owned local plugin bundle exists.
- Repo-owned MCP bundle exists.
- Bundle targets the hosted Codex public surface at `/mcp-codex`.
- Shared legal/publication URLs are embedded in the plugin metadata.
- Local JSON validation can be used as a cheap preflight gate.

## Not yet guaranteed

- Public discovery behavior outside the local/preflight install flow
- Any Codex distribution path derived from OpenAI publication
- Final post-publication listing URL or search/discovery behavior
- Final support workflow as experienced through the live Codex distribution path

## Operational stance

- Treat the current Codex bundle as preflight-ready, not fully published.
- Keep the publication claim scoped to:
  - local bundle validity
  - hosted MCP contract alignment
  - operator install/smoke readiness
- Track broader publication evidence in:
  - `W15-PUB-02` for OpenAI publication
  - `W15-PUB-07` for final status/evidence capture
