# Publication Revision Response Checklist

Use this checklist when OpenAI or Anthropic requests changes during review.

## Intake

- Record the review source: `OpenAI` or `Anthropic`
- Record the request date and reviewer/case reference
- Paste the exact reviewer request into the relevant status file
- Classify the request as one of:
  - metadata/docs only
  - legal/support URL issue
  - auth or account provisioning issue
  - transport/reachability issue
  - tool contract or annotation issue
  - product behavior issue

## Triage

- Confirm whether the request reopens any completed wave task
- If code changes are required, create a new explicit execution thread rather than silently editing finished packet docs
- Identify which public claims must be updated immediately to remain truthful
- Update:
  - `docs/publication/status/OPENAI_REVIEW.md` or `docs/publication/status/ANTHROPIC_REVIEW.md`
  - `docs/publication/status/EVIDENCE.md`
  - `docs/publication/status/LAUNCH_GATE.md` if the request reopens a gate

## Response Package

- Record the exact files changed
- Record the verification commands run
- Attach screenshots, links, or emails that resolve the request
- Draft the reviewer response with:
  - what changed
  - where it was verified
  - any remaining constraints or caveats

## Closure Check

- Confirm the reviewer-facing URLs are still live and accurate
- Confirm auth behavior still matches the declared public posture
- Confirm tool annotations and public tool inventory still match production behavior
- Mark the request as resolved in the relevant status file
- Append the resolution date and evidence link to `EVIDENCE.md`
