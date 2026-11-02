# 0032: An observer sees how they lean against the calibration reference

Date: 2026-11-01. Status: accepted (owner, 2026-11-01: "Yes and continue through all steps until complete", on building
G7; the choices below are the builder's). The panel passed review on generated data (owner, 2026-11-01, "Signed off").

## Context

The `calibration` event keeps shares only, by design: within-one and exact agreement, pass or fail. An observer who
fails, or who passes narrowly, cannot tell whether they score high or low, or on which domain. The inputs exist in the
private store: their signed scoring page and the exercise's reference.

## Decision

1. **Computed when drawn, stored nowhere.** `flows.calibration.observer_detail` reads the sign-off named by each
   `calibration` event and the exercise's reference, and returns own score minus reference per domain
   (`rules.calibration_bias`). No new document and no new event: nothing has to be kept, corrected or erased beyond the
   two documents it comes from. If either is gone, that exercise leaves the average and its agreement stays on the
   chart; the page says how many exercises the average covers.
2. **On My record, for the observer and the head of training.** `my-record` is already own-only for instructors and
   closed to the coordinator (`standards/audience.yaml`), so no policy change. Nothing about it reaches a manager
   (decision 0005) or a clearance decision.
3. **Averaged, unnamed.** The panel shows the average over the last six results (operational default, decision 0002),
   as a diverging bar per domain, then agreement per exercise against the 90% and 60% thresholds. It names no exercise
   or recording, and holds no evidence note. The words pick out the furthest above and below; no new threshold says
   what counts as a lean.
4. **Reported only.** `rules.calibration_pass` alone decides pass or fail; `calibration_bias` feeds no rule.
5. **Generated observers lean.** `devsign.like_a_person` puts one or two domains a point off the reference, which still
   passes, so a generated store has a chart to read. Before this every generated observer matched the reference exactly.

## Consequences

- With one exercise the average is that exercise's difference, so an observer can work out the reference for a
  recording they scored. Recalibration can reuse a recording: the head's page already lists those the instructor has
  not scored first and marks the others `scored_before`. A reused recording tests less than a fresh one, as it did
  before, since the observer has seen it.
- Not done: the observer pool view for the head (each observer's agreement over time, side by side); booking a
  recalibration slot from the panel (it stays on the C4 chain in the Outbox).
