---
status: accepted
date: 2026-10-24
supersedes: null
---
# 0011 event@3: child subjects

## Context
Increment 2 (`docs/plans/2026-10-24-increment-2-plan.md`, "Machine contracts") adds workflows whose
unit of work is not an instructor: a candidate (one instructor, unit and mode), an assignment (one
observation of a candidate) and an exercise (one calibration recording). Each needs its own subject
URI and attributes, opened by the workflow that creates it. `event@2` has no kind that says "this
subject now exists", so the engine could not list such subjects from the log.

## Options
1. Derive child subjects from existing kinds (a `step` event with a subject payload). Overloads
   `step`, whose payload is an auto step's output hash, and hides the subject from `verify-events`.
2. Bump to `event@3` with a `subject` kind; keep `event@2` in `contracts/v2/`, pinned by hash.
3. Keep child subjects outside the log (a table in the private store). Splits the audit trail and
   loses append-only history.

## Decision
Option 2 (the plan's fixed contract). `event@3` adds the kind `subject`. Its `subject_uri` is the new
subject, its actor is the system or the signer, and its payload is
`{subject_kind, attrs, opened_by}` (`subject@1`; `opened_by` is the opener's step id). The shape of
the event is otherwise unchanged; the closed enum makes the addition breaking.

## Consequences
No live log exists, so nothing is migrated. `contracts/v2/event.schema.json` keeps the @2 text
unchanged, pinned in `tests/test_contracts.py`. The workflow engine lists child subjects from
`subject` events; a workflow that writes them lists `subject` in its `event_kinds`. The kinds
`candidate`, `assignment` and `exercise` are defined by the plan; a new kind needs a new schema
version of `subject`.
