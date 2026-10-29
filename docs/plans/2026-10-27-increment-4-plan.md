# Increment 4: the views, instructor rights and gate checks

Status: built, 2026-10-27 (all seven items; decisions 0021, 0022) (owner: "unlock everything and keep developing"). Spec v0.2 sections Interfaces, Architecture,
Privacy (instructor rights), Build phases and Acceptance criteria.

## Why now

Every workflow is built, and `teachermodel dev-simulate` (decision 0020) gives a store with six months of realistic
records. What was waiting for data is the part of the spec that reads it: the views, the index behind them, the
instructor's own record with replies and appeals, the audit trail, and the checks for the phase gates and acceptance
criteria. Real data stays blocked on the new tenant and legal review; none of this needs it, and all of it is tested
on simulated stores.

## Items, in order

| # | Item | Spec | Done when |
| --- | --- | --- | --- |
| 1 | `teachermodel gates`: each phase gate and acceptance criterion computed from the store, with the evidence or the shortfall | Build phases, Acceptance criteria | every criterion that data can show is computed; the others say who attests them; tested on simulated stores |
| 2 | `teachermodel index`: the disposable SQLite index, rebuilt from the log and the reference files | Architecture: Index | tables for instructors, clearances, observations, cycles, outcomes, audits, CPD, bench, overrides; rebuilt identically from source |
| 3 | Views, written by the tick as static HTML in the store, one slice per role | Interfaces | clearance matrix, coaching log, quality review, instructor record; filters and flags as specified; outcomes hidden below the minimum learner count |
| 4 | Instructor reply and appeal on every decision | Privacy: instructor rights | a reply page per decision for the instructor; an appeal opens a head-of-training decision; both shown on the record |
| 5 | `teachermodel history --clearance <uri>`: the clearance's full history from the log alone; `audit-export` for a quarter | Acceptance: the log reproduces any clearance | the history names every observation, dry run, decision and event in order, with no other source |
| 6 | Paper fallback: printable run sheet and rubric, and late entry of a paper record without loss | Acceptance: system down | the observe page accepts a session date before the page opened, within a bound; printable sheets generated per unit |
| 7 | Expert-to-session template (phase 6) | Build phases 6 | the handoff template in `standards/templates/`, rendered per unit from the unit file |

Each item ships with tests, runs on a fresh `dev-simulate` store, and is committed on its own.

## Not in this increment

Real data, the Graph app, partner reports (they need a purpose), the hub contracts, and any AI assistance.
