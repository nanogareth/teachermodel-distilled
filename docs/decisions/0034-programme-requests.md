# 0034: Someone outside the training function can ask for a programme and see where it stands

Date: 2026-11-01. Status: accepted (owner, 2026-11-01: "Yes and continue through all steps until complete", on building
G6; the choices below are the builder's). The form, the requester's page and the board's list passed review on generated
data (owner, 2026-11-01, "Signed off"). What the requester sees: "One person only" (owner, 2026-11-01). Real requests wait
on a retention entry.

## Context

A programme exists only as a `ref` string inside someone's booking. A programme manager asks in a chat or an email, and
the coordinator retypes it as unit slugs and `tm:org` ids. Nothing records that a request exists, no reply date is
promised, and the requester has no way to see where it stands.

## Decision

1. **A one-screen form, offline.** `views/request-form.html` lists units by title, modes in plain words and regions;
   it saves `tm:contract/programme-request@1`, which the requester mails to the programme mailbox with the subject
   `[tm-signoff request]`. Region is required unless the mode is remote, and a past first day is refused. The form
   names no instructor. `teachermodel request new <file> --requester <mailbox>` takes one that came another way.
2. **The sender is who asked.** A request is not a sign-off. The bridge sets it aside before any sign-off check, and the
   connector vouches for the sender (decision 0006's mailbox). A refused request keeps nothing of the requester and
   appears only in the ingest report.
3. **A `request` event per stage.** `received`, `proposed`, `confirmed`, `declined`, `withdrawn`, on
   `tm:programme-request/<id>`, appended and never rewritten. This is `event@5`, one new kind, with `event@4` kept under
   `contracts/v4/` (as decision 0014 did). The mailbox and the requester's name for the programme are
   in the private document `requests/<id>.json`; the log holds its key. The same request from the same mailbox is one
   request.
4. **No block goes through.** `propose` is refused if the instructor is blocked on any working day; `confirm` checks every
   day again. A warn passes and the requester reads its outbound words. An override stays the head of training's
   (decision 0026) and shows here as ok.
5. **The requester reads one page, through the audience policy.** A new `requester` role, own-only on its own mailbox,
   gets `views/requests/<id>.html`: the stage in plain words, what they asked for and, once proposed, one person with
   "cleared to deliver this until" and the outbound words. It never shows other candidates, bookings, travel or block
   reasons. Showing the proposed person's name here, not their id, is the one place a surface resolves a name: the
   requester needs to know who is coming.
6. **We say when we are late.** The reply is promised in two working days (an operational default). The coordinator board
   lists open requests with a link to a match page per request, `views/staffing/<id>.html`; a late one shows there, on
   This week under "Waiting on someone else", and on the requester's page.

## Consequences

- **Pages still need forwarding.** Until delivery exists (G10), the coordinator sends the status page by hand.
- **A real store refuses a request** until `standards/retention.yaml` has a `programme-request-records` entry, as for
  bookings (decision 0026): it holds a person's mailbox.
- A confirmed request does not write a booking: bookings stay an export (decision 0026), so a confirmation and the
  calendar can differ until the next export.
- Not done: asking the instructor before proposing; changing dates on a request; one override for a whole programme; the
  blocked "near misses" on the match page; a partner on the form (`partner` is accepted in the file, but the form has no
  list of partners to offer).
- Assumptions still for the owner to confirm: two working days; the four decline reasons.
