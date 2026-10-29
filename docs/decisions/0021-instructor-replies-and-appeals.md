---
status: accepted
date: 2026-10-27
supersedes: null
---
# 0021 Instructors reply to and appeal decisions on their record

## Context
Spec v0.2 gives every instructor "full view of their own record, a reply on every decision, an appeal to the head of
training", and an acceptance criterion reads "an instructor can see their whole record and reply to any
decision". Nothing let an instructor answer a decision. The owner asked on 2026-10-27 to build what the roadmap still
lacks (increment 4).

## Decision
1. A workflow `tm:workflow/rights` (standards/workflows/rights.yaml) with two steps.
2. `reply-or-appeal`: the instructor's own optional page, never due, open again after each reply (`bind: input` with the
   number of replies), like the CPD activity log. They pick one decision on their record by its event id (a clearance,
   a level change, a bench decision, an override decided for them, an audit that referred them back to calibration),
   choose reply or appeal, and write their words, which stay in the private store. The log holds a `step` event with the
   decision's id, the kind and the key of the text. Only the instructor signs it.
3. An appeal also opens an `appeal` child subject (subject@2, a kind added within major 2 as decision 0014 added four):
   `{instructor, decision, request_ref}`, URI `tm:appeal/<16 hex>`.
4. `appeal-decision`: the head of training, never the instructor concerned, decides `upheld` or `varied` with
   a private reason, within 14 days (an operational default, decision 0002). One decision per appeal: the first accepted
   decision stands (`signoff.SINGLE_DECISION_STEPS`).
5. Varied changes no record by itself. The head acts through the ordinary workflow (a new clearance round, a revocation
   under decision 0019, a level decision), so every change keeps its own evidence and audit trail.
6. The instructor record view shows each reply and appeal beside the decisions, with the outcome once decided.

## Consequences
- Acceptance criterion "reply to any decision" can be met; the gate report counts it once the record view exists.
- Appeals stay inside the training function (decision 0005): they are not a grievance procedure, which stays with HR.
- `tests/test_rights.py` pins the edges: only the instructor replies, only their own decisions, an appeal opens one
  subject, the head who is the instructor cannot decide, one decision per appeal, and no text in the log.
