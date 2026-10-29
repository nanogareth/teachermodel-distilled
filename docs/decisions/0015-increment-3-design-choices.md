---
status: accepted
date: 2026-10-25
supersedes: null
---
# 0015 Increment 3 design choices

## Context
Increment 3 (`docs/plans/2026-10-25-increment-3-plan.md`) built W6 audit, W7 coaching, W8 quality, W9 CPD,
W10 bench, W11 partner clearance and W12 unit authors in four parallel streams. Each stream met a question the
spec v0.2 leaves open, and the integration settled how the streams fit together. The head of training
approved these choices with the increment 3 plan on 2026-10-25. None of them changes a threshold in `standards/`
(decision 0002): they decide what the existing rules apply to.

## Decision

**Coach observations live on the coaching cycle.** A coach observes and re-observes as steps of the cycle
subject (`tm:cycle/...`), not through a W2 assignment, because a W2 assignment step cannot be limited to the coach.
There is one observer, so there is no blind release: the coach's sign-off writes the observation. The observation
is the same `observation@2` record as a W2 one, so it counts toward a clearance, under the coach limit
(`rules.clearance.max_coach_observers`, with the coaches per instructor from `people.yaml` `coaches`) and only if the
coach was calibrated on the day. *For instructors:* your coach's visits are real observations. They can count toward
your clearance, but your coach can be at most one of your observers.

**Partners clear on recordings only, within their scope (W11).** A partner instructor (registration type partner)
is cleared only on observations and a dry run scored from recordings (`from_recording: true`); live observations
are listed in the reasons and not counted. The clearance carries `scope {partner, regions}` from the registration,
and the staffing check treats it as covering that partner and those regions only. *For partner instructors:* send
recordings of your sessions; a clearance lets you teach for your own organisation in your own regions, not
elsewhere.

**A bench exit records the decision and closes the candidates.** The spec has no "exited" level, so an exit
writes the `bench_decision` event and a `check` {result: closed} for each of the instructor's candidates, as the
record that their pathway ended; the level is not changed and no level is invented. Return to co-teaching lowers
the level to co-deliver. The exit does not by itself change the staffing check, which still reads the instructor's
clearances until they expire; ending the engagement in the roster is a separate step. *For instructors:* an exit
is written down with its reason, which you can see; nothing about you is relabelled or deleted.

**SME authors are exempt from the lead-observed floor for their own unit (W12).** When a unit gains a new version,
its authors (`standards/units` `authors`) who are registered instructors without a valid clearance for it get a
candidate per delivery mode at once, whatever their level. Every other
requirement of W3 and W4 still applies: a dry run, observations and two clearers. *For subject-matter experts:* you
can start clearing the unit you wrote without first working up the pathway; you are still observed and cleared
like anyone else.

**Below the minimum learner count, no metric triggers.** A delivery with fewer than
`rules.quality.min_learners_for_metric` learners assessed is read by no outcome metric, the feedback trigger
included (`rules.quality_triggers`). It is shown as "insufficient data". *For instructors:* a small group never
starts extra coaching through its results or its feedback.

**An audit referral is prospective.** When an audit refers an observer back to calibration on day D, the observer
is not calibrated from D until a calibration passed after D. Days before D are judged as before:
`records.calibrations` keeps every pass, `records.lapses` holds the referral dates, and `rules.is_calibrated` takes
both. So an observation the observer made before D still counts toward a clearance, and a clearance already decided
on it stands. The calibration renewal falls due on D. *For instructors:* if your scoring as an observer is referred,
you stop observing and clearing until you recalibrate; observations you made before the referral stay valid for
the people you observed.

## Consequences
- `tests/test_coaching.py`, `test_partner.py`, `test_bench.py`, `test_unit_readiness.py`, `test_quality.py`,
  `test_rules.py` and `test_audit.py` pin these choices; changing one needs a new decision.
- A referral could instead have voided the observer's earlier observations (retrospective). That would reopen
  clearances already issued on them, and the audit samples one observation, not the observer's whole quarter.
  Reopen this with evidence (decision 0002) if audits show that referred observers' earlier scores were unreliable.
- The purposes file now lists audit, coaching, CPD, quality and bench under their purposes; its new hash reopens
  legal verification of every jurisdiction profile, by design.

## Amendments (2026-10-25, carried items J)

**A bench exit or a return to co-teaching stops staffing.** This replaces the sentence above that said an exit "does not by
itself change the staffing check". The staffing check reads the instructor's latest `bench_decision` (by the day recorded). When
it is `exit` or `return-to-co-teaching` and was decided on or before the day of the request, only a clearance issued after
the day of the decision counts, for the requested unit and mode; the response is a block with the reason "bench decision:
exit" or "bench decision: returned to co-teaching". A clearance issued on the day of the decision does not lift it. `renew` and
`convert` change nothing, and neither does a decision made after the date asked about (a delivery before it is judged as
before). The level is still not changed by an exit; the block comes from the decision itself. *For instructors:* after an
exit or a return to co-teaching you are not scheduled to teach until you are cleared again; renewal or conversion changes
nothing about your scheduling.

**The head of training can override a staffing block, for one delivery.** The spec says only the head of training can
override a block and that every override records a reason. `teachermodel request-override --instructor --unit --mode --date
[--note]` opens an `override` subject (subject@2, `tm:override/<16 hex>`); the optional note goes to the private store and the
subject holds its key as `request_ref`. The step `override-decision` goes to the head of training (never the instructor
concerned), who approves or rejects and gives a written reason. A hook writes a `check` event {step: override-decision, result:
`granted` or `declined`, override, decided_by, signoff_id, reason_key} (not `approved`/`rejected`: the bridge already uses
`rejected` for a refused sign-off); the reason stays in the private store and never enters the log. An approved override turns a
block into ok for exactly that instructor, unit, mode and date, whatever the block was (no clearance, a retired one, a bench
decision), with the reasons "override tm:override/..." and "overridden: <the block's reasons>"; a warn is not touched, and a
rejected or undecided override changes nothing. A request still open or already approved is not opened again; a rejected one may be
asked again as a new override. *For instructors:* a one-off override lets you deliver on one date without changing your clearances;
the reason is written down by the head of training and is yours to see.

**An audit's second observer is re-checked when they sign, and a sample whose second observer stops being eligible is voided.**
The second observer is chosen on the day of the draw (a calibrated clearer, not the first observer, the instructor or the
instructor's coach). If they have become the instructor's coach, or are no longer a calibrated clearer, by the day they sign,
the content check refuses the second scoring and the sample stays open. On its next run `draw-sample` voids a sample like that
which has no second scoring yet: a `check` {step: draw-sample, result: void, reasons} on the sample, the system's `step` event
marked skipped that closes second-score (second-score is now `bind: input` and `skippable`, so the skip covers the inputs it
was made on), and a `step` {step: audit-result, void: true} that closes audit-result; nothing stays due for it.
We chose this over giving the sample a new second observer because a sample is identified by its quarter and its observation
(`tm:sample/<quarter>--<observation>`) and a subject's attrs are immutable (the first `subject` event for a URI wins), so a
replacement observer would need a second sample for one observation or a changed subject rule. Instead the voided
observation is withdrawn from the quarter's quota, so the same run draws the observer's next-ranked observation in its place
when one exists (a sample with no second scoring yet is the only kind voided; one already second-scored stands). A voided
observation is never drawn again. Open samples of earlier quarters are voided the same way with no replacement. A voided
sample cannot be signed, even if its second observer becomes eligible again. A known side effect of `bind: input`: a change to
the rubric after a sample was second-scored changes the page inputs, so that completed second-score would reopen; samples are
second-scored within weeks, so we accept this until a rubric change is made. *For observers:* you can second-score a sample only
while you are still calibrated and do not coach the instructor; if that changes, the sample is dropped and the audit uses
another of the first observer's observations instead.

**Coach observations can be scored from a recording.** The coach's observe and re-observe pages (W7) carry the same optional
"Scored from a recording" answer as the W2 observe page, and the observation event copies it (`from_recording`, observation@2),
so a partner instructor's coach visits, when scored from recordings, can count for the recording-only clearance of W11. Without
the answer the event says nothing about it, as before. *For coaches of partner instructors:* tick the box when you scored from
a recording; unticked, your observation is a live one and does not count towards a partner's clearance.

**The coordinator can assign an observer outside the proposals.** `assign-observer` is a separate coordinator step on the
candidate (page `approve`): the coordinator picks the observer (the proposals' pool of calibrated clearers, less the instructor),
the length, lead and mode, and may name a delivery reference (else one is derived from the sign-off id). Approval opens one
`assignment` subject through the same opener as the batch approval. No step needs it and it needs only `open-candidates`, so it
neither blocks nor waits for the automatic proposals; it has no due date (it is optional) and reopens after each approval, because
its inputs carry the number of ad-hoc assignments (the pattern of log-activity). On the day of signing a content check applies the
proposals' rules: the observer is a calibrated clearer that day and not the instructor, is not already on that delivery, and no more
of the instructor's coaches than `max_coach_observers` observe one delivery; a reference already used for another candidate is
refused because observers sharing a reference are released together. From then on it is an ordinary assignment, so its observe and
self-assessment steps still need the candidate's batch to be approved (the existing `needs`, pinned by
`test_the_engine_sees_assignments_only_once_the_candidate_is_approved`); approve the proposed batch first. *For observers:* an
ad-hoc assignment looks like any other observation request. *For coordinators:* an extra observer you add counts towards the
instructor's evidence like a proposed one.

**The gap list approval reopens when the refreshed gap list changes.** `gap-list-approved` is now `bind: input`: it is done only
while the newest approving sign-off covers the rows as they are. The gap list refreshes whenever a clearance is issued, lapses or
nears its end, so the owner agrees the list that is current, not the first one. A refresh that leaves the rows as they were
changes nothing and the approval stands. *For the programme owner:* you may be asked to agree the gap list again after clearances
change.

## Amendments (2026-10-25, integration review of increment 3)

These follow the integration review's findings (numbered as the review numbered them). None changes a threshold in
`standards/` (decision 0002); `REPEATED_TRIGGERS` (2) stays an operational default.

**Repeated triggers open a bench review only with teaching evidence (finding 1).** The spec says an outcome alone never causes a
bench decision; counting outcome triggers did. `open-bench` now opens a `repeated-trigger` review only when the instructor's
latest cycle is triggered, the quality-review triggers since that cycle and since their latest review were raised on at least two
distinct deliveries (two triggers of one delivery count once; the delivery is recovered from the trigger's content-derived id, and
a trigger it cannot be traced to does not count), and the teaching itself is in question: one of those triggers is
`domain-one-confirmed` (a domain scored 1, confirmed by a second observer), or a triggered coaching cycle closed after the latest
review with no gain in any of its focus domains. *For instructors:* poor learner results start extra coaching, never a bench
review by themselves; a review needs an observation that confirms the concern, or coaching that has not helped.

**A blocking decision blocks until a later clearance, whatever follows it (finding 2).** This replaces "the staffing check reads
the instructor's latest bench decision" in the amendment above: it reads their latest exit or return to co-teaching decided on or
before the day asked about (`records.bench_blocks.latest_blocking`), and a renew or convert decided after it does not lift it.
Only a clearance issued after the day of that decision counts. `open-bench` opens no review for an exited instructor.

**An instructor with a blocking decision leaves the pools; an exited one gets no new work (finding 3).**
`records.bench_blocks.blocking_decision(events, instructor, on)` is the latest exit or return to co-teaching decided on or before
`on` that no clearance issued after it has superseded. Such an instructor is not in the observer pool (so not a second observer
of an audit either), and a clearer decides only on a clearance issued after their latest blocking decision. An exited instructor
gets no new candidates (also as a unit author), proposals, coaching cycles or quality triggers; one returned to co-teaching is
still coached and reviewed. The exit's `closed` checks now also close the instructor's open coaching cycles, and the workflow
engine honours them (`workflow.is_closed`): a child subject closed by a system `check` {result: closed}, and an assignment of a
closed candidate, has no due step and runs nothing. This replaces "the workflow engine does not read it" above.

**After a blocking decision, clearance evidence starts again (finding 4).** A round counts only observations dated after the day
of the instructor's latest blocking decision (`clearance.evidence_since`, passed to `rules.clearance_check` as `since`); a round
opened before it no longer meets the minimum, so its decisions are refused and the next round, on new observations, supersedes
it. A clearance in force from before the decision no longer stops a new round from opening. *For instructors:* after a return
to co-teaching you are cleared again on new observations, not on the ones the review weighed.

**An override is bound to the block it overrode (finding 5).** The decision page shows the staffing check's detailed block
reasons for the request, and the decision `check` records them (`block`). An approved override lifts the block only while the
check gives exactly those reasons, and only if it was decided on or after the instructor's latest bench decision of any kind
(on or before the delivery date); an override that recorded no block lifts nothing. Approving a request the check does not block
is refused, and `request-override` refuses a date before today (finding 21). *For instructors:* an override covers the situation
the head of training saw; if your clearance or a bench decision changes it, it no longer applies.

**Clearers of the previous unit version clear a new version (finding 9).** For `sl:unit/<slug>@<n>`, a clearer holding a valid
clearance for `@<n-1>` decides within their modules. Without it the authors of a new version (W12) could have no clearer at all.
*For subject-matter experts:* the people already cleared on your unit's previous version can clear you on the new one.

**Delivery scheduling receives clearance status only (finding 12, decision 0005).** `staffing.check` reduces the reasons it
returns to "not cleared" (a block), "clearance expiring" and "recheck due" (a warn) and "override <id>" (an ok on an override).
The detailed reasons (the bench decision, a retired framework, a scope, day counts, what an override overrode) come only from
`teachermodel staffing-check --detail`, for the head of training. The bench-decision purpose's description says the manager
sees clearance status only, and its "never on its own" sentence is now true (finding 1). The purposes file's new bytes reopen
legal verification by design. *For instructors:* the scheduling system learns whether you are cleared, never why not.

## Amendments from the integration review (2026-10-25)

**The audit sample is drawn once, after the quarter closes.** The first run in a quarter draws the quarter that just closed, over all
its live observations read by observation date (one dated in the quarter and released after it ended counts, if released by that
run). Observations released after the draw do not top it up; a voided sample's replacement and a pick that had no second observer
are still completed. The second observer is none of the observers of the sampled delivery (same `delivery_ref`). *For observers:*
you are audited a quarter later, on everything you observed in it; you never second-score a delivery you took part in.

**Coaching runs without gaps.** The next cycle opens when the previous one closes, with step dates inside its period (91 days
standard, 30 triggered, from opening). A quality trigger during a standard cycle switches it to triggered (a `coaching_cycle` event
of its phase with the new intensity and focus; `coaching.derive_cycles` applies it to `st.subjects`). A cycle past 91 days is
stalled: the next opens beside it and the stalled one stays in `next` as overdue. A re-observation is not dated before the first
observation or the day the practice task was set. *For instructors:* there is always a cycle open; a trigger shortens it.

**Ad-hoc assignments do not wait for the batch.** An assignment opened by `assign-observer` stands on its own approval
(`needs_except_opened_by` on its observe and self-assessment steps); this replaces the sentence above that they still need the
batch approved. Joining a delivery whose observations are released is refused.

**Small cohorts are dropped at import; CPD gaps live in the log.** A delivery under the minimum learner count is written with a null
score and feedback and the kept import is the re-serialised document, not the file received. The cpd-plan `step` event carries the
gaps and each cycle-close event `cpd_review: {closed, kept}`; the plan file is rebuilt from them.
