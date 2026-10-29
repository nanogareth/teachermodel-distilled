---
status: accepted
date: 2026-10-24
supersedes: null
---
# 0008 Unit references replace module references

## Context
Teachable content is owned by the curriculum system and published as `sl:unit/<slug>@<version>` (spec §9.2). The v1
contracts reference `(tm|sl):module/<slug>` with no version, so a clearance or dry-run could not bind
to the version of the content it was earned on.

## Options
1. Keep `module` and loosen nothing. Clearances stay unversioned.
2. Rename the field to `unit` and require `^sl:unit/[a-z0-9-]+@[0-9]+$`, bumping `staffing-check`,
   `observation` and `roster` to @2.
3. Accept both forms during a transition. Needless: no live data exists.

## Decision
Option 2 (owner approved the spec, 2026-10-24). Every `module` field in `staffing-check`,
`observation` and `roster` becomes `unit` with the pattern above. `rules.py` dataclasses and
parameters follow, and `standards/templates/module.yaml` becomes `unit-requirements.yaml`
(what teachermodel reads from a curriculum unit). The @1 schemas stay unchanged in `contracts/v1/`.

## Consequences
A v1 document with `module` or a `tm:module/` reference is rejected by the v2 schemas. A new unit
version needs its own clearance and dry-run. `event@2` (0007) carries the observation payload by
the same rule.
