# Workflow automation, increment 1: implementation plan

**Goal:** the engine, sign-offs, the connector bridge, the setup workflow and W1, end to end on
fictional data, so phase 1 can run on real data once 0005 and retention are settled.
**Spec:** `docs/specs/2026-10-24-workflow-automation-design.md` (amended by this plan; see Task 0).
**Verify:** `py -m pytest`; `teachermodel validate`; `teachermodel check-roster <path>`.
Ticking: `- [x]` in this file as each step lands; commit per task with explicit pathspecs.

Shared conventions for every task:
- No new runtime dependency without a web-verified version (CLAUDE.md global rule).
- Pages use stdlib `string.Template` + `html.escape`; no template engine.
- Anything that holds names is written under the private dir (Task 2), never the repo.
- Every new rule or check gets a known-negative test (it must be shown to fail).

## Task 0: spec amendments found while planning

Files: `docs/specs/2026-10-24-workflow-automation-design.md` §3, §7, §10.
- [x] §10: `event@2` kinds are `signoff`, `notice`, `check`, `registration` (instructor and
  engagement references from a roster import) and `step` (an `auto` step's output hash).
- [x] §3: a step gains `applies_to` (filter on instructor type) and `due` is a `rules.py` rule name
  or `{days: N}` labelled operational default (no new thresholds in `rules.yaml`).
- [x] §7: add a human step `Retention periods` (owner, on legal advice), which the notice step
  `needs`: the notice must state how long data is kept.
- [x] §5: signer roles come from `identities/people.yaml` in the private store.
- Done: the spec diff covers only these four points.

## Task 1: decisions 0007/0008 and the v2 contracts

Files: `docs/decisions/0007-event-v2.md`, `docs/decisions/0008-unit-references.md`,
`contracts/event.schema.json`, `contracts/staffing-check.schema.json`,
`contracts/observation.schema.json`, `contracts/roster.schema.json`, `contracts/v1/*`,
`src/teachermodel/rules.py:Observation,DryRun,Clearance,clearance_check,staffing_check`,
`standards/templates/module.yaml`, `standards/templates/roster*.yaml`, `tests/*`.
- [x] Copy each @1 schema to `contracts/v1/<name>.schema.json` unchanged (history), then bump in
  place to @2.
- [x] `event@2`: add the five kinds from Task 0.
- [x] Unit refs: replace every `module` field with `unit`, pattern `^sl:unit/[a-z0-9-]+@[0-9]+$`, in
  staffing-check, observation and roster. Rename the dataclass fields and parameters in `rules.py`
  (`module` -> `unit`) and the test constants (`MOD` becomes `sl:unit/example-agent-loop@1`).
- [x] `standards/templates/module.yaml` -> `unit-requirements.yaml`: what teachermodel reads from
  a curriculum unit (pre-check, misconceptions, failure catalogue); id `sl:unit/example-agent-loop@1`.
- [x] Test first: `test_contracts.py::test_v1_unit_ref_rejected` (an `@2` doc with
  `tm:module/x` fails) and `::test_event_v2_new_kinds_accepted`.
- Done: `py -m pytest` green; `grep -rn "module/" src contracts standards` shows only `contracts/v1/`.

## Task 2: private dir resolution and guard (production path)

Files: `src/teachermodel/config.py:private_dir,people,assert_outside_repo`.
- [x] `private_dir()` reads `TEACHERMODEL_PRIVATE_DIR`; with no variable set, live commands fail
  with a message naming 0006. Tests pass `--private-dir` explicitly.
- [x] `assert_outside_repo(path)` refuses any path inside a git working tree. Walk the parents
  for `.git`; do not shell out.
- [x] `people(dir)` loads `identities/people.yaml`: `{person, name, email, roles}`. Roles are
  checked against the spec role list.
- [x] Test first: `test_config.py::test_env_var_resolves` (set the env var with monkeypatch ->
  real resolution, no injected path), `::test_inside_repo_refused` (uses this repo's own path),
  `::test_unset_fails_naming_0006`.
- Done: `py -m pytest tests/test_config.py -v` green; `TEACHERMODEL_PRIVATE_DIR=. teachermodel next`
  exits non-zero with the guard message.

## Task 3: workflows contract and `standards/workflows.yaml`

Files: `contracts/workflows.schema.json`, `standards/workflows.yaml`,
`src/teachermodel/standards.py:check_standards`.
- [x] Schema per spec §3 plus `applies_to`.
- [x] `workflows.yaml`: `tm:workflow/setup` (spec §7 plus the retention step) and
  `tm:workflow/onboarding` (W1):
  1. commitment: human; manager for `sme-engineer`, partner lead for `partner`;
  2. baseline self-assessment: human; instructor;
  3. train-the-trainer completion: human; coordinator;
  4. shadow delivery recorded: human; coordinator;
  5. co-delivery recorded: human; coordinator;
  6. level change to `lead-observed`: human; head of training, on a batch page.

  W1 ends where W2/W4 (increment 2) start.
- [x] Cross-checks in `check_standards`:
  - `needs` resolve and have no cycles;
  - every `role` is a spec role;
  - every rule-name `due` exists in `rules.py`;
  - every `page` template exists;
  - every step's `basis` is non-empty.
- [x] Test first: `test_standards.py::test_workflow_cycle_rejected`,
  `::test_unknown_page_rejected`, `::test_unknown_due_rule_rejected` (temp copies of standards).
- Done: `teachermodel validate` prints `ok`.

## Task 4: engine `next`

Files: `src/teachermodel/workflow.py:Due,subjects,next_steps`.
- [x] `subjects(events)` derives instructors (with type) from `registration` events, plus the
  singleton `tm:programme/teachermodel`.
- [x] `next_steps(workflows, events, subjects, today)`:
  1. take each step × matching subject;
  2. skip it if `done_when` already matches an event;
  3. keep it only if every `needs` step is done for the same subject (programme-level needs apply
     to every instructor);
  4. set due from the latest `needs` completion plus `days`, or from the rule;
  5. set `overdue` when today is past due.

  Order by due date, then step id, so the output is deterministic.
- [x] Test first: `test_workflow.py`:
  - `::test_needs_gate`;
  - `::test_applies_to_filters_type` (partner gets no manager step);
  - `::test_done_step_drops`;
  - `::test_overdue_edge` (due today is not overdue, due yesterday is);
  - `::test_programme_need_blocks_instructor_steps` (no roster import -> no W1 steps).
- Done: `py -m pytest tests/test_workflow.py -v` green.

## Task 5: sign-off contract and ingest core

Files: `contracts/signoff.schema.json`, `src/teachermodel/signoff.py:input_sha256,accept`.
- [x] `input_sha256(obj)` is SHA-256 of `events.canonical(obj)`, reused, not re-implemented.
- [x] `accept(signoff, current_input, sender_email, people, step, seen_ids)` returns the reasons it
  rejects: schema invalid, stale hash, unknown sender, sender is not the named signer, signer
  lacks the role. A repeat id returns `[]` and a `duplicate` flag (no-op).
- [x] Test first: `test_signoff.py`:
  - `::test_valid_accepted`;
  - `::test_stale_hash_rejected`;
  - `::test_sender_mismatch_rejected`;
  - `::test_wrong_role_rejected`;
  - `::test_duplicate_noop`;
  - `::test_email_case_insensitive`.
- Done: green; each rejection test asserts the specific reason string.

## Task 6: plan and receipt contracts, receipt ingest

Files: `contracts/plan.schema.json`, `contracts/receipt.schema.json`,
`src/teachermodel/bridge.py:build_plan,apply_receipt`.
- [x] `build_plan(due, people, private_dir)` writes ops for due `verify` steps, plus a standing
  `mail.tagged` op for `[tm-signoff` and a `file.get` per file in the library `inbox/`. `op_id`
  is a hash of `(op, args)`, so a re-plan is idempotent.
- [x] `apply_receipt(receipt, plan)`:
  - the receipt must carry the plan's `plan_sha256`;
  - only `ok` ops are used;
  - `not_found`, `error` and missing ops write a `check` event and leave the step open;
  - sign-off attachments go to `accept` (Task 5);
  - accepted sign-offs become `signoff` events, and `mail.sent` hits become `notice` events.
- [x] Test first: `test_bridge.py`:
  - `::test_wrong_plan_hash_rejected`;
  - `::test_error_op_leaves_step_open`;
  - `::test_missing_op_is_check_event`;
  - `::test_notice_sent_sets_given_on`;
  - `::test_known_negative_mail_sent` (a receipt with no matching mail never marks the notice
    given).
- Done: green.

## Task 7: page generator

Files: `src/teachermodel/pages.py:render`, `src/teachermodel/page_templates/{base,approve,
self_assessment,dpia_screening,batch_approve}.html`.
- [x] `render(step, subject, inputs, fields)` embeds `input_sha256`, `page_template_sha256`, the
  field spec and the step id.
  - Inline vanilla JS checks required fields and enums, builds the sign-off JSON and downloads it
    (Blob). The file is named `<step-slug>-<subject-slug>-<id>.json`.
  - The page shows the return channel for the role (library `inbox/` or a `mailto:` with the
    subject tag).
- [x] `self_assessment` renders the framework domains with rubric anchors 1-4 from `standards/`.
- [x] `dpia_screening` lists the nine screening criteria of the WP29/EDPB DPIA guidelines
  (WP248 rev.01), pre-answered from facts:
  - evaluation or scoring: yes;
  - vulnerable data subjects, employees: yes;
  - systematic monitoring: from the observation design;
  - the rest: no, with the reason.

  The DPO confirms each answer and records a decision.
- [x] `batch_approve` shows the unchanged rows collapsed under "approve all unchanged" and the
  changed rows expanded.
- [x] Test first: `test_pages.py::test_snapshot_<template>` (render the fictional inputs; compare
  with `tests/snapshots/`), `::test_no_external_urls` (no `http` in `src=`/`href=` except `mailto:`),
  `::test_hash_embedded_matches`.
- Done: green; open one page in the Browser pane and download a sign-off that `accept` takes.

## Task 8: setup auto steps

Files: `src/teachermodel/setup.py:it_request,ropa,notice,notice_drafts,import_roster,gap_list`,
`standards/templates/{it-request,ropa,privacy-notice}.md`, `standards/retention.yaml`.
- [x] `it_request`: the 0006 library, group and settings as one request (markdown + `.eml`).
- [x] `ropa`: data categories from `contracts/roster.schema.json`, `observation.schema.json` and
  `event.schema.json`; recipients from the spec role table; storage from 0006. No hand-typed
  category list.
- [x] `standards/retention.yaml` (`status: draft`, periods `null`). Notice rendering refuses
  `null` periods and refuses while 0005 is not `accepted`; both cases are reported in `next`.
- [x] `notice_drafts`: one `.eml` per instructor using stdlib `email.message.EmailMessage`, with
  `X-Unsent: 1` and subject tag `[tm-notice <version>]`. Personalised only by name; the body hash
  is the approved text hash.
- [x] `import_roster`:
  1. run `check-roster`;
  2. write identities to `identities/roster.yaml` (private);
  3. append one `registration` event per instructor (type, organisation, engagement refs, no
     names) and one `level_change` event for the baseline level.

  A re-import diffs against the events; a changed level is refused (spec: level moves only by
  decision).
- [x] `gap_list`: `delivers` rows with no valid clearance (via `rules.staffing_check`) become a
  batch-approve page for the owner.
- [x] Test first: `test_setup.py`:
  - `::test_ropa_categories_follow_schema` (add a field to a temp schema -> it appears);
  - `::test_notice_refused_while_0005_open`;
  - `::test_notice_refused_null_retention`;
  - `::test_eml_has_x_unsent_and_tag`;
  - `::test_import_writes_no_names_to_events` (grep the log for every example name);
  - `::test_reimport_level_change_refused`;
  - `::test_gap_list_flags_uncleared_delivery`.
- Done: green.

## Task 9: CLI and queue contract

Files: `src/teachermodel/cli.py:main`, `contracts/queue.schema.json`.
- [x] Commands per spec §4: `next [--role] [--json]`, `run`, `pages`, `plan`, `ingest <file>`
  (detects receipt vs sign-off by `schema`), `tick`. All take `--private-dir`, defaulting to
  `config.private_dir()`.
- [x] `queue@1` holds tm URIs, step ids, roles and dates, and never a name. Test it against the
  example roster names.
- [x] Test first: `test_cli.py::test_tick_on_fictional_store` (temp private dir outside the repo,
  example roster) asserts the queue starts with the IT request and the retention step;
  `::test_queue_json_has_no_names`.
- Done: green.

## Task 10: connector driver (runbook, project skill, live probe)

Files: `docs/runbooks/connector-driver.md`, `.claude/skills/tm-connector-driver/SKILL.md`.
- [x] Map each `op` to connector tools: `outlook_email_search` for `mail.sent`/`mail.tagged`,
  `sharepoint_search`/`sharepoint_folder_search` for `site.library`, `read_resource` for `file.get`
  and attachments. The skill:
  1. reads the plan;
  2. runs every op verbatim;
  3. writes `receipt.json` with `driver: connector`;
  4. runs `teachermodel ingest`.

  It makes no judgement calls; an op it cannot run is `error`.
- [ ] Live probe, read-only: run each op once with a known-positive input and once with a
  known-negative one. The positive is a message you sent yourself with a test tag; the negative
  is a tag that does not exist. Record the results in the runbook. An op with no working tool is
  marked unsupported, and its steps stay human-attested.
  2026-10-27: `site.library` positive and negative, and `mail.tagged` positive (own mailbox, attachments as plain text),
  are recorded in the runbook. Still open: a `mail.tagged` negative and a `mail.sent` probe.
- Done: the runbook table shows both probes per op, and `apply_receipt` accepts the probe receipt.

## Task 11: browser test and Outlook draft check

- [x] Web-verify the current `pytest-playwright` and `playwright` versions. Add them as an
  optional `[browser]` dev group. Write `tests/browser/test_pages.py`: fill the self-assessment,
  download the sign-off, and assert `accept` returns `[]`. Skip when browsers are not installed.
- [ ] Owner check (human): open one generated `.eml` in your Outlook. Record in the runbook
  whether it opens as an editable draft. If not, implement the `mailto:` fallback page (spec §12)
  before closing the increment. 2026-10-26: it opened, but showed the markdown source; the drafts now carry an
  HTML part. Re-check one new draft (runbook, "Outlook draft check").
  2026-10-27: the sign-off drafts the pages now download (`X-Unsent: 1`) opened in Outlook as new messages and were
  sent. Still open: the generated IT request's HTML rendering.
- Done: the browser test passes locally, and the runbook records the Outlook result.

## Task 12: end-to-end on fictional data, then the trigger

- [x] E2E script `scripts/e2e_fictional.py` against a temp private dir:
  1. example roster;
  2. `tick`;
  3. sign-offs signed by fictional people;
  4. a hand-built receipt containing them;
  5. `ingest`, then `tick`.

  Assert the queue reaches the gap-list approval, every sign-off is a `signoff` event, and
  `verify-events` passes.

  Built as 17 stages (`py scripts/e2e_fictional.py`; `tests/test_e2e_script.py` runs it in-process).
  It copies standards, contracts and decisions to a temp root so the retention periods and decision
  0005 are edited there, never in the repo (the script checks both real files are unchanged). It also
  covers the strict `mail.sent` check, W1 through the `lead-observed` level change, and two ingest
  changes made with it: an approving `lead-observed-level` sign-off appends a `level_change` event
  (actor the signer, id derived from the sign-off id), and ingest re-derives each step's inputs from
  the current state with the page builder instead of trusting the `pages/*.input.json` sidecars.
- [x] Create the desktop scheduled task (daily) that runs `teachermodel tick`, then the
  `tm-connector-driver` skill, then `ingest`. Ask before creating it; it acts on your mailbox
  reads daily. Amended by the owner 2026-10-27: the scheduled task is deterministic (Windows Task Scheduler runs
  `teachermodel daily`, created by `teachermodel schedule-daily`; `6751dae`); the mailbox read stays with the connector
  skill until the Graph driver. Verified: a triggered run returned 0 and logged its line.
- [x] Update `docs/plans/phase-plan.md` and `docs/hub-alignment.md` (the new contracts as hub
  candidates; queue@1 for the console).
- Done: the E2E script passes; `py -m pytest` is fully green; the scheduled task is listed.

## Deferred

- Filing hub inbox items: the hub to adopt `plan`/`receipt`/`signoff`/`queue`, and the crawler
  to read JSON Schema `$id`. Track D's vault inbox is not built yet, so they are recorded in
  `docs/hub-alignment.md` until it is.
- The Graph driver, real roster data (needs 0005, retention, notice sent), and W2-W12 (increments
  2-3).
