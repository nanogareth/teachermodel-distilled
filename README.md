# teachermodel

Instructor development infrastructure for a technical training function: who may teach what,
on what evidence, and how instructors keep improving. Spec v0.2 (experienced-engineer edition).

- **Spec:** [`docs/specs/2026-10-23-instructor-development-spec-v0.2.md`](docs/specs/2026-10-23-instructor-development-spec-v0.2.md).
- **Standards (machine-readable):** `standards/` — framework, rubric, rules, protocols, unit-requirements schema, `standards/units/` (pinned curriculum unit mirrors), and `standards/workflows/` (one workflow per file).
- **Contracts:** `contracts/` — JSON Schemas for events, observations, rules, framework, staffing check,
  roster import (template and fictional example in `standards/templates/`).
- **Rules engine:** `src/teachermodel/rules.py` — clearance check, calibration, audit sample,
  quality triggers, coaching cadence, bench readiness, staffing check.
- **Evidence:** `docs/evidence/` — what was adopted (strong) and deferred (moderate/weak).
- **Decisions:** `docs/decisions/` (MADR).
- **Plan:** `docs/plans/phase-plan.md`.
- **Hub alignment:** `docs/hub-alignment.md` (hub conventions).

I built a system to run instructor clearance in my own work, then rebuilt it here on generated data so anyone can
inspect it. The original has been in use since 2025 with 14 instructors, in a separate private repository that shares
no data with this one. Nothing real has run on this rebuild, by design.

## Quick start (Windows)

```powershell
py -m venv .venv; .venv\Scripts\activate
py -m pip install -e . pytest
py -m pytest
teachermodel validate
```

## Reviewing this repository

Read these in order. Each one explains the next.

1. **Purpose:** [the spec](docs/specs/2026-10-23-instructor-development-spec-v0.2.md), its purpose, scope and design
   principles. Where it disagrees with `standards/`, `standards/` wins.
2. **Why the rules are what they are:** [the evidence summary](docs/evidence/2026-10-23-ttt-evidence-summary.md) and
   [decision 0002](docs/decisions/0002-strong-evidence-only.md). Only findings rated strong change a rule; anything
   else is labelled an operational default.
3. **The rules:** [`standards/rules.yaml`](standards/rules.yaml), then
   [`src/teachermodel/rules.py`](src/teachermodel/rules.py), which holds pure functions with no model in the path.
4. **The proof:** [`tests/test_rules.py`](tests/test_rules.py). The test names state the policy.

To follow one rule from end to end, take the two observers a clearance needs. The evidence summary gives the finding
(Ho & Kane 2013), decision 0002 adopts it, `standards/rules.yaml` sets `min_distinct_observers: 2`, `clearance_check`
enforces it, and `test_one_observer_twice_is_not_enough` tests the edge.

`py -m pytest tests/test_rules.py` runs those rules alone. The full suite took about 19 minutes on one process when
last timed.

The plan and several decisions list what a live deployment would still need, such as IT setup and legal review. They
describe that deployment, not work under way here.

## Data rules

Personal data (names, evidence notes, recording links) never enters git. It lives in the private
store outside any git working tree, set by `TEACHERMODEL_PRIVATE_DIR` (decision 0006). The event log carries references only.
