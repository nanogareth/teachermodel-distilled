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

## Quick start (Windows)

```powershell
py -m venv .venv; .venv\Scripts\activate
py -m pip install -e . pytest
py -m pytest
teachermodel validate
```

## Data rules

Personal data (names, evidence notes, recording links) never enters git. It lives in the private
store outside any git working tree, set by `TEACHERMODEL_PRIVATE_DIR` (decision 0006). The event log carries references only.
