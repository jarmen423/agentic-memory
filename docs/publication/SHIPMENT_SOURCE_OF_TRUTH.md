# Shipment Source of Truth

Last updated: 2026-04-19
Owner: publication orchestrator

## Purpose

This is the single source of truth for what is still required to ship:

- OpenClaw plugin
- ChatGPT app (OpenAI Apps)
- Codex distribution path
- Claude connector (Anthropic remote MCP)
- shared public MCP production surface

If any other publication doc conflicts with this file, this file is the current decision and status source.

## Scope and Current Reality

### Already true

- Public publication/legal pages are live on `mcp.agentmemorylabs.com/publication/*`.
- Public mounts are live:
  - `https://mcp.agentmemorylabs.com/mcp-openai`
  - `https://mcp.agentmemorylabs.com/mcp-codex`
  - `https://mcp.agentmemorylabs.com/mcp-claude`
- Public reviewer auth path exists today via bearer key (`AM_SERVER_PUBLIC_MCP_API_KEYS`).
- OpenAI and Anthropic submission packets are marked complete in tracker docs.
- Codex local/preflight bundle is ready.
- Real ChatGPT developer-mode validation has been completed against
  `https://mcp.agentmemorylabs.com/mcp-openai/`.
- OpenAI dashboard domain verification and tool scan both succeeded.
- The OpenAI app was submitted for review on `2026-04-19`.

### Not yet true (global blockers)

- OpenAI review is not yet approved/published.
- Anthropic submission event is not yet completed.
- Real approval/listing evidence is not attached.
- Reviewer/demo/test packet needs final post-review archival and rotation notes.

## Gate Status (Authoritative)

- G2 Submission package readiness: complete
- G3 OpenAI approval and publication: in review
- G4 Anthropic approval and directory listing: not started
- G5 Launch integration and closure: in progress

Launch is blocked until G3 + G4 + G5 close.

## Critical Path Remaining (P0)

1. Keep the live OAuth-backed OpenAI review path stable while review is pending.
2. Capture the OpenAI review case/reference and archive the submission evidence in repo-tracked form.
3. Run real Claude validation (Claude.ai and Claude Desktop minimum) against live `/mcp-claude` and capture evidence artifacts.
4. Pass OpenAI review, publish listing, confirm derived Codex distribution URL.
5. Submit Anthropic connector, pass review, confirm directory listing URL.
6. Attach all evidence to status ledger and close launch gate record.

OAuth execution registry:

- `docs/publication/OAUTH_TODO.md`
- `.planning/execution-oauth/README.md`
- `.planning/execution-oauth/ROADMAP.md`
- `.planning/execution-oauth/tasks.json`

## Surface-by-Surface Remaining Work

## 1) Shared Public MCP Surface

Status: In progress

Remaining:

- Keep the deployed OAuth + reviewer-fallback auth posture stable during review
- Finalize reviewer/demo account and key rotation packet
- Capture and archive live validation artifacts for each public mount
  (`/mcp-openai`, `/mcp-codex`, `/mcp-claude`)

Done when:

- OAuth works end-to-end in production reviewer flow
- Public auth/documentation claims exactly match deployed behavior
- Evidence links recorded in publication status ledger

## 2) OpenAI: ChatGPT App + Derived Codex Distribution

Status: Submitted; awaiting review

Remaining:

- Capture the OpenAI review/case reference once available
- Archive the final submission evidence in repo-tracked form
- Review feedback addressed (if any)
- App published and listing URL recorded
- Derived Codex distribution confirmed and URL recorded

Done when:

- OpenAI listing is publicly reachable
- Codex distribution is reachable from approved OpenAI app path
- Submission + approval + publish evidence attached

## 3) Codex Local/Preflight Track

Status: Preflight-ready, publication-derived path pending

Remaining:

- Confirm final post-publication Codex distribution behavior and support workflow
- Record final distribution URL and discovery behavior evidence

Done when:

- Codex public distribution evidence exists and is linked to OpenAI publication outcome

## 4) Anthropic: Claude Remote MCP Connector

Status: Not submitted

Remaining:

- Real Claude.ai validation against `/mcp-claude`
- Real Claude Desktop validation against `/mcp-claude`
- Final truthful support statement for Claude Code compatibility
- Submission sent (tracking reference recorded)
- Review feedback addressed (if any)
- Directory listing published and URL recorded

Done when:

- Anthropic directory listing is publicly reachable
- Submission + approval + listing evidence attached

## 5) OpenClaw Plugin

Status: Package identity and commands locked; release/listing readiness incomplete

Remaining:

- Final marketplace title
- Final marketplace icon/screenshots
- Final support contact and issue-routing copy
- Final compatibility statement for target OpenClaw host version
- Reconcile operator docs to remove placeholder package-name text
- Run and pass release gates:
  - `npm run build`
  - `npm run typecheck`
  - `npm run build:openclaw`
  - `npm run test:openclaw`
  - `npm run typecheck:openclaw`
  - `npm run pack:openclaw`
  - `npm run validate:release-artifacts`
- Confirm real install/doctor/setup evidence from clean host environment

Done when:

- Listing assets are final
- Release gates pass on clean environment
- Install path (`install -> doctor -> setup`) is validated with evidence

## Evidence Checklist (Must Exist Before Launch)

## OpenAI evidence

- Submission confirmation artifact
- Review thread archive
- Approval artifact
- Published listing URL
- Derived Codex distribution artifact

## Anthropic evidence

- Submission confirmation artifact
- Review thread archive
- Approval artifact
- Directory listing URL

## Shared evidence

- OAuth implementation proof (deploy + test evidence)
- Live publication/legal URL verification timestamp
- Reviewer/demo/test account readiness proof
- Launch gate closure record
- OpenAI submission/case evidence after dashboard review starts emitting it

## Launch Decision Rule

Ship announcement can proceed only when all are true:

- G3 is closed
- G4 is closed
- G5 is closed
- OAuth is live and truthful in docs
- OpenAI and Anthropic evidence sections are complete
- OpenClaw status is explicitly declared as either:
  - included in launch (all OpenClaw done criteria met), or
  - public beta and out of critical path

## Source Docs (Read/Update Alongside This File)

- `docs/publication/status/LAUNCH_GATE.md`
- `docs/publication/status/OPENAI_REVIEW.md`
- `docs/publication/status/ANTHROPIC_REVIEW.md`
- `docs/publication/status/EVIDENCE.md`
- `docs/publication/codex/SELF_SERVE_READINESS.md`
- `docs/openclaw/marketplace/PUBLISHING_CHECKLIST.md`
- `docs/PLUGIN_GA_PLAN.md`

## Update Protocol

When status changes, update in this order:

1. Update this file first (single-truth summary)
2. Update platform-specific status docs and attach artifacts
3. Reconcile any checklist deltas in OpenClaw/Codex docs
4. Recompute gate state in launch gate record
