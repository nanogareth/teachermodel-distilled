# 0033: A live room leaves a record about the lab, never about who taught it

Date: 2026-11-01. Status: accepted (owner, 2026-11-01: "Yes and continue through all steps until complete", on building
G5; the choices below are the builder's). "Where learners stall" passed review on generated data (owner, 2026-11-01,
"Signed off"). Linking a room to who taught it: "Labs only" (owner, 2026-11-01).

## Context

The checkpoint collector kept a room in memory. Stopping it lost the room, unless `--snapshot` caught one final moment.
Nobody could see when a step blocked a room, or whether a demonstration helped. The projected page showed a red stuck
count, which in a small room points at a person. A learner who saw "not yet" got pytest's output and nothing else.

## Decision

In proving-ground (`tools/checkpoints/`):

1. **Kept by default, a minute at a time.** A session folder under `reports/rooms/` takes a line per minute of counts per
   step, and the summary so far, so closing the window loses a minute at most. `--no-record` opts out. Neither file
   holds a device code.
2. **Two views.** `/` stays for the room: neutral bars, "working on", and "a few" for a count under 3 in a room under 15
   devices. `/instructor`, behind a key the collector prints once, holds what the room must not see: durations, the line
   over ten minutes, the hint, and the prompt when a third of the devices have been stuck over five minutes. The prompt
   suggests and never acts. The button there marks a demonstration on the timeline.
3. **Hints.** Each step in `checkpoints.json` carries a `hint`, and the checker's `checkpoints` rule requires it.
   `checkpoint.py` prints it after "not yet", with the help route, and says what is next after a pass.

In teachermodel:

4. **`room-summary@1` is a feed, not an event.** On exit the summary goes to the inbox of the store
   `PROVING_GROUND_FEED_STORE` names (decision 0028), one file per room under `inputs/rooms/`. `collector.py --finish
   <folder>` sends one whose window was closed. An empty room sends nothing.
5. **About the lab, not the instructor.** The feed has no session reference, no instructor and no device. This week shows
   the steps that held a third of a room, per lab, over six months (an operational default). The head of training
   alone sees it. No code joins a room to the schedule, and doing so would need a new decision.

The thresholds (five minutes, a third, three devices for a room, under 15 for "a few") are operational defaults
(decision 0002), and they prompt nothing in teachermodel's rules.

## Consequences

- The open question "may the timeline judge instructors?" is answered no (the owner's "Labs only"); changing that takes
  a new decision. Dates and a lab could be matched by hand to a schedule; the page does not do it.
- The feed holds no person, so like the other lab feeds it needs no retention entry (decision 0028). The session folder
  stays on the instructor's laptop.
- Not done: remote learners outside the room's network (needs a relay and a hosting decision); expected head count
  on the instructor view; flagging a stuck device to a TA (a device has no seat); a cockpit panel; a page that survives
  the collector stopping.
