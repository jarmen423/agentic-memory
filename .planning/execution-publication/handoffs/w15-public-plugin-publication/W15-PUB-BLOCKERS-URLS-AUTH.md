# Publication Blockers Follow-Up: URLs and Auth

## Status

- Partially resolved

## What Changed

- Added public publication/legal/support/DPA pages to `am-server`:
  - `/publication/agentic-memory`
  - `/publication/privacy`
  - `/publication/terms`
  - `/publication/support`
  - `/publication/dpa`
- Wired the Codex plugin manifest to the new public URLs.
- Updated OpenAI and Anthropic publication docs to reference the new canonical
  URLs.
- Locked the public authenticated publication posture to OAuth 2.0
  authorization code flow in the publication docs.

## Verified

- `python -m pytest tests/test_am_server.py -q -k "publication or health"`
- `Get-Content .codex-plugin/plugin.json | ConvertFrom-Json | Out-Null`

## What Is Now Resolved

- The repo no longer depends on GitHub blob pages as the planned public legal
  and support URLs.
- The auth/network decision is no longer ambiguous in the publication packet.

## What Still Remains

- The new publication routes must be deployed to the live
  `api.agenticmemory.com` host before the URLs are truly usable in submission
  forms.
- OAuth is chosen, but not yet implemented in `am-server`; current runtime auth
  is still bearer-key based.
- Reviewer/demo account provisioning and end-to-end OAuth validation are still
  outstanding.
