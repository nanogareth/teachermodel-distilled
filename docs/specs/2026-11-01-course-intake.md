# Course intake (G12): one command that checks, stores and records (spec and plan)

Date: 2026-11-01. Owner's go-ahead on 2026-11-01 ("Proceed", after G12 was recommended first of the loops with
people). Decision 0030 records the choices this spec makes.

## Problem

Per participant the coordinator runs about twelve commands for the five sessions: a checker (sessions 2, 3, 5), a
store step with a key they invent, `course record`, `course status`. For a group of six that is about seventy. Nothing
ties a stored file to its check result, `course record --on` defaults to today although every run sheet says to use
the session date, the key is checked for spelling only, and a file that fails its check leaves no trace, so the
coordinator board cannot say "returned with problems".

## Scope

1. **`teachermodel course intake <file> --instructor <uri> --session <id> --on <day>`**, plus `--catalogue <file>` for
   session 3 and `--reference <private-store key>` for session 5. The session picks the check
   (`standards/train-the-trainer.yaml`, a new `check` per session):

   | check | sessions | what passes | what is stored |
   | --- | --- | --- | --- |
   | `scan` | micro-teach, remote-delivery | a non-empty PDF, PNG or JPEG whose content matches its extension | the scan |
   | `question-set` | prior-knowledge | `course.question_set_errors` finds nothing | the YAML |
   | `failure-log` | lab-facilitation | `course.failure_log_errors` against `--catalogue` finds nothing | the YAML |
   | `scores` | rubric-scoring | `course.compare_scores` against the reference finds nothing | the comparison, not the typed scores |

   A pass stores the evidence under a generated key, `evidence/ttt/<participant>-<session>-<sha256[:8]>.<ext>`, and
   records the session with `--on`. A refusal stores no evidence, records nothing, prints every problem in plain words
   and exits 1. Either way one line is appended to the participant's intake log.
2. **Plain words.** Question-set problems name "Question 1, option B" instead of `pre_check[0].options[1]`, and a wrong
   option without a misconception reads "say which wrong idea this answer shows".
3. **Intake log.** `training/intake/<participant>.jsonl` in the private store, append-only: `at`, `session`, `sha256`,
   `result` (`stored` or `refused`), the `key` and `on` when stored, the `problems` when refused. A private document,
   never an event: the problems are free text about a person's work.
4. **Coordinator board.** A session not yet recorded whose latest intake was refused shows "▲ returned" with the
   number of problems; the counter adds "returned with problems"; the note points at `course intake`.
5. **Manual record kept, hardened.** `course record` now needs `--on` and a key that exists in the private store. It
   stays for evidence that arrives some other way.
6. **Run sheets.** The coordinator steps in sessions 1-5 `RUN.md` become one `course intake` line each.

Out of scope: `course correct` (a dated correction with a reason), missed-session rebooking, a schedule for course
sessions. Follow-ups.

## Plan (test first)

1. `tests/test_course.py`: each check passes and stores under the generated key and records; each refuses with plain
   problems, stores nothing, records nothing, logs; `--on` in the future, an unknown session, an already recorded
   session and a missing `--catalogue`/`--reference` are errors that log nothing; the log is append-only; the CLI
   exits 0/1; `course record` without `--on` or with a key not in the store is refused. Then `course.py`, `cli.py`,
   `standards/train-the-trainer.yaml`.
2. `tests/test_surfaces.py`: a refused intake marks the session returned on the board and the page; a later pass
   clears it. Then `surfaces.py`, `surface_pages.py`; `devsurfaces` seeds one refused intake.
3. Run sheets, `DESIGN.md`, `CLAUDE.md` commands; full suite; commit; handover.
