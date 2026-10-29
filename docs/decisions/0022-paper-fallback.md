---
status: accepted
date: 2026-10-27
supersedes: null
---
# 0022 Paper fallback: printable sheets and late entry of a paper session

## Context
Spec v0.2, Acceptance: "A session can run from the paper run sheet and rubric with the system down, and its record is
entered afterwards without loss." Nothing printed the run sheet or the rubric. And an observation's date may not reach
back before its assignment opened (a guard against backdating into a lapsed calibration), so a session observed on paper
while the system was down, with no assignment yet, could not be entered afterwards.

## Decision
1. `teachermodel paper --unit <uri>` writes a printable run sheet (outcomes, modes, environment, pre-check and routes,
   misconceptions, failure catalogue, each with a tick box) and an observer rubric (the session header, each domain's four
   anchors, boxes for the score and the evidence note) under `generated/paper/<unit>/`. They hold no person's data; the
   header is filled by hand with ids.
2. The coordinator's ad-hoc assignment page takes an optional `held_on`: the day the paper session took place, at most
   14 days before the day of signing (`observation.PAPER_BACKDATE_DAYS`, an operational default under decision 0002) and
   never after it. The assignment carries it (subject@2 assignment attrs, an optional field added within major 2).
3. The observation of such an assignment may carry that date: its lower bound is the earlier of the assignment's opening
   and `held_on`. Nothing else changes: calibration and the clearance evidence are still judged on the observation's own
   date, so a backdated session counts only if the observer was calibrated that day.

## Consequences
- The paper path is complete. Whether a session actually ran from paper is for the head of training to attest; the gate
  report shows the criterion as attested.
- The 14-day window bounds how long a paper record can wait; past it, the session is lost to the record, as it would be
  for any late paperwork.
