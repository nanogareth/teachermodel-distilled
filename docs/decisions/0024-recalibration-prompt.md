---
status: accepted
date: 2026-10-28
supersedes: null
---
# 0024 The head of training is prompted to recalibrate a clearer

## Context
A clearer observes and decides clearances only while calibrated (spec v0.2, Rules: clearer renewal). A calibration lapses
when its renewal period ends, or the day an audit refers the observer back to calibration (W6, decision 0015), and a lapse
moves a clearer back to cleared (`levels`). Getting it back needs a new exercise, and only `teachermodel open-exercise`
opened one: nothing in the queue told the head that a clearer needed one. A simulated store built on 2026-10-28 showed the
cost. An audit referral on 2026-10-12 lapsed one of four clearers, nobody opened an exercise for them, and gate G4 (four
calibrated clearers) went unmet. The owner asked the same day for the step in the head's queue ("Automate all setup and
processes", 2026-10-26: the system prepares the page, a person decides).

## Decision
1. The auto step `tm:step/open-recalibrations` (programme, refreshed) opens a `recalibration` subject (subject@2, a kind added
   within major 2, `tm:recalibration/<16 hex>`, attrs `instructor` and `exercises`) for each registered instructor who holds
   clearer, or held it and is at cleared since. It opens one only for an instructor who:
   - is not calibrated 30 days from today: a renewal coming due, an audit referral, or never passed. The 30 days are an
     operational default (decision 0002), `calibration.RENEW_AHEAD_DAYS`;
   - has no exercise awaiting its result;
   - has no blocking bench decision (they are cleared again before they observe, decision 0015).
2. The head of training gets `tm:step/recalibration-exercise`, due in 14 days (operational default), with these
   fields:
   - one of the exercises already on record, whose recording and private reference scores are used again (those the
     instructor has not scored are listed first);
   - a second observer from the other clearers, current or lapsed, with no blocking bench decision.
   On approval the hook opens the exercise as `open-exercise` would, and both observers get their scoring page. It is
   decided once (a single-decision step).
3. The URI derives from the instructor and the number of exercises that listed them. When any exercise lists the instructor
   (this page or `open-exercise`), or the need is gone, the step writes a system `check` {result: closed} on the
   recalibration, and the engine stops listing it (`workflow.is_closed`). A failed exercise therefore leads to a new
   recalibration, never the old one again.
4. With no exercise on record yet, the page is not written. Its problem names `open-exercise`, because the first pre-scored
   recording and its reference scores come from the head (phase 2).
5. `dev-simulate` opens exercises itself only for the phase 2 rehearsal (the first ten weeks). Renewals and lapses after that
   go through this page, which the simulated head signs like any other.

## Consequences
- A lapse or a coming renewal appears in `teachermodel next` for the head, with a page that does the opening.
- An instructor who held clearer and lapsed is offered as a second observer. A calibration exercise does not need its
  observers to be calibrated: each is scored against the reference (spec W5).
- `tests/test_recalibration.py` pins the edges. They cover:
  - a renewal 28 and 32 days ahead (in and out of the 30 days);
  - a never-passed clearer and a lapsed one moved back to cleared;
  - a bench block, and an exercise awaiting its result;
  - the page: its signer, choices and refusals;
  - the exercise opened on the same reference, the closure, and a failed exercise leading to a new recalibration.
