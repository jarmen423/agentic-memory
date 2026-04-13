# W15-PUB-06 Track 2 Handoff

## What changed

- Integrated `docs/PLUGIN_GA_PLAN.md` with the completed publication packet work.
- Added `docs/publication/INDEX.md` as the main publication entrypoint.
- Pinned the canonical public publication/legal URLs on `api.agenticmemory.com/publication/*`.
- Locked the hosted public auth posture to OAuth 2.0 authorization code flow in the plan.

## What I verified

- The plan still reads as an integration pass, not a rewrite.
- The new index links cleanly to OpenAI, Anthropic, shared, and future status docs.
- The canonical URL block in the plan matches the publication pages already established by the wave.
- The auth posture is stated consistently in the plan assumptions and the Anthropic section.

## Residual risks

- `docs/publication/status/*` is still a future surface, so the index links are forward-looking.
- The plan now reflects OAuth 2.0 authorization code flow, but implementation and deployment of that auth posture remain outside this track.
- Any drift in the publication pages or packet structure will need a follow-up integration pass.

## Exact files touched

- `docs/PLUGIN_GA_PLAN.md`
- `docs/publication/INDEX.md`
- `.planning/execution-publication/handoffs/w15-public-plugin-publication/W15-PUB-06-TRACK-2.md`
