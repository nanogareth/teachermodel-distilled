---
status: accepted
date: 2026-10-27
supersedes: null
---
# 0018 A staffing override names the partner and region of its occasion

## Context
The staffing check takes an optional `partner` and `region` (staffing-check@2, increment 3, W11): a clearance scoped to a
partner or to regions covers only a request that names them. A staffing override (decision 0015) recorded only the
instructor, unit, mode and date, and the block it was decided on was computed with no partner or region. Two faults
followed:

- **A scope block could not be overridden.** The check's scope reason names the partner and region of the request, so
  it never equalled the reason recorded on an override computed with none, and the override lifted nothing.
- **An override lifted too much.** An override decided on "no valid clearance" lifted that block for a request naming
  any partner or region, because that reason reads the same with or without them.

The head of training asked on 2026-10-27 for partner and region arguments on `request-override` (open since the
increment-3 handover).

## Decision
1. `request-override` takes optional `--partner tm:org/<slug>` and `--region <ISO 3166 code>`, with the same patterns
   as the staffing check's request. They go into the override subject's attrs (subject@2, two optional properties added
   within major 2, as `scope` was added to clearance@1 in decision 0014).
2. The block an override is decided on is computed for the request's partner and region, so a scope block can be
   overridden for the partner it names.
3. An override lifts a block only for a request with the same instructor, unit, mode, date, partner and region. An
   override with neither lifts only a request that names neither. This is the spec's "exactly" (Rules), extended to the
   two fields that now describe a delivery. It fails closed. Approved by the head of training, 2026-10-27.
4. A request with neither partner nor region keeps the override URI and the decision-page inputs it had before this
   decision, so an override already open or decided is unchanged.

## Consequences
- Delivery scheduling must ask for an override with the partner and region it will pass to the staffing check. An
  override asked without them does not cover a partner's delivery.
- `records.overrides` and `rules.Override` carry `partner` and `region` (None when not named).
- `tests/test_override.py` pins the edges: an override with neither against a request naming one, an override for a
  partner and region against another partner, another region, or none, and a scope block overridden.
