---
status: accepted
date: 2026-10-25
supersedes: null
---
# 0014 event@4 and subject@2: the quality loop

## Context
Increment 3 (`docs/plans/2026-10-25-increment-3-plan.md`, "Machine contracts") builds W6 audit, W7
coaching, W8 quality, W9 CPD, W10 bench, W11 partner and W12 unit readiness. Four streams work in
parallel against fixed contracts, so the contracts are decided here and the streams do not change them.
Three things are missing from increment 2's contracts:
- W8 imports outcome summaries, and `event@3` has no kind for them;
- four new workflow units of work are not instructors: a coaching cycle, an audit sample, a bench review
  and a staffing override. `subject@1` names only candidate, assignment and exercise;
- the audit, coaching, CPD, outcome and bench-decision kinds already sit in the `event@3` enum, but
  have no payload contract, so `check_event` validates nothing for them.

## Options
1. Overload existing kinds (an outcome as a `check`, the child subjects as `step` events). Hides
   outcome data from `verify-events` and gives payloads no schema.
2. Bump to `event@4` (kind `outcome`) and `subject@2` (four kinds), add one payload schema per kind,
   and keep the earlier versions in `contracts/v1/` and `contracts/v3/`, pinned by hash.
3. Keep outcomes outside the log, in the private store. Splits the audit trail and loses append-only
   history.

## Decision
Option 2 (the plan's fixed contracts), as decision 0011 did for `event@3`.

**event@4** adds the kind `outcome` and nothing else. **subject@2** adds `cycle`, `sample`, `bench` and
`override`, with these attrs and URI rules (`check_event` enforces the URI, as it did for the increment 2
kinds):

| subject_kind | URI | attrs |
| --- | --- | --- |
| `cycle` | `tm:cycle/<instructor-slug>--<number>`, from attrs | `{instructor, coach, number, intensity: standard\|triggered, focus: [domain ids], trigger?}` |
| `sample` | `tm:sample/<quarter>--<observation id>`, from attrs | `{observation, instructor, observer, quarter, second_observer}` |
| `bench` | `tm:bench/<instructor-slug>--<n>`, slug of attrs.instructor | `{instructor, reason: contract-end\|repeated-trigger\|requested}` |
| `override` | `tm:override/<16 hex>` | `{instructor, unit, mode, date, request_ref}` |

Every new kind carries `attrs.instructor`, so the engine resolves a need on an instructor-subject step
for them exactly as for the increment 2 kinds (`workflow.CHILD_KINDS`). The `workflows@1` subject enum
gains the four kinds (a backward-compatible minor change), as does the auto-step `per` registry.

**Payload contracts**, each checked by `check_event` and closed (`additionalProperties: false`):
`audit@1`, `coaching-cycle@1`, `cpd@1`, `outcome@1` and `bench-decision@1`, with the fields of the plan's
table. They hold references, hashes, shares and dates only. `outcome@1` carries aggregates and no learner
identity, ever; the import contract `outcome-import@1` (a hub candidate) refuses any such field at every
level. A bench rationale, CPD activity text and feedback text stay in the private store under keys.

**Additive changes within a major**, each keeping its id: `clearance@1` gains an optional `scope`
`{partner?, regions?}` (W11; absent means unscoped, so every earlier payload validates), and `people@1`
gains an optional `coaches: [tm:instructor/...]` on a row holding the `coach` role. `flows.common.coaches_of`
reads it and replaces "every coach coaches everyone"; a coach with no `instructor` mapping is ignored for
the observer and clearer limits, which are about instructor URIs.

**Privacy:** the bench decision is a different use from coaching and clearance (decision 0005), so
`tm:purpose/bench-decision` is drafted in `standards/privacy/purposes.yaml` with a review note: legal needs
a separate purpose, basis and notice line before W10 holds real data. The file stays a draft. Both
jurisdiction profiles list the new purpose in `lawful_bases` (the cross-check requires it). Editing the
files reopens legal verification by design.

## Consequences
No live log exists, so nothing is migrated. `contracts/v3/event.schema.json` keeps the `event@3` text and
`contracts/v1/subject.schema.json` the `subject@1` text, both unchanged and pinned in
`tests/test_quality_contracts.py`. The record adapters `records.audits`, `cycles`, `cpd`, `outcomes` and
`bench` exist as stubs with final signatures; streams F, G, H and I write the bodies. A new subject kind
or a new attr needs a new `subject` major, and a breaking change to any payload needs a new major and a
decision record.
