# Publication Launch Runbook

Current as of April 14, 2026.

This runbook is the operator sequence for getting Agentic Memory from submission-ready to publicly published across the current OpenAI and Anthropic paths.

## 1. Freeze the hosted public contract

Before any submission:

- Confirm `W15-PUB-01` remains true in the deployed environment.
- Verify `/health/mcp-surfaces` with operator auth.
- Confirm the public surfaces still expose the frozen nine-tool contract.
- Confirm public write tools are still limited to private Agentic Memory state.
- Confirm no internal/admin tools are visible on public mounts.
- Confirm `AM_SERVER_PUBLIC_MCP_API_KEYS` is set to a dedicated reviewer key
  rather than reusing `AM_SERVER_API_KEYS`.

## 2. Confirm public legal and support assets

Before any dashboard or directory submission:

- Privacy URL is live.
- Terms URL is live.
- Support/contact URL is live.
- Website/company URL is live.
- All URLs are stable and not GitHub blob links.
- Canonical target URLs:
  - `https://mcp.agentmemorylabs.com/publication/agentic-memory`
  - `https://mcp.agentmemorylabs.com/publication/privacy`
  - `https://mcp.agentmemorylabs.com/publication/terms`
  - `https://mcp.agentmemorylabs.com/publication/support`
  - `https://mcp.agentmemorylabs.com/publication/dpa`

These URLs were re-verified live on 2026-04-14. Re-check them immediately
before submission rather than assuming the prior verification still holds.

Use:

- `PUBLIC_POLICY_CHECKLIST.md`
- `SUPPORT_AND_TERMS_CHECKLIST.md`

## 3. Run pre-submission validation

### OpenAI

- Connect ChatGPT developer mode to `/mcp-openai`.
- Use the dedicated public MCP reviewer key from `REVIEWER_ACCESS_PACKET.md`.
- Refresh metadata once after a redeploy.
- Run the prompts in `docs/publication/openai/TEST_PROMPTS.md`.
- Confirm screenshot capture is from the real connected surface.

### Anthropic

- Connect the remote MCP surface to `/mcp-claude`.
- Use the dedicated public MCP reviewer key from `REVIEWER_ACCESS_PACKET.md`.
- Confirm auth behavior matches the chosen production/reviewer model.
- Confirm the connector is reachable from the public internet.
- Prepare the minimum usage examples and reviewer setup path.

## 4. Submit the review packets

### OpenAI

- Use the OpenAI dashboard review flow.
- Record the submission date and case id.
- Archive the final submitted assets and copy.

### Anthropic

- Use the current Anthropic connector submission path.
- Record the submission date and any tracking reference returned.
- Archive the final submitted assets and copy.

## 5. Monitor review and respond to revisions

- Track status in `REVIEW_STATUS_TEMPLATE.md` or the future status surface.
- If a revision is requested:
  - capture the exact issue
  - assign an owner
  - fix only the needed surface
  - update the packet/runbook if the issue exposed missing documentation
- Re-run the affected smoke tests before resubmitting.

## 6. Publish and verify

### OpenAI

- Publish the approved app from the dashboard.
- Record the direct listing URL.
- Verify exact-name search for `Agentic Memory`.
- Verify derived Codex distribution after publish.

### Anthropic

- Confirm directory listing is live.
- Record the direct listing URL.
- Verify the public setup path still works after listing.

## 7. Capture launch evidence

Use `TELEMETRY_EVIDENCE_CHECKLIST.md` to record:

- review submitted
- review approved
- published/listed
- first successful post-publish tool call
- first successful post-publish write and retrieval

## 8. Rollback or unpublish path

If launch must be reversed:

- OpenAI:
  - unpublish the active version from the dashboard
  - switch to a known-good approved version if one exists
- Anthropic:
  - follow the current listing-removal or support escalation path
- Backend:
  - if necessary, disable public auth credentials or block the affected mount while leaving internal surfaces intact

## 9. Close the wave

- Update the publication status log.
- Attach approval and listing evidence.
- Confirm top-level docs are aligned in `W15-PUB-06`.
- Mark the launch gate closed only after OpenAI and Anthropic evidence are both attached.
