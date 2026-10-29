# Development simulation: a complete dummy store, end to end

Status: accepted for build (owner request, 2026-10-27: "populate a complete set of dummy data end to end to emulate
real-world usage during development"). Decision 0020 records the two relaxations a simulated store gets.

## Goal

One command builds a private store that looks like months of real use: every workflow has run, several times, with
the variety real people produce (a not-yet outcome, a disagreement the head resolves, a quality trigger, a coaching
cycle, an audit, a bench review, an override). A developer can then open its pages, queues, packs and records, or keep
ticking it with the ordinary CLI.

    teachermodel dev-simulate --store <dir> [--weeks 26] [--end YYYY-MM-DD]

## What exists and why it is not enough

- `scripts/e2e_fictional.py` drives one scripted instructor through every stage, in a throwaway temp store, against a
  temporary copy of the standards with fictional privacy profiles. It is a test, not a dataset.
- `dev-autosign` signs every due page in a pilot store, all on the real day, always approving. Nothing that needs time
  to pass ever fires (quarterly audit, calibration renewal, recheck and expiry, coaching cadence, contract-end bench),
  and nothing ever goes wrong.

## Design

1. **A fresh simulated store.** `--store` must not exist or must be empty (or a previous simulated store, which
   `--reset` clears). It is a pilot store (`pilot: true`, decision 0016) marked `simulated: true` (settings@1, an
   optional field added within major 1). Everyone in it is generated, at example.com, the owner included. The store
   must be outside the repository and outside AppData, like any store.
2. **The real standards.** The store runs against the repository's own `standards/`, so the ordinary CLI agrees with
   every hash in it afterwards. Two legal blockers would stop a store on the real standards, and a simulated store
   relaxes them (decision 0020):
   - the notice templates still carry their "DRAFT for legal review" banner and draft markers. In a simulated store the
     notice text renders anyway, with the markers removed and a first line `SIMULATED DATA: generated for development.
     This is not a privacy notice.`;
   - the generated roster has only jurisdictions with a profile (IE, US-CA). The pilot generator's DE partner, a
     leftover fixture, moves to IE in both generators.
3. **A simulated calendar.** Weekdays from `end - weeks` to `end` (default: today). Each day has two rounds, 07:30 and
   13:30 UTC. A round is: tick; answer the plan with a fixture receipt; ingest through the real `do_ingest` (the fixture
   driver is allowed through the `allowed_drivers` keyword only, as in the e2e; the CLI never accepts it). Every app
   function gets the simulated time, so expiry, quarters, cadences and due dates behave as in real use.
4. **The simulated mailbox** answers every op of the plan:
   - `site.library`: exists;
   - `mail.sent`: the owner "sends" each notice draft the day after it is written: a message from the owner to the
     instructor with the op's tag;
   - `mail.tagged`: one message per sign-off the people produce this round, from the signer's own address, with the
     sign-off file attached.
5. **People act on their pages.** For each due human step and subject, the round signs one page (the next signer's
   the next round, for a step every signer signs), from the page's embedded data, like `dev-autosign`. Answers start
   from `devsign.answers` and are then shaped by the subject instructor's **persona**:

   | Persona | Observation scores | Clearance decision | Outcomes against baseline |
   | --- | --- | --- | --- |
   | strong | 3 to 4 | cleared | +2 to +6 |
   | solid | 3 | cleared | -2 to +3 |
   | developing | 2 to 3 | second clearer `not_yet`, the head resolves `cleared_with_conditions` with a recheck | -6 to 0 |
   | struggling | 2 | `not_yet` from both, with actions | -14 to -10, 16+ learners (quality triggers) |

   Every choice is a hash of fixed inputs (ids and the day), never a random draw: two runs with the same arguments
   write the same store.
6. **What the organisation does on its own initiative**, on fixed rules:
   - day one: the roster import once its step waits for the command;
   - a calibration exercise for clearers without a current calibration (none yet, or renewal within 30 days of the
     six-month limit), scored against the reference, one clearer missing the first time;
   - an outcome export on the first weekday of each month, for every delivery of the month before;
   - a CPD activity per delivering instructor each month, on one of their CPD plan's gap domains;
   - one ad-hoc observer assignment per quarter, for the candidate with the fewest observations;
   - after a bench decision that returns someone to co-teaching, one staffing override for a delivery a week later,
     approved by the head;
   - bench reviews open by themselves (contract end, repeated triggers); the head decides by persona (struggling:
     return to co-teaching; a contractor at contract end who is solid or better: renew).
7. **The roster**: 14 instructors, IE and US-CA only. Four founding clearers (one in California), two cleared
   professionals, three lead-observed SMEs, two co-delivering SMEs, a Californian contractor whose contract ends inside
   the window, an Irish contractor and an Irish partner. Two coaches are mapped to the developing and struggling
   instructors. Personas are fixed per instructor.
8. **Output**: the store, a `simulation.log` with one line per day (sign-offs, events, rejections), and a summary of
   event counts by kind. A rejected sign-off is a simulator defect: the run stops and names it.

## Not in scope

- Real mail, the connector or Graph: the simulated mailbox stands in for both.
- Realistic free text: notes and reasons are short generated sentences, kept in the private store as usual.
- Load testing: 14 instructors over 26 weeks is the size of the real programme, not a stress test.

## Plan

1. Settings@1 `simulated` (requires `pilot: true`), validate refuses it otherwise; the notice relaxation in
   `setup.notice_text` and the overlay variant, gated on it; tests for both, and that a non-simulated pilot store is
   still blocked.
2. Pilot generator: the partner moves from DE to IE; README and docstring updated.
3. `simulate.py`: store creation (settings, people, roster, reference, retention), the calendar loop, the mailbox,
   persona answers, the scheduled initiatives; `teachermodel dev-simulate`.
4. Tests: a short simulation (a few weeks) completes with no rejection and writes the core event kinds; determinism
   (two runs, same log); refusals (non-empty store, store inside the repo).
5. Run the full 26 weeks once, check that every workflow fired (event kinds and step ids), record the result in the
   handover.
