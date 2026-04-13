# OpenClaw Design-Partner Operations

This document defines how to run the first 5 OpenClaw design partners as a
small, high-touch beta rather than a loose install list.

## Program Goals

- reach 5 active beta users
- turn onboarding into a repeatable checklist
- collect structured product feedback, not just bug reports
- identify whether `capture_only` or `augment_context` should remain the
  recommended default

## Partner Roster Template

Track each partner with:

- partner name
- primary operator
- contact channel
- environment type
- OpenClaw host version
- package version installed
- mode:
  - `capture_only`
  - `augment_context`
- onboarding status
- active-in-last-7-days:
  - yes
  - no
- top issue
- top win

## Status States

Use these states consistently:

- `invited`
  - partner has been selected but not scheduled
- `scheduled`
  - onboarding session booked
- `onboarding`
  - active install/setup/validation work in progress
- `active`
  - partner meets the active-user definition from the onboarding runbook
- `blocked`
  - technical or operational issue prevents normal usage
- `paused`
  - partner intentionally stopped testing

## Weekly Operating Cadence

Run this cadence once per week during the private beta:

1. Review each partner against the active-user definition.
2. Triage any blocked partners into a named support thread.
3. Capture one product win and one friction point per active partner.
4. Decide whether a partner should stay on `capture_only` or trial
   `augment_context`.
5. Summarize risks before inviting any new partner.

## Feedback Categories

Collect feedback under these headings:

- install friction
- auth/config confusion
- memory search quality
- project command usability
- context augmentation quality
- backend reliability
- operator observability gaps

This keeps feature requests separate from incident work.

## Go / No-Go Questions For Expanding Beyond 5 Partners

Do not widen the beta cohort until these questions have acceptable answers:

1. Can operators install and validate without live engineering help?
2. Are search and ingest failures diagnosable from the current docs/runbooks?
3. Is support load staying small enough for a high-touch beta?
4. Is one mode clearly safer as the recommended default?

## Current Beta Limitation Notes

- The current beta relies on operator-managed deployment, not a hosted control
  plane.
- The repo does not yet expose a fully automated support bundle export; support
  collection is still partially manual.
- The backend contract is stable enough for beta, but public-beta/GA packaging
  and support expectations are still out of scope for this phase.
