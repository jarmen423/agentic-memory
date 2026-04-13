# OpenAI Demo Account Checklist

Use this only if the OpenAI submission uses an authenticated MCP surface.

## Account requirements

- Reviewer login path is already provisioned and tested.
- Login requires no MFA, SMS code, email magic link, VPN, or company-network access.
- Credentials are stable for the full review window and do not expire immediately.
- Account contains realistic sample data for:
  - code search
  - conversation memory retrieval
  - explicit memory writes
  - research memory retrieval or write validation

## Reviewer materials

- Username or email is recorded in the internal submission packet.
- Password is recorded in the internal submission packet.
- Any required org, workspace, or project selector is preconfigured.
- If OAuth is used, callback and consent flow have been tested outside internal networks.
- Reviewer instructions fit in one short paragraph and do not require back-and-forth with the team.

## Hard rejection risks from OpenAI docs

- Credentials do not work from the public internet.
- Reviewer is forced to create a new account.
- MFA or another inaccessible second factor is required.
- Demo data is empty, unrealistic, or does not support the provided test prompts.
- Credentials expire before review completes.

## Recommended prep

- Create one dedicated reviewer account, not a personal employee account.
- Seed it with exact artifacts referenced by `TEST_PROMPTS.md`.
- Re-test login and all prompts from a clean browser session before submission.
