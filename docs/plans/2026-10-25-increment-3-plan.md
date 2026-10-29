# Increment 3 (W6 audit, W7 coaching, W8 quality, W9 CPD, W10 bench, W11 partner, W12 unit readiness): plan

**Goal:** the quality loop. Every cleared instructor stays in coaching. Audits keep observers
honest, outcomes trigger coaching rather than benching, and a bench decision rests on a complete
evidence pack. Partners and new units move through the same pathway.
**Spec:** v0.2 W6-W12 and Rules; workflow-automation design §8; decisions 0003, 0005, 0013.
**Verify:** `py -m pytest`; `py scripts/e2e_fictional.py`; `teachermodel validate`.

**Order:** K1 here → F, G, H and I in parallel worktrees → merge and integrate → J (carried items,
here) → integration review → push.

## Machine contracts (fixed; streams must not change them)

**event@4** (decision 0014) adds the kind `outcome`, for imported outcome summaries (aggregates
only).

**subject@2** (decision 0014) adds four child-subject kinds:

| subject_kind | URI | attrs | Opened by |
| --- | --- | --- | --- |
| `cycle` | `tm:cycle/<instructor-slug>--<n>` | `{instructor, coach, number, intensity: standard\|triggered, focus: [domain ids], trigger?}` | G: auto `open-cycles` (every active instructor at lead-observed or above) |
| `sample` | `tm:sample/<quarter>--<observation-id>` | `{observation, instructor, observer, quarter, second_observer}` | F: auto `draw-sample` once a quarter (`rules.audit_sample`) |
| `bench` | `tm:bench/<instructor-slug>--<n>` | `{instructor, reason: contract-end\|repeated-trigger\|requested}` | I: auto `open-bench` (engagement end within 30 days, or two quality triggers on a triggered cycle), or the CLI `teachermodel request-bench` (head of training) |
| `override` | `tm:override/<16 hex>` | `{instructor, unit, mode, date, request_ref}` | J: CLI `teachermodel request-override` |

**Payload contracts:**

| Kind | Contract | Payload |
| --- | --- | --- |
| `audit` | `audit@1` | `{sample, observation, observer, second_observer, within_one_share, exact_share, agreed: bool, referred_to_calibration: bool, signoff_id}` |
| `coaching_cycle` | `coaching-cycle@1` | `{cycle, instructor, coach, number, intensity, focus, phase: opened\|feedback\|practice\|closed, change?: {domain: delta}, signoff_id?}` |
| `cpd` | `cpd@1` | `{instructor, activity_key, domains: [ids], hours, logged_on, signoff_id}` (activity text in the private store) |
| `outcome` | `outcome@1` | `{delivery_ref, instructor, unit, mode, delivered_on, learners_assessed, score, baseline, feedback?, feedback_median?, source}`; no learner identities, ever |
| `bench_decision` | `bench-decision@1` | `{bench, instructor, decision: renew\|convert\|return-to-co-teaching\|exit, rationale_key, evidence_pack_sha256, decided_by, signoff_id}` |
| `clearance` | `clearance@1`, additive | optional `scope: {partner?: tm:org/..., regions?: [codes]}` (W11) |

**Quality triggers:**
- H writes a `check` event `{step: tm:step/quality-review, instructor, result: "trigger", trigger: <reason id>, domain?}` on the instructor subject, one per new trigger. The id comes from (instructor, reason, the latest delivery_ref).
- G reads these triggers to set the next cycle's intensity and focus.
- I counts them for `repeated-trigger`.

**Coaching assignment (G owns):**
- `people.yaml` rows gain `coaches: [tm:instructor/...]`, an additive change to people@1.
- `flows.common.coaches_of(st, instructor)` replaces "every coach coaches everyone", and B's and D's
  coach limits switch to it.

**Records adapters:** `records/audits.py`, `cycles.py`, `cpd.py`, `outcomes.py` and `bench.py`. Each
owner writes its own; K1 writes the stubs.

## K1. Groundwork (one agent, this checkout)
- [x] event@4 and subject@2 (with v3 and v1 copies pinned), and decision 0014.
- [x] The payload schemas above, wired into `events.check_event`; the clearance@1 `scope` field.
- [x] Records stubs, and `coaches_of` (with its people@1 field) so that streams can call it.
- [x] The outcome import contract `contracts/outcome-import.schema.json` (hub candidate):
  `{schema, source, exported_at, deliveries: [{delivery_ref, instructor, unit, mode, delivered_on,
  learners_assessed, score, baseline, feedback?, feedback_median?}]}`. It refuses any field that
  could identify a learner (`additionalProperties: false`).
- [x] Purpose: draft `tm:purpose/bench-decision` in `standards/privacy/purposes.yaml`
  (status draft, review note for legal; spec §legal notes: W10 needs its own purpose). This
  reopens legal verification by design.
- Done: suite and E2E green; `validate` ok.

## F. W6 audit (worktree)
- `draw-sample`: an auto step that runs once a quarter. The second observer is a calibrated clearer,
  not the first observer, the instructor or the instructor's coach. Selection is hash-ranked.
- `second-score`: a human step for the second observer, scoring from the recording reference with
  the evidence_score page. The first observer's scores are never on that page.
- `audit-result`: an auto step that computes agreement and writes an `audit` event.
- Low agreement (below the calibration thresholds) refers the first observer back to W5. It writes
  a `check` result `refer-to-calibration`, and `records.calibrations` treats the observer as not
  calibrated from that date until their next passed calibration.
- Tests:
  - the sample matches `rules.audit_sample`;
  - second-observer eligibility;
  - blindness;
  - referral lapses the calibration.

## G. W7 coaching and W9 CPD (worktree)
- **Coaching (W7):**
  - `open-cycles`: an auto step that opens the next cycle when the previous one closed, or when
    `rules.coaching_overdue` says it is due. Intensity is triggered when H's trigger events exist
    since the last cycle, with focus = the trigger domain, or the two lowest averaged domains.
  - The cycle steps, per `standards/coaching-protocol.md`:
    1. observe: reuses W2 through an assignment, with the coach as observer;
    2. feedback: human, the coach, within 5 working days;
    3. practice task: human, the coach;
    4. re-observe: an assignment again;
    5. close: auto, records the change in the focus domains.
- **CPD (W9):** a CPD plan seeded from the lowest-scoring domains across recent observations. The
  instructor logs activities on a page; an activity counts toward a domain gap, and the next cycle's
  close keeps or closes that gap.
- **Coach limits:** `coaches_of` is wired into W2 proposals and the W4 coach limits (replacing
  "every coach").
- Tests: cadence edges (91 days and 30 days), triggered intensity, a cycle closing with a change,
  and CPD seeding.

## H. W8 quality (worktree)
- `teachermodel import-outcomes <file>`: validates outcome-import@1, refuses learner identifiers,
  and writes `outcome` events (deterministic ids by delivery_ref).
- `quality-review`: an auto step per instructor after each import and monthly. It runs
  `rules.quality_triggers` and writes trigger `check` events. The minimum learner count hides
  metrics, and an outcome alone never opens a bench.
- Tests:
  - the rule edges (10 points, 2 consecutive deliveries, 15 learners);
  - a domain at 1 confirmed by a second observer;
  - learner fields refused at import.

## I. W10 bench, W11 partner, W12 unit readiness (worktree)
- **W10:**
  - `open-bench`: the triggers above.
  - `evidence-pack`: an auto step that writes `generated/bench/<slug>.html`, a self-contained HTML
    pack with clearances, observations from at least two observers, outcomes, coaching history
    and CPD. Notes are referenced, never pasted into events. It records `evidence_pack_sha256`.
  - `bench-ready`: auto, `rules.bench_ready`.
  - `bench-decision`: human, head of training. Return-to-co-teaching is the default for a
    teaching-quality reason. The rationale is required and stored privately. A `level_change`
    follows for return-to-co-teaching and exit, through the existing hook pattern.
- **W11:** a partner candidate (registration type partner) clears with
  `scope {partner: organisation, regions: registration regions}`. All its observations and its dry
  run must be from recordings (an observation `length` or flag `from_recording` true; check
  observation@2 and add an optional `from_recording` field if needed, additive). The staffing check
  honours scope: a scoped clearance does not cover other partners or regions.
- **W12:** a unit file gaining a new version opens dry-run candidates for its SME authors.
  `standards/units` entries gain an optional `authors` field. It reuses W3, with no new decision
  logic.
- Tests: the bench needs an evidence pack and two current observers, return-to-co-teaching
  lowers the level, a scoped clearance blocks staffing outside its scope, and a new unit version
  opens a candidate.

## J. Carried items (here, after the merge)
- [x] Staffing override (spec Rules):
  - `teachermodel request-override` opens an `override` subject.
  - `override-decision`: human, head of training, with the reason required and stored privately.
  - An approved override turns `staffing_check` from block to ok for exactly that instructor, unit, mode and date, with the
    override id in the response reasons.
- [x] Bench outcomes stop staffing: an exit or a return to co-teaching blocks the staffing check until a clearance is issued
  after the decision (decision 0015, amended).
- [x] Audit second observer re-checked at signing; a sample whose second observer stops being eligible is voided and its
  quota refilled from the next-ranked observation (decision 0015, amended).
- [x] Coach observation pages carry the optional `from_recording` field into the observation event.
- [x] A coordinator page for ad-hoc observation assignments: an assignment opened from a page, not only by proposals
  (`assign-observer`, a separate step, reopened after each approval).
- [x] `gap-list-approved` gets `bind: input`.
- [x] `purposes.yaml`: workflow files that exist leave `planned_workflows`, and `validate` refuses a planned id that exists.
- [x] E2E: bench decision blocks staffing, an override opens it for exactly one date, a bench exit blocks it again.

## Deferred
- Hub items, filed when Track D's inbox exists: outcome-import adoption by `engagement/`, and the
  staffing gate in `delivery/`.
- PDF evidence packs: built 2026-10-27 for bench reviews (`teachermodel export-pack`). Partner reports wait on a
  purpose that covers sending a pack to a partner.
