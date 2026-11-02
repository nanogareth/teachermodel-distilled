# Train-the-trainer session 3: Lab facilitation and recovery -- Participant Pack

> **Your name**: ____________________  **Date**: ____________________  **Pod and position**: ________
>
> Everything you need for session 3, in the order you need it: what to do **before**, how the
> session **runs**, the steps you work through **during** it, and what happens **after**.
>
> **Format**: one continuous 90-minute block, in person, in the same two pods as session 1. One
> trainer moves between them.
>
> **What you do**: open a hands-on lab for the rest of your pod, who work it as learners on their
> own laptops. Something in the room goes wrong during your opening, and you deal with it in front of
> them while keeping them working.
>
> **Bring a laptop.** You work the lab as a learner in the other slots, so your laptop needs the lab
> set up before you arrive. The pre-work below takes about twenty minutes.

<!-- pack:brief -->

## Before the session

### At a glance

| Field | Value |
|-------|-------|
| **Course** | Train-the-trainer, session 3 of 5 |
| **Duration** | One 90-minute block, and about twenty minutes the evening before to set up your laptop |
| **Group** | Four to six participants and one trainer, in your session 1 pods |
| **Scored on** | One rubric domain, lab facilitation, on the printed form |
| **You keep** | Your opening plan, your notes, and this pack |
| **Recorded** | A short failure log the trainer writes about your opening, which the coordinator checks and records |
| **Counts toward clearance** | No. The forms are practice, not observations |

### What this session is for

A hands-on lab depends on things the learners did not write: their laptops, the packages on them,
the room's network, the lab's own files, and the server that shows the room's progress. Any of them
can fail in the middle of a session, and when one does, the instructor has a room of learners
waiting to see what happens next.

The rubric describes four ways it can go. The lab stalls. The instructor fixes the one learner with
the problem while everyone else waits. The instructor says in front of the room what is wrong and
keeps everyone else working while it is put right. Or the instructor does all that and uses the
failure to teach something about checking evidence, which in a lab about testing is often the
point of the lab.

Today you practise the third and fourth. The trainer makes something fail during your opening, on
purpose, so that everyone gets one failure to handle. You do not know in advance what it will be.

### What you will be able to do

1. Open a hands-on lab for a small cohort: the task, the room page, and the first checks.
2. Notice when something in the room has failed, from the room page and from what learners' screens
   say, and name it out loud.
3. Keep the rest of the cohort working while one learner's problem is put right.
4. Score a peer's opening on the lab-facilitation anchors.

### The lab: aggregates-only export

The coordinator has sent you the lab's starter folder. The starter is exactly what a
learner receives, and its `README.md` is what they read first. In short:

- **The task.** `exporter/export.py` turns per-learner grader results into one row per delivery: how
  many learners were assessed, the pass rate, and a baseline to read it against. The output goes to
  a review outside the training team, so it must not identify any learner, and every number must mean
  what its field says. The visible tests pass. The README says plainly that this does not make the
  export safe, and the learners' job is to show why with their own tests.
- **The four steps.** `python checkpoint.py` lists them. Step 1 is the visible tests passing. Steps 2
  to 4 run the learner's own tests for each of the README's three properties, found by name: a test
  with `identity`, `baseline` or `refuses` in its name. A step passes when at least one test of that
  name exists and every one of them passes.
- **Step 2 takes a while.** A good identity test fails on the starter, because the starter leaks.
  So a learner on step 2 sees "not yet" until they have fixed the exporter. That is progress, and
  you can tell your learners so.

Your opening covers the task, joining the room, step 1 and the start of step 2. Nobody finishes the
lab today.

### The room page

The room page shows the whole cohort's progress on one screen. Each learner joins the room once,
with `python checkpoint.py --join <address> <code>`. After that, every check they run with
`python checkpoint.py <step>` also tells the room which step it was and whether it passed. It sends
nothing else: no name and no code.

The page lists the four steps and, for each, how many devices have passed it and how many are stuck
on it. It refreshes every five seconds. It counts **devices**, so a learner sharing a laptop with a
neighbour counts once. `python checkpoint.py --all` checks every step on the laptop and tells the
room nothing.

Every check prints its tests' output, then one last line: the step, PASS or "not yet", and whether
the result was reported to the room. When a learner says their check "did something odd", that last
line is the first thing to read.

**Today the room server runs on the trainer's laptop,** one for each pod. You show the room page in a
browser on your own laptop, turned towards your pod. If you need anything done to the room server,
tell the trainer what you want done, as you would tell a technician. They will do it, and they will
tell you what its window shows if you ask.

### What makes a good opening

You have nine minutes. A plan that works usually looks like this:

| Minute | What happens |
|---|---|
| 0-2 | The task in your own words, and what "safe to send" means. Learners open this slot's folder |
| 2-3 | The room: the page on your screen, the join command on the flipchart, everyone joins |
| 3-4 | Step 1: everyone runs it and reads the last line. You read the page |
| 4-9 | Step 2: what an identity test is and how it is named, then the learners work while you watch the page and the room |

Three habits matter more than the script:

- **Count the page against the room.** The page can only show the devices that report to it.
- **Give the room work before you go to one laptop.** Then say out loud, where everyone can hear,
  what you see on that laptop and what you think is wrong.
- **Ask learners to read you their screen.** Read the last line of a check before anything else.

### How you are scored

Lab facilitation has four anchors on the form:

| Score | Anchor | What it looks like in a nine-minute opening |
|---|---|---|
| 1 | Lab stalls on an environment or model failure | The opening stops: the facilitator is at one laptop and nobody else has anything to do, or the problem is never found |
| 2 | Recovers individual learners but the cohort loses pace | The learner with the problem is put right, and the other learner waited with nothing to do |
| 3 | Diagnoses a failing environment or non-deterministic output in front of the room and keeps the cohort moving | The facilitator says out loud what they see and what they think is wrong, and the other learner has work throughout |
| 4 | Turns a live failure into a teaching moment on verification | As 3, and the facilitator uses the failure to say something about checking evidence that the learners can use in the lab |

The other four domains come marked "not seen" on the form, and you leave them that way.

### Pre-work (about twenty minutes, the evening before)

1. Read the starter's `README.md` as a learner would.
2. Install what the lab needs: `python -m pip install pytest jsonschema`. On Windows, if `python`
   is not found, use `py` in its place throughout. On a Mac or Linux laptop it may be `python3`.
3. In the starter folder, run `python -m pytest -q`. It should pass.
4. Still in the starter folder, run `python checkpoint.py 1`. The last line should read
   `step 1 (The visible tests pass): PASS; not reported (no room joined)`.
5. Make five copies of the starter folder, next to each other, named `lab-trainer`, `lab-slot1`,
   `lab-slot2`, `lab-slot3` and `lab-slot4`. Each part of the session starts from a fresh copy, so
   do not run anything in the copies yet.
6. Reply to the coordinator by the date in their message: whether your laptop runs Windows, macOS
   or Linux, and whether steps 3 and 4 worked. If they did not, say what the screen showed.

### What to bring

- Your laptop, charged, with the five copies on it, and its charger
- Your instructor id, which you write on every form you fill in as a scorer
- A pen

### Pre-session self-check

- [ ] `python checkpoint.py 1` in the starter folder ends with "not reported (no room joined)".
- [ ] I have the five copies, and I have not run anything in them.
- [ ] I have read the README, and I could explain the task in two minutes.
- [ ] I know what the room page shows, and what the last line of a check tells me.
- [ ] I know my instructor id.

<!-- pack:demo -->

## How the session runs

One continuous 90-minute block in one room. The trainer opens the lab first, with the whole room as
learners, so that you work the lab and see an opening before you run your own. Before each phase the
trainer gives a one-minute briefing to the whole room.

| When | What runs |
|------|-----------|
| 0:00-0:05 | Welcome: the lab, delivery failures and the four anchors |
| 0:05-0:06 | Briefing: the trainer's opening |
| 0:06-0:20 | **Phase 1**: the trainer opens the lab for the room, then you take the opening apart |
| 0:20-0:21 | Briefing: planning |
| 0:21-0:28 | **Phase 2**: plan your nine-minute opening |
| 0:28-0:29 | Briefing: facilitation rounds |
| 0:29-1:14 | **Phase 3**: three slots of 15 minutes: an opening, silent scoring and a feedback round |
| 1:14-1:15 | Briefing: the lab's failure list |
| 1:15-1:22 | **Phase 4**: read the lab's failure list against what happened in your pod |
| 1:22-1:26 | Share-out, both pods together |
| 1:26-1:28 | Reflection, written |
| 1:28-1:30 | Wrap: the trainer collects every form |

### Pods, positions and slots

You are in the same pod and position as in session 1, and you open the lab in the slot that matches
your position. In the other slots you are a **learner** in your own pod, on your own laptop, and
afterwards a scorer.

| Slot | Opens the lab | Peer 1: learner, speaks first | Peer 2: learner, keeps time, speaks second | Learners' folder |
|---|---|---|---|---|
| 1 | Position 1 | Position 2 | Position 3 | `lab-slot1` |
| 2 | Position 2 | Position 3 | Position 1 | `lab-slot2` |
| 3 | Position 3 | Position 1 | Position 2 | `lab-slot3` |

If your group is four or five, the trainer tells you how the pods and slots work.

### The envelopes

At the start of Phase 1, and again at the start of Phase 2, the trainer hands you sealed envelopes,
one for each part of the session where you are a learner. Open each one only when that part starts,
and read the card without showing anyone. Most cards say there is nothing to do. A card may ask you
to do something on your laptop at a set moment, such as running a command. If it does:

- Do exactly what it says, when it says, and then keep working as a learner.
- When anyone asks what your screen shows, read it to them. Say nothing about the card until the
  slot ends.
- Whatever it changes is put back before the slot ends, and the trainer checks.
- If you do not want your laptop changed, hand the card back to the trainer unopened as the slot
  starts.

**As a learner, work the lab as yourself.** Read the README's task, try the steps, and ask the
facilitator when you are stuck, as you would in a real lab.

### The slot (15 minutes)

| Part | Time | What happens |
|---|---|---|
| Opening | 9:00 | The facilitator opens the lab: the task, the room page and the join command, step 1, then step 2. Learners work in this slot's fresh folder. The timekeeper stops it at nine minutes, finished or not |
| Silent scoring | 1:00 | Everyone except the facilitator scores lab facilitation on the form, with one line of evidence |
| Feedback round | 5:00 | In the order below |

### The form

The form is the same one as in sessions 1 and 2. Only lab facilitation is scored today; the other
four domains come marked "not seen". Write your own instructor id as **Observer id**. Score alone
and in silence, and write one line of evidence for your score: what happened, and roughly at what
minute.

### The feedback routine (5 minutes)

| Turn | Who | Time | What happens |
|---|---|---|---|
| 1 | Facilitator | 0:45 | What you noticed, at what minute, and what you thought it was |
| 2 | Peer 1 | 0:45 | Lab facilitation, in the stem: the minute the problem showed and the minute the facilitator named it out loud |
| 3 | Peer 2 | 0:45 | Lab facilitation, in the stem: what the other learner was doing while it was handled |
| 4 | Trainer | 2:00 | Score, the two minutes that decided it, and one move for next time. If the trainer is in the other pod: each peer names the minute the pod stopped moving, if it did, and one move that would have kept it moving, a minute each |
| 5 | Facilitator | 0:45 | You name the one move you will make next time, write it in box 3.1, and take the forms |

### How to say a score

The stem is the session 1 stem:

> "I scored lab facilitation at [number]. The anchor for [number] says [its words]. What I saw was
> [what happened, and roughly when]."

Two invented examples, from openings of a different lab:

> "I scored lab facilitation at 2. The anchor for 2 says 'recovers individual learners but the
> cohort loses pace'. At minute 4 you went to my neighbour's laptop and stayed there for three
> minutes. It was working again by minute 7, and I had stopped at step 1 because I did not know what
> to do next."

> "I scored lab facilitation at 3. The anchor for 3 says 'diagnoses a failing environment or
> non-deterministic output in front of the room and keeps the cohort moving'. At minute 5 you told us
> to start the next exercise, then said out loud that one laptop had the wrong version of the
> library, while you fixed it."

<!-- pack:worksheet -->

## During the session

This is your own record, and you keep it. The forms are collected at the end; this pack is not.

In the step lists, **[A]** is everyone, **[F]** is the facilitator and **[L]** is the learners. When
you are not opening the lab, you are a learner.

### Phase 1 -- The trainer's opening (14 min, 0:06-0:20, whole room)

> **Briefing at 0:05**, one minute. You are the trainer's learners, working in your `lab-trainer`
> folder. Open your Phase 1 envelope when the trainer says, and read the card without showing
> anyone.

```text
1. Open your envelope, listen to the task, and join the room from your    [A]  2 min
   lab-trainer folder with the command on the flipchart
   done when: your laptop prints "joined room" and the code
2. Run step 1 and read the last line it prints                            [A]  4 min
   done when: the trainer moves the room on to step 2
3. Start step 2: write a test with identity in its name                   [A]  3 min
   done when: the trainer stops the opening
4. Score the trainer's opening in silence in box 1.1                      [A]  1 min
   done when: box 1.1 has a score and one line of evidence
5. Take the opening apart with the trainer: which minute matched which    [A]  4 min
   anchor
   done when: the trainer has been through the four anchors
```

**1.1 -- Your score for the trainer's opening.**

| | |
|---|---|
| Lab facilitation score | |
| One line of evidence, with the minute | |
| One thing the trainer did that you will do in your opening | |

### Phase 2 -- Plan your opening (7 min, 0:21-0:28, on your own)

> **Briefing at 0:20.** You get your slot slip and your envelopes. Plan your nine minutes alone.
> Do not open the envelopes until their slot starts.

```text
6. Read your slot slip, then the README again                             [A]  2 min
   done when: you know your room code and your learners' folder
7. Plan your nine-minute opening in box 2.1                               [A]  4 min
   done when: every row of box 2.1 has what you will say or do
8. Get ready for slot 1: a terminal in lab-slot1, or the room page from   [A]  1 min
   your slip if you open the lab in slot 1
   done when: your screen is ready
```

**2.1 -- Your opening.**

| Minute | What you say or do | What you watch |
|---|---|---|
| 0-2: the task | | |
| 2-3: the room | | |
| 3-4: step 1 | | |
| 4-9: step 2 | | |
| If a learner's check does something odd, the first thing you do | | |

### Phase 3 -- Facilitation rounds (45 min, 0:29-1:14, in your pod)

> **Briefing at 0:28.** Three slots of fifteen minutes, in your session 1 positions. Nine minutes
> of the opening, one of silent scoring, five of feedback. When you are a learner, open that slot's
> envelope as the slot starts and work in that slot's folder.

```text
9. Open the lab for your pod: the task, the room, step 1, step 2.         [F]  9 min
   Learners work the lab in this slot's folder
   done when: peer 2 calls nine minutes, finished or not
10. Score the opening in silence, lab facilitation only                   [L]  1 min
    done when: every learner has a score or "not seen" and a line of
    evidence
11. Run the feedback round in the order of the table, and name the one    [L]  5 min
    move
    done when: the facilitator has written the move in box 3.1 and has
    the forms
```

**3.1 -- Your opening** (fill in after your own slot).

| | |
|---|---|
| What went wrong, as you saw it | |
| The minute you noticed, and how | |
| What the other learner was doing meanwhile | |
| The one move you will make next time | |

- [ ] Opened the lab, and got learners to step 2
- [ ] Scored every opening I was a learner in, in the silent minute, with evidence
- [ ] Spoke in the stem when it was my turn

### Phase 4 -- The lab's failure list (7 min, 1:15-1:22, in your pod, then on your own)

> **Briefing at 1:14.** The trainer hands out the lab's failure list: each failure, how it was
> made to happen, and what a facilitator is expected to do about it. It goes back to the trainer
> at the end.

```text
12. In your pod, find each slot's failure on the list and read its        [A]  3 min
    expected handling against what happened
    done when: your pod has matched all its slots
13. Fill in box 4.1 for your own slot, and hear your failure log from     [A]  4 min
    the trainer
    done when: every row of box 4.1 is filled in
```

**4.1 -- Your slot against the list.**

| | |
|---|---|
| The failure in your slot, by its id on the list | |
| What the list expects a facilitator to do | |
| What you did | |
| What you will do next time it happens | |

### Share-out (1:22-1:26, both pods together)

About a minute and a half per pod: for each slot, the failure, the minute it showed, and the minute
the facilitator said out loud what it was.

### Reflection (1:26-1:28)

**R.1 -- Which failure on the list would hurt your own lab most, and what will you check before the
cohort arrives?**

> ______________________________________________________________________

**R.2 -- What did you say in front of your pod that you would say again?**

> ______________________________________________________________________

<!-- pack:rubric -->

## After the session

### Your failure log

Your record for this session is a short file the trainer writes at the end of your slot and reads
to you in Phase 4. It has five fields:

| Field | What it holds |
|---|---|
| `lab` | The lab: `aggregates-only-export` |
| `failure` | The id of the failure the trainer made happen in your slot, as it appears on the lab's list |
| `against_expected` | `met`, `partly` or `missed`: how what you did compares with what the list expects a facilitator to do |
| `cohort_kept_moving` | `true` if the other learners kept working while it was handled, `false` if they waited |
| `what_was_done` | Two or three sentences on what you did and roughly when, at most 600 characters, with no names |

The coordinator checks the file, stores it in the private store and records session 3 on your
course record, dated the day of the session. If you think the log is wrong, say so when the trainer
reads it to you: it can be corrected then, before you leave.

### What happens to your forms

The trainer collects every form at 1:28 and gives them to the coordinator the same day. They are
kept in the private store with your session 1 forms. They are not the record for this session: the
failure log is.

The forms are formative. They are not observations, they never count toward your clearance, and
only the technical training function sees them: your manager does not, and neither does anyone
running a performance review.

### What you keep for later sessions

- **Box 3.1 and box R.1.** Session 4 has you teach remotely and read the room from the same page,
  with no faces to read.
- **Box 1.1.** Session 5 asks you to score recordings on all five domains, lab facilitation among
  them.
- **Your copies of the lab.** Delete them when you like; nothing in them is needed again.

### How this is marked

It is not marked, and there is no pass mark. Session 3 counts as complete once the coordinator has
recorded your failure log. The course is complete when all five sessions are recorded.
