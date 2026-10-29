# Increment 2 (W2 observation, W3 dry-run, W5 calibration, W4 clearance): plan

**Goal:** every step from a lead-observed instructor to a clearance and a working staffing check.
Software proposes everything it can; people only score, sign and decide.
**Spec:** workflow-automation design §8 (rows W2-W5), §12; spec v0.2 W2-W5 and Rules.
**Verify:** `py -m pytest`; `py scripts/e2e_fictional.py`; `teachermodel validate`.

**Order:** K0 first (here) → B, C, E in parallel (each in its own worktree) → merge and review → D →
integration review → push.

**Lesson applied:** parallel implementers invent incompatible contracts. Every shape that crosses a
stream is fixed below, and K0 builds it before anyone fans out.

## Machine contracts (fixed; streams must not change them)

**Child subjects** are opened by a new event kind, `subject` (event@3, decision 0011):
- `subject_uri` is the new subject;
- `actor` is the system or the signer;
- the payload is `{subject_kind, attrs, opened_by}`, where `opened_by` is the opener's step id.

| subject_kind | URI | attrs | Opened by |
| --- | --- | --- | --- |
| `candidate` | `tm:candidate/<instructor-slug>--<unit-slug>-<ver>--<mode>` | `{instructor, unit, mode}` | K0 auto step `open-candidates` (one per registration `delivers` unit × mode, for instructors at `lead-observed` or above) |
| `assignment` | `tm:assignment/<16 hex>` | `{candidate, instructor, unit, mode, observer, length, lead, delivery_ref, recording_ref?}` | B, from an approved assignment batch |
| `exercise` | `tm:exercise/<16 hex>` | `{unit, rubric_version, recording_ref, observers: [...], reference_key}` | E, from the `teachermodel open-exercise` CLI (head of training) |

**Engine (K0):**
- `workflow.subjects` includes the child subjects. The schema's subject enum gains the three kinds.
- A need from a child subject on an instructor step resolves to `attrs.instructor`; a need on a
  candidate step from an assignment resolves to `attrs.candidate`.
- `applies_to` works on child subjects through their `attrs`.

**Payload contracts** (K0 writes the schemas; `events.check_event` validates each kind):

| Kind | Contract | Payload |
| --- | --- | --- |
| `observation` | `observation@2` (+ optional `assignment`, `delivery_ref`, `recorded_at`) | written by B on release |
| `dry_run` | `dry-run@1` | `{candidate, instructor, unit, mode, passed, checks: {id: pass\|fail}, failure_injected, fallback_exercised, environment_sha256, signoff_id}` (C) |
| `calibration` | `calibration@1` | `{exercise, observer, unit, rubric_version, within_one_share, exact_share, passed, signoff_id}` (E) |
| `clearance` | `clearance@1` | `{clearance (tm:clearance/<16 hex>), candidate, instructor, unit, modes, outcome, conditions, recheck, clearers: [2], observations: [ids], issued, expires, framework_version}` (D) |

**Record adapters:** each stream owns its own module in the `records` package; nobody edits
another's.
- `records/observations.py`, `dry_runs.py`, `calibrations.py` and `clearances.py`.
- Each turns events into the `rules.py` dataclasses: `rules.Observation`, `rules.DryRun`, calibration
  dates, `rules.Clearance`.
- K0 writes the signatures with `NotImplementedError` bodies and the tests' import paths.

**Due rules (K0):**
- Registry: `src/teachermodel/due.py` with `@due_rule("name")`. Each rule has the signature
  `(step, subject, events, today) -> date | None`.
- `workflow` resolves a rule-name `due` through the registry, and `validate` checks the names.
- The `rules.DUE_RULES` tuple goes. Streams register their rules in their own flow modules.

**Field kinds (K0):** in `pages.py` and `base.html`, with browser tests.
- `evidence_score`: a score of 1-4 with rubric anchors, a required note, and an optional recording
  timestamp.
- `checklist`: items, each pass or fail with a note.
- `number`.
- The note text goes only to the private store. Events carry hashes and keys.

## K0. Groundwork (one agent, this checkout)
- [x] event@3 with the `subject` kind (keep v2 in `contracts/v2/`, pinned), and decision 0011.
- [x] The engine child-subject support and need resolution above.
- [x] The payload schemas, wired into `events.check_event`.
- [x] The `records` package stubs.
- [x] The `due.py` registry.
- [x] The three field kinds.
- [x] `standards/workflows/pathway.yaml` with the auto step `open-candidates` (programme subject,
  re-runs while its needs are met). It needs `lead-observed-level` done for the instructor; the
  candidates come from registration `delivers`.
- [x] Units: `standards/units/<slug>@<ver>.yaml`, a local, pinned mirror of curriculum units
  (`unit-requirements` shape), and `units.load(uri)`. Move the example there.
- Done: suite and E2E green; `validate` ok. As built (contracts unchanged unless noted here):
  - `open-candidates` needs `tm:step/roster-import`, not `lead-observed-level`: a programme step cannot ask about every
    instructor, and an instructor may start at lead-observed and never take that step. The runner tests each
    instructor's latest level (`flows/pathway.py`).
  - `subject@1` `opened_by` also accepts `tm:cli/<command>` (for E's `open-exercise`); `check_event` requires a subject
    event's URI to fit its kind (a candidate's is derived from its attrs, `workflow.candidate_uri`).
  - `dry-run@1`: `failure_injected` is the failure_catalogue id or null; `passed: true` needs all checks `pass`, a failure
    injected and the fallback exercised.
  - `records.dry_runs(events, units)`: `units` maps a unit URI to its current `environment_sha256`.
  - Beyond the list: `pages.evidence_score_fields(standards)` (one required field per domain, for B and E).

## B. W2 observation (worktree)
- [x] `standards/workflows/observation.yaml`:
  - `propose-observations` (auto, per candidate). Pairs come from clearers, never the instructor;
    at most one may be the instructor's coach. The rotation is hash-ranked and deterministic.
    It plans enough observations to meet `rules.clearance` minimums, with at least one full lead
    observation.
  - `assignments-approved` (human coordinator, `batch_approve`, `bind: input`). On approval,
    ingest opens the `assignment` subjects.
  - `observe` (human observer, per assignment). The page uses `evidence_score` per framework domain,
    plus length, lead, mode and timestamps.
  - `self-assessment` (human instructor, per assignment).
  - `release` (auto, per assignment). Once every assignment sharing a `delivery_ref` has an
    accepted observation, it writes the `observation` events (blind until then; spec W2) and
    stores the notes privately.
- [x] `records/observations.py`, plus a due rule for the observation window (operational default).
- Tests cover blindness (no observation event while the second observer is pending), a coach as
  the second observer refused, and the instructor never observing themself.

## C. W3 dry-run (worktree)
- [x] `standards/workflows/dry-run.yaml`: `dry-run` (human clearer, per candidate) on a `checklist`
  page built from the unit file: preflight items, a run-sheet walk, one failure from
  `failure_catalogue` chosen and handled, and the fallback exercised.
- [x] Approval writes a `dry_run` event with `environment_sha256` = the hash of the unit's
  `environment`, `failure_catalogue` and run sheet. A dry run counts only while that hash matches.
- [x] `records/dry_runs.py`. Tests cover a passed dry run, a changed environment voiding it, and
  no failure injected meaning not passed.

## E. W5 calibration (worktree)
- [x] `teachermodel open-exercise` (head of training). It writes the `exercise` subject and stores
  the reference scores privately, never in events or on observer pages.
- [x] `standards/workflows/calibration.yaml`:
  - `calibration-score` (human observer, per exercise), using the `evidence_score` page;
  - `calibration-result` (auto), computing `rules.calibration_pass` per observer against the
    reference and writing `calibration` events.
- [x] Due rule `clearer_renewal` (`rules.calibration.renewal_months`).
- [x] `records/calibrations.py`, feeding `rules.is_calibrated`.
- Tests cover pass and fail at the thresholds, reference scores never appearing on a page, and
  renewal coming due.

## D. W4 clearance and staffing (after B, C and E are merged; Opus)
- [x] `standards/workflows/clearance.yaml`:
  - `evidence-ready` (auto, per candidate), running `rules.clearance_check` over
    `records.observations`, `dry_runs` and `calibrations`;
  - `clearer-decision-1` and `clearer-decision-2` (human, two different calibrated clearers, not
    the instructor);
  - `head-resolves` (only on disagreement);
  - `issue` (auto), writing the `clearance` event with expiry.
- [x] Due rules `clearance_expiry` and `conditional_recheck`.
- [x] The gap list reads clearances (carry-over 15).
- [x] `teachermodel staffing-check --instructor --unit --mode --date` returns staffing-check@2 from
  `records.clearances`.
- [x] E2E: an instructor goes from lead-observed to cleared, and the staffing check flips from block
  to ok.
- Done: suite and E2E green; `validate` ok. As built (contracts unchanged):
  - A **round** is the unit of decision: evidence-ready writes a `step` event with the verdict detail and the evidence
    hash, and the decision pages are bound to it (`bind: input`). A new round opens when an undecided round's evidence
    changes, after not_yet (or a lapse) when the evidence changes, for a conditional clearance when the evidence changes
    (the recheck), and `warn_expiry_days` before a clearance in force expires (the renewal). `tm:clearance/<round id>`.
  - Decision 2 follows decision 1 and goes to the other clearers; the content checks refuse the instructor (any URI or
    mailbox), an uncalibrated signer (on the signing day), the first clearer again, a second coach, evidence that no
    longer meets the minimum, and an outcome without what it needs. The spec's coach limit is on observers; it is applied
    to the clearers too (a coach may be one of the two).
  - The hook of decision 2 skips `head-resolves` (system `step`, `skipped`) when the outcomes agree; agreeing conditional
    decisions join their conditions and take the earlier recheck.
  - `clearance.conditions` holds keys (`clearances/<hex>.json#conditions/<n>`); the words stay in the private store.
  - `recheck-lapse` (auto) writes the superseding not_yet; `records.clearances` keeps the latest event per id.
  - `rules.clearance_check` detail also names the observation ids that counted.
  - `staffing.check(events, request, rules)` is the pure function; the command exits 0 ok, 3 warn, 2 block, 1 a request
    outside the contract (changed from "0 ok or warn" in the integration review).
  - The gap list step now refreshes. Level moves: `standards/workflows/levels.yaml` (`propose-levels`, `levels-decided`)
    proposes moves to and from cleared and clearer (below).
- [x] Integration review fixes (D's half; the bridge, sign-off and observation halves are the other stream's):
  - `issue` re-checks the round's evidence and issues nothing while it fails (a blocked `check`, "evidence no longer meets
    the clearance minimum: ..."). The evidence hash covers the passed dry runs and the unit's environment hash, so a voided
    dry run (and the run that replaces it) opens a new round. Round ids count the earlier rounds (A, B, A is not deduped).
  - The decision date is the sign-off's `signed_at`: calibration, the clearer's own clearance and the recheck are judged on
    it. A `signed_at` before the day the round opened is refused; one more than a day after the time of ingest is refused
    when the caller puts that time in `st.cache["now"]` (`clearance.NOW_KEY`; the bridge bounds `signed_at` generically).
  - head-resolves refuses a signer who is not a people-list head of training or who is the candidate's instructor (URI,
    mapping or roster mailbox). D1 and D2 signers, coaches and calibrations are compared after normalising through the
    people mapping (`clearance.person_key`, `same_person`).
  - A clearer decides only within their modules (spec, Users and roles): they need a valid clearance for the candidate's
    unit, in any mode, on the decision date (the page pool uses the round's date).
  - A renewal round counts only observations dated after the renewed clearance was issued (`since` on the round).
  - Framework major versions: `rules.staffing_check` blocks (with a reason) a clearance judged against another framework
    major; `rules.clearance_check` counts only observations whose rubric version has the current major
    (`rules.framework_version`). `rules.Observation.rubric_version` and `rules.Clearance.framework_version` are optional
    fields; `records.clearances` fills the latter, `flows/clearance.py` fills the former from the log until
    `records.observations` does.
  - The staffing check warns ahead of a conditional recheck (the same `warn_expiry_days` window).
  - Levels: `levels-decided` is one approve page with an approve-or-decline field per row (not a batch page:
    `signoff.BATCH_STEPS` requires every row approved). cleared -> clearer needs a valid clearance and a current calibration;
    clearer -> cleared is proposed when a passed calibration has lapsed, cleared -> lead-observed when a clearance once in
    force is on record and none is valid (a roster level with nothing in the log is not demoted). The hook recomputes the
    proposal and skips a row no longer proposed. The `propose-levels` step id counts the earlier proposals.
  - W5: an exercise needs two or more observers; `calibration` events carry an optional, additive `inter_observer`
    agreement (against each other, W5 step 2; never part of pass or fail). The result `step` event records
    `renewal_months`, which `clearer_renewal` reads, so a store run against another root uses that root's rules.
  - The coach limit applied to the two clearers is an OPERATIONAL DEFAULT (decision 0002): the spec's rule is on observers
    (recorded in the basis of `clearer-decision-2`).
  - E2E: the two bootstrap clearers hold pre-log clearances (seed data, replacing the contractor's seeded level change);
    the SME goes lead-observed -> cleared (W4) -> calibrated (W5) -> clearer (the head's approval) and then observes the
    professional's candidate.

## Open questions
- Resolved 2026-10-25: observations in any mode count; only the dry run must match (decision 0013).

## Deferred
A coordinator page for ad-hoc assignments (the CLI only proposes for now); W6-W12 (increment 3);
legal items 11, 15 and 16 from the jurisdiction review.
