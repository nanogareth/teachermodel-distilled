# Train-the-trainer: course design

Date: 2026-10-30. Spec v0.2, W1 step 3: "Complete the train-the-trainer programme (prior-knowledge diagnosis,
conceptual questioning and peer discussion, lab facilitation, remote delivery)." This document is that programme.
The sessions and their evidence are listed for the tools in `standards/train-the-trainer.yaml`.

## Who it is for

Engineers who know their subject and have not taught it, contractors joining the bench, and partner facilitators.
They arrive with a baseline self-assessment (W1 step 2) and leave ready to shadow a cleared instructor (W1 step 4).
The course does not clear anyone. Clearance comes later, from observations of real deliveries (W2, W4).

## What a participant can do at the end

1. Teach a ten-minute slice of a technical session, take scored feedback on the rubric, and teach it again better.
2. Find out what a room already believes, with a diagnostic question whose wrong answers point to named
   misconceptions, and run a vote, discussion and revote on it.
3. Keep a hands-on lab moving when the environment or the model fails, using the lab's failure catalogue.
4. Run the same slice remotely, so that remote learners take part as fully as the people in the room, and read the
   room from checkpoint progress rather than from faces.
5. Score a recorded session on the five-domain rubric close to the reference scores, and say which anchor each score
   rests on.

Technical depth, the first rubric domain, is not taught here: it is the participant's own expertise. The dry run
(W3) and the observations that lead to clearance check it.

## The five sessions

Each session is 90 minutes, run from a `RUN.md` for the trainer and a `LEARNER.md` for participants (facilitator content never goes in the
learner's document), and ends in evidence that
the coordinator records with `teachermodel course record`. Groups are four to six participants and one trainer.

| # | Session | Rubric domains | What participants do | Evidence recorded |
| --- | --- | --- | --- | --- |
| 1 | Micro-teach rounds | all but remote-inclusive, which an in-room session cannot show | Teach a 10-minute slice, receive rubric-scored feedback from the trainer and peers, reteach the part the feedback was about | Both rounds' rubric forms, held in the private store |
| 2 | Diagnosing prior knowledge | prior-knowledge, conceptual-questioning | Write a diagnostic question from the unit's misconceptions list and run a vote, discussion and revote with it | The question set, in the unit's `pre_check` shape |
| 3 | Lab facilitation and recovery | lab-facilitation | Run a slice of a proving-ground lab for peers while the trainer injects a delivery failure from the scenario's catalogue | Which failure was injected and how it was handled, against the catalogue's `expected_handling` |
| 4 | Remote and inclusive delivery | remote-inclusive | Teach the session 1 slice remotely, with breakouts and the checkpoint room page | The remote round's rubric form |
| 5 | Seeing teaching through the rubric | all five | Score two reference recordings independently, then compare with the reference scores and discuss the anchors | The scores against the reference, domain by domain |

Session 1 comes first because every later session reuses its slice and its feedback routine. Sessions 2 to 4 can
run in any order. Session 5 can run at any point; participants who take it early get more from the feedback in the
others.

## Why microteaching

The spec rates microteaching as weak to moderate evidence (Hattie's 0.88 rests on old meta-analyses), so it is used
for what it does reliably: short, repeated practice with specific feedback before teaching a real room. The
feedback uses the clearance rubric's anchors, so participants hear from the start the language their observers will
use later.

## Completion

A participant completes the course when all five sessions are recorded. There is no pass mark. Sessions 1, 4 and 5
produce rubric scores, and these are formative: they are not observations, do not count toward clearance, and are
not shown to anyone outside the training function (decision 0005). The coordinator signs the W1 train-the-trainer
step. The page lists each session as recorded or missing, and the sign-off binds to that record.

## Partner facilitators

Partner facilitators take the same five sessions remotely. Session 3 runs in a shared remote lab with screen share.
Session 4 is their main session rather than an adaptation. The partner lead's nomination is the W1 commitment step,
and their clearance later follows the partner pack (W11). The course record is the same, so the coordinator cannot
tell a remote completion from an in-room one, and does not need to.

## What exists and what is still to build

| Part | State |
| --- | --- |
| This design, and the session list in `standards/train-the-trainer.yaml` | written |
| `teachermodel course record` / `course status`, and the evidence list on the train-the-trainer sign-off page | built |
| Session 1 pack: `01-micro-teach/RUN.md` and `LEARNER.md` | written |
| Session 2 pack: `02-prior-knowledge/RUN.md` and `LEARNER.md`; `teachermodel check-questions` checks its question set | written, built |
| Session 3 pack: `03-lab-facilitation/RUN.md` and `LEARNER.md`; `teachermodel check-failure-log` checks its failure log against the lab's catalogue | written, built |
| Session 4 pack: `04-remote-delivery/RUN.md` and `LEARNER.md`, hybrid on one network, with a fully remote section for partners | written |
| Session 5 pack: `05-rubric-scoring/RUN.md` and `LEARNER.md`; `teachermodel compare-scores` compares a participant's scores with the reference | written, built |
| Reference recordings for session 5 | the same three reference-scored recordings the calibration phase gate needs |

## Left open

- Session 1 timing. Six people teaching ten minutes each, twice, with feedback, does not fit 90 minutes with one
  trainer. The pack splits the group into two pods teaching side by side. The second round is a five-minute reteach
  of the part the feedback was about. The trainer scores each participant in one round and peers score every teach
  (`01-micro-teach/RUN.md`). The alternatives are a second trainer for groups of five or six, a cap of four, or a
  longer session.
- Session 2 group sizes. Every teacher needs at least two voters. With five, the trainer votes in pod B for two
  slots; with four, the group runs as one pod with 9-minute slots (`02-prior-knowledge/RUN.md`).
- Who types the session 2 question set file. The pack has each participant send it within two working days; the
  alternative is that the coordinator types it from the participant's card.
- Session 2's reading of a prior-knowledge 4 in a single cycle: a route call that uses the revote and sends learners
  who still chose a wrong option somewhere different from the rest. The head of training confirms or changes it.
- Session 2 needs each participant's unit in `standards/units/` with a misconceptions list. Only the example unit
  is there today, so until real units are mirrored every participant uses the T-7 fallback in the run sheet.
- Session 3 has the trainer run both pods' checkpoint rooms, so that the unreachable-room failure can be injected
  without the facilitator seeing it. The alternative is that facilitators run their own rooms and that failure is
  dropped, leaving three failures for three slots per pod.
- Session 3 uses the aggregates-only-export lab, which is not yet placed in a unit, so its feedback forms are
  printed from the example unit. The lab also has no offline wheels yet; the trainer brings the jsonschema wheel.
- The remote version of session 3 for partner facilitators (a shared remote lab with screen share) has no pack yet.
- Session 4 runs hybrid inside the building, because the checkpoint room page reaches only laptops on the same network
  and no relay exists for learners outside it. Partners take it fully remote and read checks from a poll and from
  checkpoint lines pasted in chat. The teach is six minutes, not ten, so two staggered pods fit with the trainer watching
  every teach, and the trainer's spoken feedback moves to a two-minute one-to-one. A second trainer would restore both.
- Session 5 needs, from the head of training: two excerpts of reference-scored sessions (20 and 15 minutes, each with a
  remote learner so every domain has a moment), a printed reference sheet with the anchor and timestamps behind each
  reference score, and the reference scores as a file in the private store. None of these exists yet.
- Whether the instructors in the session 5 recordings agreed to their recordings being shown for training. The pack
  says only that they are real people and that the training function holds the recordings.
- How long the scanned micro-teach forms are kept: `standards/retention.yaml` has no entry for train-the-trainer
  evidence yet.
- Who trains the trainers in the first cohort. The founding clearers (decision 0017) are the obvious choice, and the
  head of training decides.
- Whether session 5 should share recordings with W5 calibration exercises. Reusing them saves recording effort, but
  it means participants have seen the exercise recordings before they ever calibrate as observers.
