# 0031: Audition observers score on their own signed page, outside the event log

Date: 2026-11-01. Status: accepted (owner, 2026-11-01: "Mailbox, no event" and "not observable, kept out of means").
The observer pages passed review on generated data
(owner, 2026-11-01, "Signed off", relayed by the role-surfaces session after phone-width screenshots). Amends the Consequences of 0025. Spec: `docs/specs/2026-11-01-audition-observer-pages.md`.

## Context

Decision 0025 kept auditions out of the event log and had the coordinator transcribe each observer's form with
`audition score`. So the coordinator held the first form before the second was in, notes were optional although the
pack asked for one per domain, and an observer had to invent a score for a domain the slice could not show. Every
other scoring step in teachermodel uses a signed offline page that comes back through the sign-off mailbox.

## Decision

1. **One page per observer.** Assigning or replacing an observer writes their page,
   `pages/audition-score--<id>--<observer slug>.html`: the slice, the unit and mode, and the rubric's
   evidence-score field for each domain (score, required evidence note, optional timestamp). The page never shows
   the candidate's name or the other observer's form.
2. **Back through the mailbox, never into the log.** The observer mails the signed file to the programme mailbox
   like any sign-off. Ingest recognises step `tm:step/audition-score` and hands the document to the audition, not the
   workflow engine: the sender must be the assigned observer's mailbox with the `clearer` role, the observer must not
   have scored, and the input hash must match the page's current inputs. An accepted form becomes
   `auditions/<id>/score--<slug>.yaml`, with the signed document beside it. Nothing is appended to the event log,
   neither the form nor a rejection: a refused form is listed in the ingest report and in
   `auditions/<id>/refused.jsonl`. 0025's "nothing enters the event log" stands.
3. **Not observable.** Each domain may be marked "not observable in this slice", with a note saying why. The
   evidence lists such domains separately; a domain either observer could not observe has no average, no within-one
   flag and no bar check, and the overall mean covers only domains both observers scored, saying how many. The
   starting plan seeds only from scored domains.
4. **Notes are required** on every domain, by either route, as on the W2 observation form.
5. **The coordinator's route stays** for a paper form (`audition score --form`), with the same checks. It is the
   fallback, not the default.

## Consequences

- The coordinator no longer handles the forms, so independence no longer rests on their discretion.
- Pages change template hash (the not-observable option is in the shared page script), so an unsent page of any step
  drawn before this change is drawn again on the next tick and must be signed again.
- Not done: reminders at 24 and 72 hours, an assignment page the observer accepts, conflict checks.
