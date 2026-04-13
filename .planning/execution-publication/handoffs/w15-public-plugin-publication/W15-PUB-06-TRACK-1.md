# W15-PUB-06 Track 1 Handoff

Status: complete

## What changed

- Updated `README.md` so the public plugin section reflects the real publication model:
  - OpenAI / ChatGPT publish through OpenAI app review
  - Codex distribution derives from the approved OpenAI app
  - Claude publishes through Anthropic directory submission
- Added canonical publication/legal URLs to `README.md`:
  - `https://api.agenticmemory.com/publication/agentic-memory`
  - `https://api.agenticmemory.com/publication/privacy`
  - `https://api.agenticmemory.com/publication/terms`
  - `https://api.agenticmemory.com/publication/support`
  - `https://api.agenticmemory.com/publication/dpa`
- Added concise cross-links in `README.md` to the publication packets in `docs/publication/openai`, `docs/publication/anthropic`, and `docs/publication/shared`.
- Updated `docs/INSTALLATION.md` so the OpenClaw beta section is clearly separated from the public publication flow and the new public publication section points at the canonical URLs and publication packets.
- Rewrote `docs/PUBLIC_PLUGIN_SURFACES.md` to be the canonical contract page for the hosted public MCP surfaces, including:
  - the real OpenAI / Codex / Claude publication model
  - public tool set boundaries
  - auth model with strict MCP auth note
  - streamable HTTP transport
  - canonical publication/legal URLs
  - packet references

## What I verified

- Read back the edited sections in all three docs to confirm the wording is coherent and the publication model is consistent across them.
- Confirmed the docs now point at the same canonical publication/legal URLs and the same packet set.
- Confirmed the updated public surface page no longer describes Codex as a separate public submission path.

## Residual risks

- These are documentation changes only; they do not deploy the hosted publication endpoints or implement OAuth.
- Track 2 still owns the top-level integration/doc index work, so I intentionally did not touch `docs/PLUGIN_GA_PLAN.md` or `docs/publication/INDEX.md`.
- The public URLs are canonical in docs, but they still depend on the live deployment being present on `api.agenticmemory.com`.

## Exact files touched

- `README.md`
- `docs/INSTALLATION.md`
- `docs/PUBLIC_PLUGIN_SURFACES.md`
- `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-06-TRACK-1.md`
