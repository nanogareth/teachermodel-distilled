# 0027: Session schedule as an input, a freshness register, and an audience policy

Date: 2026-10-30. Status: accepted (owner, 2026-10-30). The built foundations (G1, G9, G11 in 5205b2b) were signed off
by the owner on 2026-10-30 ("Signed off") before the feeds and pages were built on them (decision 0028).

## Context

The role surfaces designed on 2026-10-30 (head of training's This week, the coordinator board, the instructor's My
record, and the rest) need data the record does not hold: which sessions are scheduled, and whether each source is
still reporting. They also need each person to see only what their role allows, which until now was a convention kept
by hand in each view.

## Decision

1. **The session schedule is a validated input, not events.** A calendar export (`tm:contract/schedule@1`) is kept at
   `inputs/schedule.yaml`, as bookings are (decision 0026). Sessions are plans; the facts of a delivery still arrive
   as outcomes and observations. Like bookings, a store that is not simulated reads a schedule only once
   `standards/retention.yaml` has an entry for `schedule-records`. The owner chose a calendar export over a form so
   nobody types sessions twice.
2. **A freshness register.** `standards/freshness.yaml` lists every source, its owner and how often it must report; a
   source past its limit is an item for that owner. Silence is never shown as success.
3. **An audience policy.** `standards/audience.yaml` lists which surfaces each role may open and which fields it keeps.
   Read models are projected through it, and a test renders every surface for every role. Decision 0005 (status
   leaves the function, scores never do) becomes a test, not a convention.
4. **Outbound pages go by email** from the programme mailbox, once IT grants Mail.Send scoped to that mailbox (owner,
   2026-10-30). Until then pages are generated and forwarded by hand. Not built in this change.

## Consequences

- The schedule export needs a retention entry before real use, as bookings do.
- A new surface or field is invisible to every role until the audience policy names it.
- Operational defaults (decision 0002): the freshness cadences and grace days are defaults, to revise from use.
