# OpenAI Dashboard Field Inventory

Current as of April 12, 2026.

This is a normalized field inventory based on OpenAI's current submission docs. Exact dashboard labels may drift. Where the docs are not explicit, the field grouping below is an inference from the required submission artifacts.

## Publisher and identity

| Field | Draft value | Source | Status |
|---|---|---|---|
| Publication name | `Agentic Memory` | `.codex-plugin/plugin.json` | Draft only |
| Publisher / developer name | `Agentic Memory` | `.codex-plugin/plugin.json` | Draft only |
| Verification mode | Individual or business | OpenAI submission prerequisite | Decision needed |
| Submitter role | `Owner` | OpenAI docs | Must confirm |

## Server and auth

| Field | Draft value | Source | Status |
|---|---|---|---|
| MCP server URL | `https://api.agenticmemory.com/mcp-openai` | `docs/PLUGIN_GA_PLAN.md` | Ready for use |
| Transport | Streamable HTTP | `W15-PUB-01` contract lock | Ready |
| Public auth surface | `mcp_public` | `src/am_server/mcp_profiles.py` | Ready in code |
| Auth model | `OAuth 2.0 authorization code flow` | Publication decision | Chosen |
| OAuth client details | `Required for submission once implemented` | OpenAI docs | Implementation pending |
| CSP / exact domains fetched | `TBD` | OpenAI docs require exact CSP | Missing |

## App listing metadata

| Field | Draft value | Source | Status |
|---|---|---|---|
| App name | `Agentic Memory` | `.codex-plugin/plugin.json` | Draft only |
| Short description | `Search and trace code, research, and conversation memory from ChatGPT.` | Adapted from Codex plugin copy | Draft only |
| Long description | `Connect ChatGPT to Agentic Memory through a hosted MCP surface optimized for bounded code, research, and conversation retrieval plus explicit memory writes.` | Adapted from current public metadata | Draft only |
| Category | `Coding` | `.codex-plugin/plugin.json` | Draft only |
| Company URL | `https://api.agenticmemory.com/publication/agentic-memory` | Publication pages | Ready in code, deploy pending |
| Website URL | `https://api.agenticmemory.com/publication/agentic-memory` | `.codex-plugin/plugin.json` target | Ready in code, deploy pending |
| Privacy policy URL | `https://api.agenticmemory.com/publication/privacy` | Publication pages | Ready in code, deploy pending |
| Terms URL | `https://api.agenticmemory.com/publication/terms` | Publication pages | Ready in code, deploy pending |
| Support/contact URL | `https://api.agenticmemory.com/publication/support` | Publication pages | Ready in code, deploy pending |
| Logo | `TBD` | Submission requirement | Missing |
| Screenshots | `TBD` | Submission requirement | Missing |
| Localization info | `TBD` | Submission requirement | Missing |
| Country availability | `TBD` | Submission flow | Missing |

## Tool and MCP metadata

| Field | Draft value | Source | Status |
|---|---|---|---|
| Tool list | Frozen nine-tool public contract | `W15-PUB-01` | Ready |
| Tool descriptions | Use current server docstrings plus reviewer-safe summaries | `src/agentic_memory/server/public_mcp.py` | Needs final copy pass |
| Tool annotations | Public read/write/destructive/open-world labels locked | `src/am_server/mcp_profiles.py` | Ready |
| Read/write justification | Internal/private memory writes only, no public internet side effects | `W15-PUB-01` | Ready |

## Reviewer evidence

| Field | Draft value | Source | Status |
|---|---|---|---|
| Test prompts | See `TEST_PROMPTS.md` | This packet | Ready after review |
| Expected responses | See `TEST_PROMPTS.md` | This packet | Ready after review |
| Demo credentials | See `DEMO_ACCOUNT_CHECKLIST.md` | This packet | Provisioning pending |
| Mobile validation note | Required if public artifact is intended for mobile use | OpenAI docs | Needs explicit answer |
| Release notes | `Initial public submission` | Submission process | Ready once submitting |

## Immediate cleanup list

- Deploy the new `am-server` publication routes to the public host.
- Provision OAuth and reviewer/demo account flows against the chosen auth model.
- Produce screenshots from the actual ChatGPT developer-mode experience.
- Freeze the final listing copy after one pass against the OpenAI app submission guidelines.
