# Public Plugin GA Plan for ChatGPT, Codex, Claude, and OpenClaw

## Goal

Publish Agentic Memory through the real public distribution paths that exist today:

- **OpenAI Apps / ChatGPT Apps Directory**
- **Codex Plugin Directory** via OpenAI app approval and publication
- **Anthropic Connectors Directory** for Claude remote MCP

For this plan, **public GA** means:

- hosted and production-stable
- reviewer-ready
- approved and published/listed on platforms that require review

Manual installability, local plugin bundles, and custom connector support are necessary for testing and dogfooding, but they are **not sufficient** for public publication.

## Summary

Ship all public surfaces in parallel, but hold launch behind one shared publication gate. Treat the hosted/public MCP contract as the product core, freeze that contract, and close the remaining gaps in six tracks:

1. shared hosted backend hardening for `/mcp-openai`, `/mcp-codex`, `/mcp-claude`
2. OpenAI publication track for ChatGPT app approval and Codex distribution
3. Codex local/preflight plugin track for packaging, dogfood, and future self-serve readiness
4. Anthropic publication track for Claude connector approval and directory listing
5. OpenClaw / Claude Code hardening as a separate beta-or-later deliverable
6. submission assets, compliance docs, dogfood telemetry, and release ops

This plan targets **public publication**, not just "hosted + installable".

## Important Interface Decisions

- Keep the current public MCP tool set unchanged for this cycle:
  - `search_codebase`
  - `get_file_dependencies`
  - `trace_execution_path`
  - `search_all_memory`
  - `search_web_memory`
  - `memory_ingest_research`
  - `search_conversations`
  - `get_conversation_context`
  - `add_message`
- Keep the current public mounts as the only supported public backend contract:
  - `/mcp-openai`
  - `/mcp-codex`
  - `/mcp-claude`
- Keep `/mcp-full` private/internal only.
- Keep public and internal auth separated. Public publication requires distinct public credentials, public telemetry labels, and public-facing quota/rate-limit handling.
- Do not add indexing, watch, repo-maintenance, or admin tools to any public surface in this cycle.
- Treat ChatGPT and Codex as one **OpenAI publication path**:
  - the OpenAI-reviewed app is the public artifact
  - Codex public distribution comes from that approved/published app
- Treat `.codex-plugin/plugin.json` and `.mcp.json` as:
  - local install and preflight artifacts
  - useful for dogfood and future self-serve Codex publishing
  - not the primary public publication mechanism for this cycle
- Treat Claude remote connector publication and OpenClaw / Claude Code local plugin work as separate deliverables.
- Public publication requires stable, non-placeholder external artifacts:
  - privacy policy URL
  - terms URL
  - support URL
  - canonical company / product publication URL
  - reviewer test credentials or demo data when auth is required

Canonical publication/legal URLs live on the `api.agenticmemory.com/publication/*` surface:

- `https://api.agenticmemory.com/publication/agentic-memory`
- `https://api.agenticmemory.com/publication/privacy`
- `https://api.agenticmemory.com/publication/terms`
- `https://api.agenticmemory.com/publication/support`
- `https://api.agenticmemory.com/publication/dpa`

## Implementation Changes

### 1. Shared hosted backend GA hardening

- Freeze the public MCP contract and document it as versioned GA surface behavior.
- Add accurate public-tool safety annotations and verify them in code and smoke tests:
  - `readOnlyHint`
  - `destructiveHint`
  - `openWorldHint` where relevant
- Harden `am-server` public auth for real hosted use:
  - require dedicated public MCP keys
  - reject fallback-to-internal behavior in hosted prod config
  - label metrics and logs by surface: `openai`, `codex`, `claude`
- Replace the current per-process rate limiter with a hosted-safe public quota/rate-limit layer or, at minimum, a deploy-stable throttling path that survives multi-process deployment.
- Add public-surface health/smoke coverage that verifies:
  - auth works
  - tool list is correct
  - streamable HTTP transport works
  - CORS and browser/client compatibility are correct where required
  - each mount returns the expected surface headers/labels
- Add production deployment docs for the current `api.agenticmemory.com` path:
  - required env vars
  - secret separation
  - public vs internal auth
  - rollback path
  - reviewer/demo account preparation if auth is required
- Move public legal/support URLs off ad hoc repo blobs and onto stable publication-ready URLs.
- Make public-surface telemetry and product-state reporting first-class release inputs.

### 2. OpenAI publication track for ChatGPT and Codex

- Define the supported public path as:
  - ChatGPT developer-mode validation against the hosted MCP surface
  - OpenAI app submission and review
  - publish approved app
  - resulting public ChatGPT listing and Codex plugin distribution
- Use one canonical OpenAI reviewer-facing endpoint for submission:
  - default: `/mcp-openai`
- Keep `/mcp-codex` available for platform-specific testing if useful, but do not treat it as the primary public submission mechanism.
- Build the full OpenAI submission package:
  - app name, descriptions, logo, screenshots
  - privacy policy URL
  - terms URL
  - company / support URLs
  - MCP and tool metadata
  - test prompts and expected responses
  - localization/publication metadata
  - demo credentials and sample data if auth is required
- Complete OpenAI prerequisite work:
  - org or individual verification
  - Owner-role access for submitter
  - dashboard-ready submission owner/runbook
  - CSP definition if app UI/components require it
- Add OpenAI validation:
  - ChatGPT developer mode connects successfully
  - tool metadata refresh works
  - one read/search scenario passes
  - one conversation-memory retrieval scenario passes
  - one explicit memory-write scenario passes
  - mobile validation passes if the public artifact is meant to be used there
- Add post-approval launch checks:
  - app is published
  - direct listing link works
  - app can be found by exact name search
  - Codex distribution is created from the approved app and is reachable
- Keep the browser extension out of the OpenAI publication critical path. It remains a passive-capture surface and regression target, not the primary public OpenAI product for this cycle.

### 3. Codex local/preflight plugin track

- Keep `.codex-plugin/plugin.json` and `.mcp.json` as the canonical local Codex bundle.
- Harden the Codex bundle for:
  - local install correctness
  - dogfood coverage
  - future self-serve publication readiness
- Validate:
  - manifest completeness
  - legal/support metadata completeness
  - hosted URL assumptions
  - install docs
  - local/custom marketplace install flow
- Add Codex-specific preflight coverage:
  - plugin bundle resolves correctly
  - hosted MCP handshake succeeds
  - bounded tool list is exposed
  - one read flow and one write flow work end-to-end
- Treat this track as a release-quality confidence and packaging track, not as the formal public publication path.
- Keep `am-proxy` and `am-codex-watch` as secondary/passive-capture surfaces. They must not regress, but they are not blockers for public publication unless the product claim explicitly includes passive capture.

### 4. Anthropic publication track for Claude remote connector

- Define the supported public path as Anthropic remote MCP directory submission against `/mcp-claude`.
- Prepare the hosted connector for Anthropic directory requirements:
  - streamable HTTP
  - HTTPS/TLS
  - CORS configured for supported browser/cloud clients
  - safety annotations on every tool
  - OAuth 2.0 authorization code flow for the public auth posture
  - public internet reachability from Anthropic infrastructure
- Create the full Anthropic submission package:
  - connector name, description, use cases, category
  - privacy policy URL
  - support channel
  - setup/auth docs
  - minimum three usage examples
  - reviewer test account with sample data if auth is required
  - tested-surface checklist for Claude.ai, Claude Desktop, and Claude Code where applicable
- Add Claude remote validation:
  - remote connection works against `/mcp-claude`
  - auth works with the intended production auth model
  - bounded tool list is exposed
  - conversation retrieval and explicit memory write succeed end-to-end
  - error handling is understandable when auth/backend is unhealthy
- Add Anthropic-specific infra checks:
  - server is reachable from public internet
  - firewall/IP allowlisting is correct if applicable
  - OAuth callbacks and reviewer/test flows work cleanly
- Submit through the Anthropic remote MCP directory process and treat revision-response turnaround as part of the release critical path.

### 5. OpenClaw / Claude Code hardening track

- Keep OpenClaw as a separate Claude Code-class deliverable, not part of the core remote Claude connector publication gate.
- Finish the remaining OpenClaw gaps already called out in repo docs:
  - live host validation in a real OpenClaw install
  - canonical read support for non-conversation memory hits
  - end-to-end plugin-installed runtime tests, not just backend-contract tests
- Keep `capture_only` as the default shipping mode.
- Keep `augment_context` installable but non-default.
- Remove manual operator friction where possible:
  - validate setup command in a real host session
  - reduce or eliminate normal reliance on explicit `--session-id`
- Add host validation artifacts:
  - real install checklist
  - setup/repair checklist
  - backend-unhealthy behavior check
  - project activation/deactivation flow check
- If OpenClaw reaches directory/package-submission quality later, treat that as its own follow-on publication task.
- If OpenClaw misses the cycle, ship it as public beta and do not block OpenAI or Anthropic publication.

### 6. Submission assets, docs, telemetry, and release ops

- Add one shipping dashboard/status view that clearly reports:
  - hosted backend healthy
  - public MCP surfaces healthy
  - OpenAI submission package ready
  - OpenAI review status
  - OpenAI publication status
  - Claude submission package ready
  - Claude review status
  - Claude directory listing status
  - OpenClaw host validation status
- Extend dogfood state/events so every platform records:
  - install attempted
  - install completed
  - first successful tool call
  - first successful memory write
  - first successful memory retrieval
  - review submitted
  - review revision requested
  - review approved
  - published/listed
  - repair succeeded
- Add one operator runbook for launch:
  - deploy hosted backend
  - validate each public mount
  - run platform smoke suites
  - verify submission assets
  - submit to OpenAI
  - submit to Anthropic
  - track review state
  - publish/list when approved
  - either cut launch or rollback/unpublish
- Add one user-facing install/info page per primary surface:
  - ChatGPT / OpenAI app
  - Codex plugin distribution
  - Claude connector
  - OpenClaw beta

## Test Plan and Release Gates

### Gate 1: Contract and policy freeze

Must pass before submission packaging is considered complete.

- Public tool list matches the frozen contract on all public mounts.
- Every public tool has accurate safety/action annotations.
- Public auth is separated from internal auth.
- Public mounts do not expose internal/admin tools.
- Streamable HTTP works for `/mcp-openai`, `/mcp-codex`, `/mcp-claude`.
- CORS and client compatibility checks pass where required.
- Public privacy/support/legal URLs are stable and non-placeholder.

### Gate 2: Submission package readiness

Must pass before any formal review submission.

- OpenAI verification prerequisites are complete:
  - verified publishing identity
  - Owner-role submitter
- OpenAI submission assets are complete:
  - descriptions
  - logo/screenshots
  - test prompts and expected behavior
  - privacy/company/support URLs
  - demo credentials if auth is required
- Anthropic submission assets are complete:
  - setup/auth docs
  - privacy policy
  - support channel
  - minimum three usage examples
  - reviewer test account if auth is required
- Reviewer runbooks exist for both OpenAI and Anthropic.

### Gate 3: OpenAI approval and publication

Required for ChatGPT public launch and Codex public distribution.

- ChatGPT developer mode validates successfully against the canonical OpenAI endpoint.
- OpenAI review submission is accepted without missing-field churn.
- Required read, retrieval, and write scenarios pass in the reviewer/demo environment.
- Review revisions, if any, are closed.
- App is approved and published.
- Direct listing link works.
- App can be found by exact publication name.
- Codex distribution is created from the approved app and is reachable.

### Gate 4: Anthropic approval and directory listing

Required for Claude public launch.

- Claude remote connector works against `/mcp-claude` from the supported surfaces.
- Anthropic submission is accepted without missing requirement churn.
- Required read, retrieval, and write scenarios pass in the reviewer/demo environment.
- Review revisions, if any, are closed.
- Connector is approved and listed in the directory.

### Gate 5: Optional OpenClaw readiness

Required only if OpenClaw is included in the same public announcement.

- Real host install succeeds.
- `openclaw agentic-memory setup` works end-to-end.
- Session register, memory search, memory ingest, project use/status/stop, and context resolve all pass in a real host session.
- Non-conversation canonical read support is complete.
- Repair flow works when backend is unavailable or misconfigured.

### Regression suite

These are mandatory across the cycle but are not the primary public publication target.

- `am-ext` manual acceptance checklist still passes.
- `am-proxy` Codex App Server passive ingest still works.
- `am-codex-watch` still ingests Codex rollout artifacts.
- Existing MCP self-hosted flow remains intact.
- Existing product-status and dogfood flows remain intact.

## Assumptions and Defaults

- Priority is parallel execution across all target surfaces, with one shared public launch gate.
- Public GA means **hosted + reviewer-ready + approved/published where the platform requires review**.
- OpenAI public distribution currently runs through app submission and publication:
  - ChatGPT listing is the primary artifact
  - Codex public distribution is derived from the approved app
  - standalone `.codex-plugin` packaging is not sufficient for public Codex publication in this cycle
- Anthropic public distribution currently runs through remote MCP directory submission and review.
- Public auth posture for the hosted public surfaces is OAuth 2.0 authorization code flow.
- Deployment remains on the current `am-server` architecture and existing `api.agenticmemory.com` hosting path; no platform migration is part of this plan.
- ChatGPT primary target is the OpenAI Apps / hosted MCP path, not the browser extension.
- Claude is treated as two deliverables:
  - public hosted connector path via `/mcp-claude`
  - OpenClaw / Claude Code native plugin path
- Browser extension, proxy, and Codex artifact watcher remain supported secondary surfaces and regression targets, not primary blockers for public publication.
- If OpenClaw live host validation misses the cycle, ship it as beta and do not block OpenAI or Anthropic publication.
