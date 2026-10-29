---
status: accepted
date: 2026-10-27
supersedes: null
---
# 0023 Framework v1.1: the 0.2.0 draft promoted, and the phase 6 attestation

## Context
Phase 6's gate (spec v0.2, Build phases) reads: one partner instructor cleared remotely, one SME module taken through to
delivery, then a v1.1 revision of the standard. On 2026-10-27 the head of training stated, in the session that
built the gate report:

- they use a previously delivered SME programme, taken through to delivery, as the real-world evidence, and attest that
  the framework is fit for purpose;
- they reviewed the framework document and approve its promotion from draft to v1.1.

The clearance rules expire a clearance, and retire an observation, judged against another framework major (spec v0.2,
Clearance expiry; `rules._other_major`). Moving from 0.2.0 to 1.1.0 changes the major, so taken literally the promotion
would expire every clearance and observation on record, and the staffing check would block everyone, although the
content did not change.

## Decision
1. `standards/framework.yaml` becomes version 1.1.0, status active, effective 2026-10-27. The domains, levels, rubric
   anchors and thresholds are unchanged; the rubric and the rules name framework 1.1.0. Thresholds keep their basis
   (decision 0002 is not engaged: nothing was changed).
2. The rules gain `framework_compatible_majors: ["0"]`: what was judged against a 0.x framework stays in force under 1.x,
   because 1.1.0 is the same content approved. A later major revision that changes the content expires them as the spec
   says, unless its own decision record declares otherwise. `tests/test_rules.py` pins the edge.
3. `standards/attestations.yaml` records both statements by role (head of training), date and this decision, with no
   name. `teachermodel gates` meets phase 6 when a partner clearance rests on observations from recordings, the framework
   is at 1.1 or later, and the SME delivery is attested.

## Consequences
- Clearances and observations already on record, in the pilot store and in simulated stores, stay in force.
- New clearances, observations and calibration exercises record framework 1.1.0. Pages that show the version (the
  self-assessment) change their inputs and reopen once; in the pilot store, dev mode re-signs them.
- The rubric anchors still carry their "draft wording" comment: calibration may refine the wording within 1.x, as a minor
  revision.
