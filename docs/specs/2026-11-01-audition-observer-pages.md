# Audition observer pages (G8): sealed, signed scoring (spec and plan)

Date: 2026-11-01. Owner's choices on 2026-11-01: forms come back through the sign-off mailbox with no event, and a
domain may be "not observable", kept out of every mean. Decision 0031 records the choices.

## Scope

1. **Field kind.** `evidence_score` takes `not_observable: true`: a fifth choice, "Not observable in this slice",
   saved as `{not_observable: true, note}`. The note is required either way. Fields without the flag are unchanged.
2. **The page.** `audition.score_page(st, audition, observer)` is a page spec (template `approve`, decision approve):
   inputs are the audition id, unit and title, mode, slice, minutes, the observer and the day assigned; fields are the
   five evidence-score fields with not-observable. `audition.write_pages` draws a page for every assigned observer who
   has not scored; `assign` and `replace` call it, and so does the tick's page step.
3. **Ingest.** `bridge` sets audition documents aside (`Applied.auditions`, with the verified sender) before any
   workflow check, logging nothing for them. `audition.receive` accepts or refuses each: `signoff.accept` against the
   observer's current page hash, the observer's mailbox and the `clearer` role, signed no earlier than the day
   assigned; decision approve; one entry per domain, scored 1-4 or not observable, each with a note; observer assigned
   and not yet scored. A document already stored is a no-op; a refusal is written once per (document, reasons) to
   `refused.jsonl` and returned as a report line.
4. **Evidence.** `evidence()` takes `None` for not observable. Result and the This week card say "over N of 5
   domains" and list what was not observable; the dumbbell draws only the scores given.
5. **Coordinator route.** `audition score --form` accepts `not_observable: true` and requires notes.

Out of scope: reminders, assignment acceptance, conflicts, observer names on the panel page.

## Plan (test first)

1. `tests/test_pages.py`: the not-observable choice renders, its ids do not clash, a prefilled value validates;
   snapshots updated.
2. `tests/test_audition.py`: pages are drawn on assign and replace and dropped from the to-draw list once scored; a
   signed form through a fixture receipt is stored with no event; every refusal reason; a re-read message is a no-op;
   evidence with not observable; notes required on the coordinator route.
3. `tests/test_surfaces.py`: the card with a not-observable domain.
4. Docs, full suite, commit, handover.
