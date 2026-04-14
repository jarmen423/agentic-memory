# Public Policy Checklist

Current as of April 12, 2026.

This checklist defines the minimum public policy and legal surface needed before Agentic Memory is submitted for OpenAI or Anthropic directory review.

## Required stable public URLs

These must be public, non-placeholder, and controlled by the product team. GitHub blob links are acceptable for internal drafts only, not as final publication URLs.

- Privacy policy URL
- Terms of service URL
- Support/contact URL
- Company or product website URL

## Privacy policy minimum content

The public privacy policy should explicitly cover:

- What Agentic Memory stores:
  - code memory
  - conversation memory
  - research memory
  - review/demo account data if applicable
- What user-related data may appear in tool inputs and outputs
- Why the data is processed:
  - retrieval
  - indexing
  - explicit memory writes
  - service operation and abuse prevention
- Who receives the data:
  - internal service operators
  - required infrastructure providers
  - no public third-party publishing as part of the current public tool contract
- Retention and deletion rules
- User controls for correction, deletion, or support requests
- Contact point for privacy questions

## Data-boundary statements that should appear clearly

- Public tools do not post to the public internet.
- The public tool surface does not expose internal admin/indexing tools.
- State-changing tools write only to Agentic Memory's private backend state.
- The service should not collect:
  - payment card data
  - PHI
  - government identifiers
  - raw credentials or secrets
- The service should not return unnecessary internal identifiers such as request ids, trace ids, or debug payloads to end users.

## Terms of service minimum content

- Description of the service and acceptable use
- Availability/no-warranty posture appropriate for the current product stage
- Limits on misuse, abuse, and policy-violating content
- Suspension/removal rights for abuse or security issues
- Contact path for support and legal notices

## Support/contact minimum content

- Public support email or support form
- Expected support scope:
  - install/connectivity issues
  - review/demo account issues
  - bug reports
  - privacy requests
- Business identity or operator name shown consistently with the publication name

## Cross-platform notes

- OpenAI explicitly requires privacy policy and support contact details. Terms and company URLs are part of the current submission package.
- Anthropic directory submission also expects privacy/support materials and a reviewer-ready setup path.
- Both platforms benefit from stable public pages that do not move between review and launch.

## Canonical publication URLs

- Website: `https://mcp.agentmemorylabs.com/publication/agentic-memory`
- Privacy: `https://mcp.agentmemorylabs.com/publication/privacy`
- Terms: `https://mcp.agentmemorylabs.com/publication/terms`
- Support: `https://mcp.agentmemorylabs.com/publication/support`
- DPA: `https://mcp.agentmemorylabs.com/publication/dpa`

## Remaining blockers on April 12, 2026

- The canonical URLs are implemented in `am-server`, but they still need deployment to the live public host.
- No final retention/deletion wording is captured in publication docs yet.

## Exit criteria

- Final public URLs exist and are controlled by the team.
- The privacy policy and terms match the actual hosted public tool behavior.
- Support/contact details are consistent across OpenAI, Anthropic, and Codex-facing metadata.
