# Expert-to-session handoff: $title

Unit `$unit_id` (spec v0.2, Build phases 6: an SME module taken through to delivery). Rendered by `teachermodel handoff`
from the unit file; the expert and a clearer complete it together before the first dry run.

## What the session must achieve

$outcomes

Delivery modes: $modes. Environment: $environment

## What the expert brings

Tick each item when it exists in the unit's source repository.

- [ ] A worked example for every topic the pre-check covers, so learners who miss a question have something to study.
- [ ] A demonstration script, with the exact commands and the output each one should give.
- [ ] A lab with expected outputs, and pre-computed outputs to fall back on when the model or the sandbox fails.
- [ ] The failure modes learners will hit, each with how to inject it at the dry run and how the instructor handles it.
- [ ] The misconceptions the expert sees most, each as a wrong answer a diagnostic question can catch.

## The session, as a plan

| Block | Minutes | What happens |
| --- | --- | --- |
| Pre-check | 10 | Run the diagnostic questions; route each topic by the result (skip or add the worked example). |
| Worked example | 15 | Only for the topics the room missed. |
| Demonstration | 15 | The script, live, with one injected failure handled in front of the room. |
| Lab | 40 | Learners build; the instructor diagnoses failing environments and keeps the cohort moving. |
| Conceptual question | 10 | Vote, peer discussion, revote, on a question whose wrong answers map to the misconceptions below. |
| Debrief | 10 | Address each wrong answer; name what to practise next. |

## What the unit file holds now

Pre-check:

$pre_check

Misconceptions:

$misconceptions

Failure catalogue:

$failure_catalogue

## Still missing before the dry run

$missing

## Readiness route

1. The expert is registered as an instructor and named in the unit's `authors`: a candidate opens for each delivery mode
   (W12).
2. A clearer runs the dry run against the run sheet and the failure catalogue (W3); `teachermodel paper --unit $unit_id`
   prints both.
3. The first lead delivery is observed by two calibrated observers (W2), and two clearers decide (W4).
