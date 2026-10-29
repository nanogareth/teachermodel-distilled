---
status: accepted
date: 2026-10-24
amended: 2026-10-28
supersedes: null
---
# 0004 Who controls the data of a deployment

## Context
The code, standards, contracts and documents in this repository hold no personal data (0003). A deployment does:
its private store and event log hold records about named instructors. The privacy notice, the record of
processing and the IT request each have to name who is responsible for those records.

## Decision
This applies to every deployment (owner, 2026-10-24, amended 2026-10-28).

The deploying organisation is the controller of the personal data its deployment holds, and the private store and
the event log are under its control (0006). Legal confirms the controller before real data is entered, and again
if the organisation moves to a new tenant or changes structure (0016).

## Consequences
- Real roster data may be entered only in a deployment, subject to the private store (0006) and the privacy
  notice. No real data is in this repository (0003).
- Settings and data specific to one organisation stay in that deployment's private store, outside the repository.
