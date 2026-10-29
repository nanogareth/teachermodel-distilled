# Phase plan

Status: active, 2026-10-23. Phases and gates from spec v0.2, Build phases.

| Phase | Work | Gate | State |
| --- | --- | --- | --- |
| 0 Scaffold | Repo, PROJECT.yaml, standards drafts, contracts, rules engine with tests | `teachermodel validate` passes; rule tests green | done (2026-10-23) |
| 1 Baseline | Roster by instructor type; existing observation notes, feedback, per-instructor results | Roster and gap list agreed | next |
| 2 Standard | Finalise framework, rubric anchors, dry-run and coaching protocols, rules, module template | Two clearers score three pre-scored recordings and meet calibration | |
| 3 Records | Private store, event writers per kind, index build (SQLite), observer form, instructor record, clearance matrix | Every active instructor has a record; every delivery maps to a clearance or flagged gap | |
| 4 Pathway, calibration, coaching | TtT programme, level progression, calibration exercises, clearer gating, coaching log | 4+ calibrated clearers; one instructor per type through the pathway; all active instructors in a cycle | |
| 5 Quality loop | Outcome imports, quality review, triggers, audit sampling, CPD, evidence packs, staffing check contract live | One quarter end to end; audit scored; every trigger actioned | |
| 6 Scale | Remote clearance, partner pack, expert-to-session template | One partner cleared remotely; one SME module delivered; standard v1.1 | framework v1.1.0 approved and SME delivery attested by the head of training, 2026-10-27 (decision 0023) |

## Next actions (phase 1)

- [x] Resolve decision 0004: the deploying organisation controls the data of its deployment
  (2026-10-24, amended 2026-10-28).
- [x] Choose the private store location and its backup: decision 0006 accepted (restricted
  SharePoint library, nightly copy, quarterly restore test).
- [x] Build the workflow tooling (increment 1, `docs/plans/2026-10-24-workflow-automation-increment-1.md`):
  engine (`next`), sign-off pages and ingest, connector bridge (plan, receipt), setup workflow, W1
  onboarding through the level change. `py scripts/e2e_fictional.py` runs the whole chain on
  fictional data, outside the repo.
- [ ] Set up 0006: create the library and security group, sync it, set `TEACHERMODEL_PRIVATE_DIR`,
  add the nightly copy. `teachermodel run` writes the IT request (markdown and `.eml`); IT confirms
  on a generated page.
- [ ] Add the processing to the record of processing activities; ask the DPO whether a DPIA is needed.
  `teachermodel run` generates the record from the contracts; the DPO signs the screening on a
  generated page.
- [x] Draft the roster import format as a contract: `contracts/roster.schema.json`, template and
  fictional example in `standards/templates/`, `teachermodel check-roster <path>`.
- [ ] Issue the privacy notice. The text and per-instructor drafts are generated; rendering waits on
  decision 0005 and the retention periods. Sending is yours; the daily check records `given_on`
  from Sent Items, and W1 data collection starts only after it.
- [ ] Set the retention periods in `standards/retention.yaml` with legal advice (decision 0002:
  operational defaults must be labelled as such). The notice refuses to render while any is null.
- [x] Resolve decision 0005: option 1, managers and reviews see clearance status, never scores
  (head of training, 2026-10-24).
- [ ] Real data waits on four things: 0005 accepted, retention periods set, the IT library and
  group in place, and the notice approved and sent. Then run `teachermodel import-roster`.
- [x] Open items from the tooling: the daily scheduled `tick` (Windows task, 07:30) and mailbox read (desktop task,
  06:00), the bracket and attachment probes, and the Outlook check of a generated `.eml` (owner, 2026-10-27).
  The shared-mailbox read stays open until a shared sign-off mailbox exists.
- [ ] Record three calibration recordings with reference scores (needed for phase 2 gate).

## Build increments (workflow automation)

Spec: `docs/specs/2026-10-24-workflow-automation-design.md` §12.

| Increment | Scope | State |
| --- | --- | --- |
| 1 | Engine, sign-offs, connector bridge, setup workflow, W1 | done 2026-10-24 (pushed) |
| 1b | Owner checks: probe email, Outlook `.eml`, scheduled `tick` | done 2026-10-27 (owner); shared mailbox open |
| P1-P2 | Privacy by jurisdiction: IE base, US-CA overlay, retention per purpose, bound approvals | done 2026-10-24; profiles await legal |
| 2 | W2 observation, W3 dry-run, W4 clearance and staffing check, W5 calibration, level progression | done 2026-10-25 (pushed); plan `docs/plans/2026-10-24-increment-2-plan.md` |
| 3 | W6 audit, W7 coaching, W8 quality, W9 CPD, W10 bench, W11 partner, W12 unit readiness, staffing override | done 2026-10-25 (pushed); plan `docs/plans/2026-10-25-increment-3-plan.md`; decisions 0013-0015; bench purpose awaits legal |
| Graph driver | Python driver for the admin-consented app (`teachermodel graph-read`) | built 2026-10-27, fixture-tested; live once IT registers the app in the new tenant |
| Dev simulation | `teachermodel dev-simulate`: a complete simulated store, months of generated use on the real standards (decision 0020) | built 2026-10-27 |
| 4 | Gate report, SQLite index, views, instructor replies and appeals, clearance history and audit export, paper fallback, expert-to-session template | built 2026-10-27; plan `docs/plans/2026-10-27-increment-4-plan.md`; decisions 0021-0022; a simulated store passes 15 of 19 criteria |

## Parallel work streams

The shared hot spots are `standards/workflows.yaml` (all workflows in one file),
`src/teachermodel/app.py` `PAGE_SPECS` (all page builders in one dict) and the event `kind` enum.
Two agents editing them at once collide. Stream A removes that, and then increment 2 fans out.

**Owner and people (start now, no code):**

| Item | Who | Unblocks |
| --- | --- | --- |
| Retention periods | legal | notice text |
| Send the generated IT request | you, then IT | private store, real data |
| DPIA screening | DPO | roster import |
| Send yourself one `[tm-signoff probe]` mail with a `.json` attachment; open one `.eml` | you | 1b |
| Record three reference-scored calibration recordings | head of training, two clearers | phase 2 gate, W5 |
| Confirm teachermodel owns instructor identity | Hub owner | hub staffing gate |

**Agent streams, in order of dependency:**

| Stream | Scope | Model | Depends on | Isolation |
| --- | --- | --- | --- | --- |
| A Enabling refactor | One file per workflow under `standards/workflows/`; page builders registered per workflow module (`src/teachermodel/flows/`); event kinds declared per workflow and checked by `validate`. No behaviour change: the E2E script and the suite must pass unchanged. | sonnet | integration review fixes | this checkout |
| B W2 observation | observer form page (full and 15-minute, blind until both submit), observation events (`observation@2`), recording reference via `meeting.recording` | sonnet | A | worktree |
| C W3 dry-run | checklist from `unit-requirements.yaml` failure catalogue, validity by unit version, clearer sign-off | sonnet | A | worktree |
| D W4 clearance | two-clearer decision page, `rules.clearance_check` wiring, clearance events, expiry and recheck as `DUE_RULES`, staffing check served from events | opus (the decision rules and the staffing gate are the core of the system) | A; reads B and C event shapes | worktree, merged last |
| E W5 calibration | calibration exercise pages, agreement statistics, clearer-role grant and renewal | sonnet | A | worktree |
| F Graph driver | `graph` driver behind the same plan and receipt contracts, recorded-fixture tests; web-verify `msal` before pinning | sonnet | none (contract is fixed) | worktree |
| G Prose review | notice, ROPA and IT request templates for plain English; mark legal points | opus | none | this checkout, templates only |
| H Hub items | hub: adopt `plan`/`receipt`/`signoff`/`queue` as `sl:` contracts; crawler reads JSON Schema `$id` | sonnet | none | their own repos and sessions |

Carried into increment 2 from the increment 1 integration review: the gap list must read clearance
events once W4 writes them, and the gap list and notice text must re-run after a later roster
import (stream D); `standards.ROOT` resolves only under an editable install, so package
`standards/` and `contracts/` as data before any non-editable install (stream A).

Run B, C and E together after A, then D. F, G and H can run at any time. Each stream gets one
implementer and one reviewer, and an integration review over the merged increment, as increment 1 did.

## For internal legal (from the AI-assisted profile drafts, 2026-10-24)

The full review notes are in `standards/privacy/jurisdictions/{ie,us-ca}.yaml` and
`standards/privacy/purposes.yaml`. The points that change what we build:

- **A DPIA is likely required.** Three WP248 criteria apply: evaluation or scoring, systematic
  monitoring, and employees as vulnerable data subjects. The DPC list (item 4) may also apply.
- **A California risk assessment probably applies.** 11 CCR 7150(b)(4) covers inferring work
  performance from systematic observation, including video. It is due before processing starts,
  and submissions to the CPPA by 1 April 2028.
- **No purpose rests on consent.** EDPB 05/2020 para 21 names assessment forms as an example of
  consent that is not freely given. Legitimate interest needs a balancing test per purpose, and the
  notice must show the Art. 21 right to object.
- **Bench decisions need their own purpose, basis and notice text** before W10 holds real data. The
  0005 wording covers only coaching and clearances.
- **An Art. 14 notice is also needed,** because observers' scores and HR roster data come from
  others, not from the instructor.
- **Automated decisions:** confirm whether the staffing-check block is a solely automated decision
  (GDPR Art. 22) or ADMT for work allocation under the CCPA rules.
- **California applicability:** the overlay applies only if the organisation is a CCPA "business". Check
  whether Gov. Code 12946 (4-year personnel records) and Labor Code 1198.5 (inspection) cover
  clearance and coaching records.
- **Gaps in the data model:**
  - outcome summaries have no data category yet (W8, increment 3);
  - observers' own data in calibration needs notice coverage.
- **Sources the drafter could not reach:** EUR-Lex, irishstatutebook.ie and leginfo. The drafts
  used secondary or compiled copies, and flagged each case.

## Carried into increment 3 (from the increment 2 reviews)

- **Owner decision:** do observations in one delivery mode count toward a clearance in another? Today
  they count in any mode; only the dry run must match the mode.
- **Spec rule not yet built:** the head of training overrides a staffing block, with a recorded
  reason (spec, Rules).
- **Coaches:** coach-to-instructor assignment is not modelled. Every coach counts as everyone's
  coach, so the coach limits are conservative.
- **Coordinator page:** a page for ad-hoc observation assignments. Today proposals are automatic,
  then the coordinator approves them.
- **Stale approval:** `gap-list-approved` is not bound to the refreshed gap list.
