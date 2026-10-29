---
status: accepted
date: 2026-10-24
supersedes: null
---
# 0007 event@2: workflow event kinds

## Context
The workflow automation design (spec `docs/specs/2026-10-24-workflow-automation-design.md`, §9, §10)
records sign-offs, notices, rejected ingests, roster imports and automated step outputs in the same
append-only log. `event@1` has a closed `kind` enum that lacks them.

## Options
1. Add the kinds to `event@1` in place. Breaks consumers that treat the enum as exhaustive.
2. Bump to `event@2` with the extra kinds; keep `event@1` in `contracts/v1/` for history.
3. A separate log per workflow. Splits the audit trail.

## Decision
Option 2 (owner approved the spec, 2026-10-24). `event@2` adds the kinds `signoff`, `notice`,
`check`, `registration` (instructor and engagement references from a roster import) and `step`
(an `auto` step's output hash). The shape is unchanged; the closed enum makes the addition breaking.

## Consequences
No live log exists yet, so there is nothing to migrate. `contracts/v1/event.schema.json` keeps the
@1 text unchanged. Payloads for the new kinds are defined by the contracts that introduce them
(`signoff@1` and later), not by this record.
