# OpenAI Reviewer Runbook

Current as of April 14, 2026.

This runbook is for internal dry runs and for preparing the exact material that will be entered into the OpenAI dashboard submission flow.

## Review target

- Product: `Agentic Memory`
- Canonical endpoint: `https://mcp.agentmemorylabs.com/mcp-openai`
- Transport: streamable HTTP
- Public tool count: `9`
- Public internet side effects: none
- State-changing tools:
  - `memory_ingest_research`
  - `add_message`

## Reviewer prerequisites

- Submission owner has `Owner` role and verified publisher identity.
- Hosted endpoint is reachable over public HTTPS.
- Stable privacy, terms, support, and website URLs are ready.
- Current live reviewer auth packet is prepared from `../shared/REVIEWER_ACCESS_PACKET.md`.
- Reviewer-ready credentials and sample data are provisioned with no MFA.
- Marketplace publication still requires OAuth 2.0 authorization code flow; do
  not mark that blocker closed until it is actually implemented.
- The live public MCP host currently uses bearer-key reviewer auth, not OAuth.

## ChatGPT developer-mode dry run

1. Turn on ChatGPT developer mode in Settings -> Apps & Connectors -> Advanced settings.
2. Create a connector using the canonical OpenAI endpoint.
3. Use the dedicated reviewer key from `../shared/REVIEWER_ACCESS_PACKET.md`.
4. Confirm that the advertised tools match the frozen nine-tool contract.
5. Run the prompts in `TEST_PROMPTS.md`.
6. Refresh metadata after one redeploy and verify the tool list still matches.
7. If the app is meant to work on mobile, verify the same connector on ChatGPT mobile after linking it on web.

Raw `curl` checks are only useful for confirming the auth gate. They are not a
full success signal for the streamable HTTP MCP handshake.

## Expected tool contract

Read tools:

- `search_codebase`
- `get_file_dependencies`
- `trace_execution_path`
- `search_all_memory`
- `search_web_memory`
- `search_conversations`
- `get_conversation_context`

Write tools:

- `memory_ingest_research`
- `add_message`

Annotation expectations:

- Read tools: `readOnlyHint=true`, `destructiveHint=false`, `openWorldHint=false`
- Write tools: `readOnlyHint=false`, `destructiveHint=true`, `openWorldHint=false`

## Submission packet contents

- Final listing copy from `DASHBOARD_FIELD_INVENTORY.md`
- Reviewer prompts and acceptance criteria from `TEST_PROMPTS.md`
- Demo credential packet from `DEMO_ACCOUNT_CHECKLIST.md`
- Reviewer access packet from `../shared/REVIEWER_ACCESS_PACKET.md`
- Publish checks from `PUBLISH_CHECKS.md`

## Failure triage before submission

- If ChatGPT cannot connect:
  - verify public HTTPS reachability
  - verify endpoint path is `/mcp-openai`
  - verify auth expectations match the chosen review model
- If tools look wrong:
  - refresh metadata in ChatGPT
  - confirm deployed surface still matches the frozen public contract
- If a write test fails:
  - confirm the reviewer account has the required project or sample data context
  - confirm the backend allows explicit memory writes on the public surface
- If outputs contain extra internal identifiers:
  - remove or suppress telemetry-style fields before submission

## Internal sign-off before pressing Submit

- Product owner signs off on listing copy and screenshots.
- Backend owner signs off on endpoint stability and public contract.
- Release owner signs off on privacy, terms, support, and reviewer-account readiness.
