# Anthropic Publish Checks

Run these after directory approval and before calling the Claude connector launched.

## Approval and listing

- Submission date is recorded.
- Any tracking reference or review contact is recorded.
- Approval evidence is archived.
- Final directory listing URL is recorded.

## Live connector checks

- Directory listing resolves publicly.
- Connector details match the final submitted name and description.
- Any account requirement language is accurate.
- Public docs, support, and privacy links resolve successfully.

## Post-listing smoke checks

- `/mcp-claude` still exposes the frozen nine-tool contract.
- Minimum three documented example flows still work.
- If auth is enabled, reviewer/demo account state is rotated or preserved according to policy without breaking the live setup path.
- If Claude Code support is claimed, direct connection still works after listing.

## Regression notes

- If the connector is only valid for Claude.ai/Desktop under a specific network/auth posture, keep that limitation explicit in listing/support materials.
- Any post-approval changes to auth, tools, or public behavior should be treated as a re-review risk and documented in the publication status log.
