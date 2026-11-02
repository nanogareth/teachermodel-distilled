# 0030: Course intake checks, stores and records in one step

Date: 2026-11-01. Status: accepted (owner, 2026-11-01: "Proceed" on G12; the choices below are the builder's, for
review on generated data). The coordinator board's "returned" count passed that review
(owner, 2026-11-01, "Signed off", relayed by the role-surfaces session after phone-width screenshots). Spec: `docs/specs/2026-11-01-course-intake.md`.

## Context

The train-the-trainer course is recorded by hand: a checker per session, a key the coordinator invents, then
`course record`, whose date defaults to today and whose key is never looked up. About seventy commands per group of
six, and a file that fails its check leaves nothing behind, so no surface can show evidence sent back.

## Decision

1. **One intake command.** `teachermodel course intake <file> --instructor --session --on` runs the check that
   `standards/train-the-trainer.yaml` names for the session (`scan`, `question-set`, `failure-log`, `scores`). Only a
   pass stores the evidence and records the session. Session 5 stores the comparison, which is the evidence, not the
   typed scores.
2. **Generated keys.** `evidence/ttt/<participant slug>-<session>-<first 8 of sha256>.<ext>`: stable for the same
   file, meaningless otherwise, and never typed by a person.
3. **`--on` is required.** Course sessions are not on the session schedule (`schedule@1` lists unit deliveries), so
   the coordinator gives the session date; a day after today is refused. Taking the date from a course schedule is a
   later change.
4. **The intake log is a private document.** `training/intake/<participant slug>.jsonl`, append-only, beside the
   course record it explains. It holds problems in plain words about a person's work, so it is never an event and
   never leaves the private store; the board shows only that a session was returned and how many problems it had.
   It falls under the same retention category as the course record once retention entries exist (`retention.yaml`
   is still empty pending legal advice).
5. **The manual record stays for other routes, with checks.** `course record` needs `--on` and a key that exists in
   the private store. Generated stores keep recording through the function directly.

## Consequences

- One command per participant per session; the record can no longer point at a file that is not there, or carry
  the day it was typed.
- The sign-off page's `course` input (`course.status`) is unchanged, so signed pages still bind to the same list.
- Not done: `course correct`, missed-session rebooking, course sessions on a schedule.
