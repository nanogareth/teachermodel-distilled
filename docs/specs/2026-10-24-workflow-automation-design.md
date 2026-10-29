# Workflow automation: design

Status: draft for review, 2026-10-24. Covers the phase 1 setup steps and workflows W1-W12 of spec
v0.2. Hub conventions: `docs/hub-alignment.md`; hub spec §6-§8.

## 1. Goal

Every step of every workflow is defined in one file and typed by who does it. The CLI does every
deterministic step, and machine checks cover what people did. People do only the steps that need
judgement, a policy decision or a legal act. They do each one on a pre-filled page whose result is
bound to the hash of what they saw.

## 2. Decisions

- **Three step types.** `auto` steps are done by the CLI. `verify` steps are decided by the CLI
  from data read out of Microsoft 365. `human` steps are done by one named role on a generated page.
  No model is in the decision path; `auto` never means a model.
- **Pages are local.** Self-contained offline HTML, generated into the private store (decision 0006)
  and never committed, because pages carry names. Templates live in git.
- **Microsoft 365 is read-only for now.** The connector holds Mail.Read, Sites.Read.All,
  Files.Read.All, User.ReadBasic.All and the meeting recording and transcript read scopes. It has no
  write scope. The CLI therefore writes everything, people act, and the connector verifies.
  An admin-consented Graph app replaces the connector later as a driver swap (§6), not a rewrite.
- **Messages to people are sent by people** (hub §7). The CLI writes drafts; it never sends.
- **Hub-shaped integration.** Planner -> plan -> driver -> receipt (hub §7). Sign-offs bind to input
  hashes and go stale when inputs change (hub §8).

## 3. Workflow definitions: `standards/workflows/<slug>.yaml` (`tm:contract/workflows@1`, one workflow per file, merged on load)

Each workflow has an id (`tm:workflow/<slug>`), a `basis` and a list of steps. A step has:

| Field | Meaning |
| --- | --- |
| `id` | `tm:step/<slug>`, stable and meaningless |
| `type` | `auto`, `verify` or `human` |
| `role` | spec role that acts (human) or is notified (auto, verify) |
| `subject` | entity kind the step runs per: `programme`, `instructor`, `unit`, `delivery`, `clearance` |
| `applies_to` | optional filter on instructor type |
| `needs` | step ids that must be complete for the same subject |
| `done_when` | event kind plus payload match that marks the step complete |
| `due` | rule name in `rules.py`, or `{days: N}` labelled operational default, or none |
| `page` | page template, for human steps |
| `basis` | `spec` section, decision id, or `operational default` (decision 0002) |

Steps for standards not yet settled in phase 2 carry `basis: operational default`.

## 4. Engine (`src/teachermodel/workflow.py`, pure)

`next(workflows, events, subjects, today) -> list[Due]` returns open steps whose `needs` are met.
Each `Due` holds the step, subject, role, due date, overdue flag and blocking reason. It is a pure
function, unit-tested like `rules.py`. Commands:

| Command | Does |
| --- | --- |
| `teachermodel next [--role R]` | prints the queue; `--json` writes it as `tm:contract/queue@1` |
| `teachermodel run` | executes due `auto` steps and appends their events |
| `teachermodel pages` | regenerates pages for due `human` steps |
| `teachermodel plan` | writes the read plan for due `verify` steps (§6) |
| `teachermodel ingest <file>` | ingests a receipt or a sign-off (§5, §6) |
| `teachermodel tick` | `run`, `plan`, `pages`, `next`, in that order |

**Trigger.** A daily desktop scheduled task runs `tick`. The same session then runs the read plan
through the connector and ingests the receipt. No agent decides when work runs.

## 5. Sign-offs (`tm:contract/signoff@1`, hub candidate)

Fields: `schema`, `id`, `step`, `subject_uri`, `input_sha256`, `decision`, `fields`, `signer`
(`tm:person/` or `tm:instructor/`), `signed_at`, `page_template_sha256`.

**Pages.**
- Pre-filled with everything known.
- Only what changed since the last approval is shown expanded. Batch pages offer "approve all
  unchanged".
- Required fields and enums are checked in the browser; ingest is the authority.
- Saving downloads one JSON file.

**Return channels; signer identity is checked automatically.** Amended 2026-10-24 after the
connector probe (`docs/runbooks/connector-driver.md`): the connector cannot report a file's
`createdBy`, so the library channel stays disabled until the Graph driver, and every role returns
sign-offs by email.
- **Private library** (head of training, programme owner): save into `inbox/` in the
  library. The receipt's `createdBy` is the identity.
- **Programme mailbox** (everyone else): email the file with the subject tag `[tm-signoff <id>]`
  to the owner's mailbox, or to a shared mailbox the owner can read (Mail.Read.Shared). The
  authenticated sender is the identity. Observers never see each other's submissions, which
  keeps W2 blind scoring intact.

**Ingest (fail-closed).** A sign-off is accepted only when all of these hold:
- the schema is valid;
- `input_sha256` equals the hash of the current input (otherwise it is stale, rejected, and the
  page regenerated);
- the signer matches the identity from the receipt, mapped through `identities/`;
- the signer holds the step's role (roles from `identities/people.yaml` in the private store);
- on a step with `signer` (a step on an assignment or exercise, decision 0012) the signer is one named by the
  subject's attrs (`attrs.observer`, `attrs.instructor`, or any listed `attrs.observers` who has not signed yet), and
  holds the role as an instructor: a roster instructor holds `instructor` and, while their latest level is clearer,
  `clearer`; a people-list person is an instructor only through the explicit `instructor` field of their row;
- the content rules the flow registered for the step hold (`flows.content_check`), for example a score of 1-4 and an
  evidence note for every framework domain;
- the id has not been seen before (a repeat is a no-op).

An accepted sign-off appends a `signoff` event. A missing or unreadable receipt leaves the step open.

## 6. Driver bridge (`tm:contract/plan@1`, `tm:contract/receipt@1`, hub candidates)

A plan is a list of read operations, each `{op_id, op, args}`. A receipt returns
`{op_id, status: ok|not_found|error, data}` for each, plus `driver`, `run_at` and `plan_sha256`.

| `op` | Reads | Used by |
| --- | --- | --- |
| `site.library` | library exists, item count | setup |
| `mail.sent` | sent items to a recipient with a tag, since a date | notice, reminders |
| `mail.tagged` | inbox messages with a tag: sender, received, attachments | sign-off channel |
| `file.get` | library file content and `createdBy` | sign-off channel, imports |
| `meeting.recording` | recording reference and timestamps for a delivery | W2, W6 |

**Drivers.** `TEACHERMODEL_M365_DRIVER=connector|graph`.
- `connector`: a Claude session executes the plan verbatim through the connector and writes the
  receipt. It makes no judgement and skips no op; an op it cannot run returns `error`.
- `graph`: a Python driver for the Graph app, with the same contract. It also unlocks reads the
  connector lacks (group membership, library permissions).

Until the Graph driver exists, library permissions are attested by IT on a sign-off page.

## 7. Setup workflow (`tm:workflow/setup`)

| Step | Type | Detail |
| --- | --- | --- |
| IT request | auto | renders the exact request: library, security group, members, no sharing links, audit log |
| IT done | human | IT signs off: group created, permissions set |
| Library exists | verify | `site.library`; local sync path resolves; `TEACHERMODEL_PRIVATE_DIR` set |
| ROPA entry | auto | generated from contracts (data categories), role table (recipients), 0006 (storage) |
| DPIA screening | human | DPO page pre-filled with the processing facts; DPO answers and decides |
| Retention periods | human | owner sets periods on legal advice in `standards/retention.yaml` |
| Notice text | auto, then human | rendered from template, ROPA, retention and 0005 (needs 0005 accepted); owner approves the text hash |
| Notice drafts | auto | one `.eml` per instructor (`X-Unsent: 1`, tag `[tm-notice <version>]`) |
| Notice sent | verify | `mail.sent` per instructor; sets `notice.given_on` to the sent date |
| Roster import | auto | `check-roster`, then identities to `identities/`, references to events |
| Gap list | auto, then human | roster deliveries without clearance; owner agrees it (phase 1 gate) |

## 8. W1-W12

| Workflow | auto | verify | human |
| --- | --- | --- | --- |
| W1 Onboarding | record, baseline form, shadow and co-deliver scheduling | sign-off senders | manager or partner lead confirms; instructor self-assesses |
| W2 Observation | assignment, recording link, blind release once both observers submit | sign-off senders | observer scores; instructor self-assesses and replies |
| W3 Dry-run | checklist from the unit's failure catalogue; lab preflight import; validity check on unit version | sign-off senders | clearer signs off or lists fixes |
| W4 Clearance | `clearance_check`, expiry, staffing-check update | | two clearers decide; head of training resolves a disagreement |
| W5 Calibration | agreement statistics, role grant or renewal | | observers score the reference recording |
| W6 Audit | hash-ranked sample, agreement, referral to W5 | recording available | second observer scores |
| W7 Coaching | cycle creation, intensity, overdue flags | | coach records feedback and practice task |
| W8 Quality review | triggers from hub outcome aggregates (§9) | | none; a trigger opens W7 or a re-observation |
| W9 CPD | plan seeded from lowest domains | | instructor logs activity |
| W10 Bench | `bench_ready`, evidence pack | | head of training decides and gives a rationale |
| W11 Partner | scoped W1-W4 from recordings | `meeting.recording` | as W1-W4, remote |
| W12 Unit readiness | reads the published `sl:unit@version` from the hub registry; opens W3 | | as W3 |

Overrides of a block always stay human, with a reason (spec, Rules).

## 9. Hub fit

1. **Contracts.** `plan`, `receipt`, `signoff` and `queue` are defined here under `tm:` with
   hub-shaped fields, and are offered to the hub to adopt as `sl:contract/...`.
   teachermodel then moves to the `sl:` versions. That is a major bump with a decision record.
2. **Units.** Teachable content is `sl:unit/<slug>@<version>`, owned by the curriculum system. `staffing-check`,
   `roster` and the module template move from `(tm|sl):module/` to `sl:unit/...@version`, so a
   clearance and a dry-run bind to one unit version.
3. **W12.** The expert-to-session conversion is the curriculum system's job. W12 here consumes a published unit,
   runs the dry-run and emits readiness.
4. **Deliveries and outcomes.** Deliveries arrive as hub delivery events. Outcome summaries arrive
   as aggregates published by hub `engagement/` through a contract. teachermodel never imports
   from the LMS or holds learner data.
5. **Staffing gate and identity.**
   - The hub's `rehearsed` -> `published` transition calls the staffing check.
   - teachermodel owns instructor identity: hub bindings reference `tm:instructor/` URIs. The hub
     owner must confirm.
6. **Console and inbox.** `queue@1` carries tm URIs and steps, never names. The hub console and the
   portfolio inbox read it.
7. **Edges.** The Track D crawler's edge derivation is not built yet (`packages/portfolio` has no
   provides or consumes code). The crawler is to read each contract's JSON Schema `$id`.

## 10. Contract changes and decision records

- **0007:** `event@2` adds the kinds `signoff`, `notice`, `check`, `registration` (instructor and
  engagement references from a roster import) and `step` (an `auto` step's output hash). Same
  shape; the closed enum makes this breaking.
- **0008:** unit references, giving `staffing-check@2` and `roster@2`. No live data exists yet.
- **New:** `workflows@1`, `signoff@1`, `plan@1`, `receipt@1`, `queue@1`.

## 11. Errors and testing

**Fail-closed throughout:**
- an op `error` or `not_found` never satisfies a step;
- a stale hash is rejected and the page regenerated;
- a signer mismatch is rejected and flagged to the head of training;
- every rejection is a `check` event.

**Tests:**
- Unit tests for `next` (needs, due dates, overdue) and for ingest (stale hash, wrong signer, wrong
  role, duplicate, missing receipt, error op).
- Each `verify` op is tested against a known-negative receipt.
- Page snapshot tests.
- A Playwright browser test per page template; the spec requires them for the observer form and
  the staffing check.

## 12. Increments

1. Engine, `standards/workflows/`, sign-off and ingest, the connector driver, setup, W1, and 0007/0008.
   Unblocks phase 1.
2. W2-W5: observer form, dry-run, clearance, calibration.
3. W6-W12: audit, coaching, quality, CPD, bench pack, partner, unit readiness.

**Verify in increment 1:** that `.eml` files with `X-Unsent: 1` open as drafts in the owner's
Outlook (the new Outlook may not honour the header; the fallback is a `mailto:` page per instructor).

## 13. Out of scope

Sending mail. Writing to Microsoft 365 before the Graph app. Hosted pages. AI drafting (spec, AI
assistance). Learner data. Retention periods (they need legal advice).
