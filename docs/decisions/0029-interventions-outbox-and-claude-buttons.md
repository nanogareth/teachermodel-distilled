# 0029: Intervention chains, a dry-run outbox, and Claude buttons

Date: 2026-10-30. Status: accepted (owner, 2026-10-30: "Yes, start and continue through all steps").

## Context

The role surfaces show what needs doing; nothing yet tells the person who must act, reminds them, or escalates. The
owner's design adds chains of interventions started by deterministic conditions, an outbox for everything that leaves the store, and
Claude buttons that draft or act through enterprise connectors. The owner's choices: Microsoft 365, Teams first through Power Automate, notify and calendar proposals unattended after a
shadow period, escalation per chain, the Claude API directly, Claude may write with a person approving each call,
Opus 5.5 for every button, enrolment through Workday Learning, the relay owned by the programme account with IT.

## Decision

1. **Chains are data.** `standards/chains.yaml` lists each chain's condition, steps (kind, recipients, due offset from
   the condition's anchor date), escalation and Claude buttons. A condition is a pure function over the record, the
   schedule, the feeds and the workflow's due steps; no model decides whether one holds.
2. **The outbox is derived, not stored.** Each run computes the outbox afresh from the conditions that hold. An
   action's id is a hash of its chain, subject, anchor date, step and recipient, so the same action keeps the same id
   on every run and is never sent twice once delivery exists. Nothing is written to the event log by this change.
3. **Dry run only.** `outbox@1` has `mode: dry-run`; no driver sends anything. The Outbox page shows every action that
   would go out, for the head of training only (standards/audience.yaml).
4. **Claude never evaluates a condition and never writes unapproved.** Buttons are declared beside the chains: a
   drafting button returns a draft that must fit its schema (`contracts/drafts/`); an acting button's every write is
   approved by the person who pressed it, and comes back as `claude-session@1`. Drafts, session records and commands
   arrive through `inbox/` and are checked like feeds.
5. **The deployment kit is generated.** `teachermodel claude-kit` writes the agent files, the drafting request
   templates and the system prompts from `standards/chains.yaml`, so the buttons cannot drift from the chains. The
   relay and the Power Automate flow templates live in `deploy/claude/`. Nothing in this repository calls the Claude
   API; the owner's development stays subscription-only.

## Consequences

- Delivery (G10), the relay and the agents run only in the deploying organisation's tenant; this repository proves them on generated
  data and fakes.
- Chains whose source is not connected yet (a train-the-trainer cohort calendar, the HRIS leaver feed) are listed as
  waiting on the Outbox page, never silently skipped.
- The due offsets and escalation days are operational defaults (decision 0002).
- Recording sent actions as events needs a new event kind (a later decision); until delivery exists there is nothing
  to record.
