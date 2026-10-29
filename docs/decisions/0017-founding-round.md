---
status: accepted
date: 2026-10-27
supersedes: null
---
# 0017 A founding round lets the first clearers of a unit decide

## Context
A clearer decides a clearance only within their modules (spec v0.2, Users and roles). `flows/clearance.py` `holds_unit`
enforces this: the clearer must hold a clearance in force for the candidate's unit on the day they sign. Clearances come
only from `clearance` events, and W4 issues them only on two clearers' decisions. A unit nobody holds yet, which is every
unit of a new programme, can therefore never get its first clearance. Until now only seed data got past this
(`scripts/e2e_fictional.py` and the pilot's `dev-autosign` appended clearance events "from before the log"). Nothing let
real founding clearances in.

The head of training considered two mechanisms on 2026-10-27:
- a **recognised prior clearance**: the head signs off an existing clearance with a private evidence reference (spec,
  build phase 3: "enter existing clearances"). This puts in force a clearance with no observations, dry run or clearers in
  the log, which breaks the acceptance criterion that every clearance links to them, and it is a second way in to audit.
- a **founding round**: W4 runs in full and only the "within their modules" gate is waived, while the unit has too few
  holders for W4 to run otherwise.

## Decision
The founding round. The head of training chose it, with any calibrated clearer as a decider (no list of named founders).

1. A round is **founding** on a day when fewer than two clearers could decide on the candidate under the ordinary rule
   (`clearance.unit_deciders`): clearers by level, other than the candidate's instructor (by URI, people mapping or
   mailbox), calibrated that day (`rules.is_calibrated`, audit referrals included) and holding the unit that day
   (`holds_unit`: any mode, the previous version under W12, and never a clearance a blocking bench decision followed).
   Two is the number of clearers W4 needs (spec, Domain model: "clearers (2)"). It is structural, not a threshold
   (decision 0002).
2. In a founding round a clearer who holds no clearance for the unit may make `clearer-decision-1` or `-2`
   (`clearance.within_modules`). The page pool and the content check both apply it, the content check on the day of
   signing. A clearer under a blocking bench decision (exit, return to co-teaching) never decides under the waiver.
3. Nothing else is waived: the evidence minimum (two observations by two calibrated observers, a passed dry run), the
   calibration of each clearer on the day, not the instructor, two different people, the coach limit, and the head of
   training on disagreement.
4. A clearance a founding round issues carries `founding: true` (clearance@1, an optional field added within major 1 as
   `scope` was in decision 0014). It is set when at least one of the two clearers held no clearance for the unit on the
   day they decided. A clearance without it was decided under the ordinary rule.
5. The waiver closes by itself once two calibrated clearers other than the instructor hold the unit, and opens again only
   if that stops being true (expiry, a lapsed calibration, a bench decision).

## Consequences
- Every clearance stays backed by evidence in the log, so the acceptance criteria hold for founding clearances too.
- To start a unit, the programme needs at least three calibrated clearers: the roster's baseline level (clearer, set once
  at first import) and a passed W5 calibration make one. Candidate X is decided by Y and Z, then Y by X and Z, after which
  the ordinary rule applies to Z.
- Until they are cleared, instructors already teaching a unit are a flagged gap in the gap list. The head of training can
  override a staffing block for one delivery (decision 0015).
- A unit whose clearers never get cleared on it stays founding. The `founding` mark on each clearance it issues makes this
  visible to an audit.
- The E2E and `dev-autosign` no longer append seed clearances for clearers. Their clearers decide under the waiver.
- `tests/test_founding.py` pins the edges: zero or one other holder (founding), two (ordinary), the day of signing, an
  uncalibrated holder, the instructor, a bench decision, and the mark.
