# Train-the-trainer session 3: Lab facilitation and recovery -- Run Sheet

> The only document you need on the day. Participant-facing content lives in `LEARNER.md`; the step
> numbers below refer to its step list. Course design: `docs/train-the-trainer/DESIGN.md`, row 3.
> The lab is `scenarios/aggregates-only-export` in the proving-ground repository.

| Field | Value |
|-------|-------|
| **Envelope** | 90 min, one continuous block. Four phases on one clock, no break |
| **Mode** | In person. One trainer and one group of 4 to 6, in the session 1 pods at opposite ends of one room. Every participant works on their own laptop |
| **Roles** | In Phase 1 you open the lab and the whole room are your learners. In Phase 3, per slot: one facilitator, the rest of the pod as learners on their own laptops, and you, who inject one failure and move between the pods. Peer 2 keeps time |
| **Tools** | The `aggregates-only-export` lab: its starter on every laptop, and its checkpoint collector (the room page) on your laptop. Printed forms from `teachermodel paper` (decision 0022), sealed inject cards in envelopes, slot slips, and a printed catalogue sheet that stays sealed until 1:14 |
| **Slice** | The opening of the lab: the task, joining the room, step 1 (the visible tests pass) and the start of step 2 (the learner's own identity tests) |
| **Evidence** | One failure log per participant, a YAML file you write on your laptop at the end of their slot, checked with `teachermodel check-failure-log` and recorded by the coordinator. The forms are feedback only: formative, not observations, never counted toward clearance |
| **Recording** | None. Nothing is filmed |
| **Hardware / cost** | A laptop per participant with Python 3, pytest and jsonschema; your laptop with a proving-ground checkout; a local network that lets the laptops reach yours; a projector or large screen for Phase 1; two USB sticks with the jsonschema wheel; about 14 printed forms, 7 catalogue sheets and 20 envelopes for a group of six |

**Both pods run on one clock,** as in sessions 1 and 2. One call from you moves both pods to the
next turn.

**Every participant opens the lab once, for the rest of their pod.** They have nine minutes to get
two learners from a fresh copy of the starter to work on step 2, with the room page showing where
everyone is. In that time you inject one delivery failure from the lab's catalogue, and they have to
notice it, say in front of the pod what is wrong, and keep the other learner working while it is
put right. Then the pod scores the opening on lab facilitation and nothing else.

**Your injections are staggered so that you see every one.** In each slot one pod gets a failure
that shows in the first four minutes and the other gets one at five and a half minutes. You watch
the first pod until its failure is handled, cross the room, and watch the second. Each facilitator's
failure log rests on what you saw.

---

## BEFORE

### What you need in your head

- **What a delivery failure is.** Something in the environment, not in the learner's work, that
  stops a check or a report: a missing package, a lab file that is not what the lab expects, the
  room's network, the room server. The lab's `staff/catalogue.yaml` lists four for this lab under
  `failure_catalogue`, each with how to inject it and the handling a facilitator is expected to
  show. That handling is what you judge the log against.
- **The four anchors.** Lab facilitation scores 1 when the lab stalls on an environment or model
  failure, 2 when the facilitator recovers individual learners but the cohort loses pace, 3 when they
  diagnose the failing environment in front of the room and keep the cohort moving, and 4 when they
  turn the live failure into a teaching moment on verification. A nine-minute opening can show all
  four, so a 4 is possible today.
- **Why inject.** Waiting for a real failure would give some participants one and others none. An
  injected failure gives everyone one, at a time you choose, from a list whose expected handling is
  written down.
- **Participants do not see the catalogue until 1:14.** The facilitator does not know which failure
  is coming. The learner-peer who injects it knows only what their card says. `LEARNER.md` names no
  failure and gives no handling, and you say nothing about the four until Phase 4.
- **You are the facilitator's technician.** Both pods' room servers run on your laptop, because one
  failure is a server that stops, and you have to stop it without the facilitator seeing you. If a
  facilitator asks you to do something to their room server, do it. If they ask what its window
  shows, tell them.
- **You do not need to know the lab's content.** The failures are in the environment. Know the four
  catalogue entries well enough to recognise each one from a learner's screen, using the table
  below.
- **The same scores, the same rules.** The forms are formative, they are not observations, they
  never count toward clearance, and only the training function sees them (decision 0005). The
  feedback routine is the session 1 routine: silent scores first, then the facilitator, then the
  peers, then you, then the facilitator again. You fill in no form today. Your written record of each
  opening is its failure log.

### What each failure looks like

Every check ends with one line: the step, PASS or "not yet", and what happened to the report. With
no room joined it says "not reported (no room joined)". `python checkpoint.py --all` runs every step
on the laptop and reports nothing to the room.

| Failure | How you inject it today | What the learner's last line says | What the room page shows | The moves the catalogue expects |
|---|---|---|---|---|
| `stale-room-code` | Card: join with `OLD1` in place of the slot's code | `step 1 (The visible tests pass): PASS; not reported (the room refused it: 403)` | One device fewer than there are learner laptops | Ask who sees "refused"; have them join again with today's code; re-run their latest step. Their result was never in doubt, only the report |
| `room-unreachable` | You press Ctrl+C in that pod's collector window at 5:30 | `step 1 (The visible tests pass): PASS; not reported (the room could not be reached)` | The browser can no longer load the page at its next five-second refresh | Tell the room their work is unaffected; take a show of hands per step while the page is down; restart the collector with the same `--room` code; ask learners to re-run their latest step, because the page counts from zero after a restart |
| `jsonschema-missing` | Card: `python -m pip uninstall -y jsonschema`, before step 1 or at 5:30 before step 2 | `not yet`, and above it `ModuleNotFoundError: No module named 'jsonschema'` from collecting `tests/test_export.py` | That device stuck on step 1 (or step 2) | Install it with pip, or from the offline wheels when the room has no network; pair the learner with the other learner while it installs |
| `backslash-glob` | Card, **Mac or Linux laptop only**: the first `results` glob in `sample/manifest.json` changed to backslashes | `not yet`: `test_the_sample_pass_rates` finds 0 learners in cohort-a where it expects 8 | That device stuck on step 1 | Use it to show why the empty-delivery refusal matters: the starter exports cohort-a as 0 learners at 0.0 without complaint. Then fix the manifest to forward slashes |

**`backslash-glob` does nothing on Windows.** There the backslash glob still matches the eight
files, every test passes and nothing goes wrong. Use it only when the card holder's laptop runs macOS
or Linux, and ask at T-7 which laptops do.

The room page refreshes every five seconds and counts devices, not people. It keeps progress in
memory only, so a restarted collector starts from zero and the learners' next checks fill it again.

### Judging the log

Write `against_expected` from the moves in the last column above:

- **met:** every move for that failure, in any order and in the facilitator's own words.
- **partly:** at least one move. Restarting the room with a new code (so every learner has to join
  again) is partly, and so is fixing the learner while the rest of the pod waits with nothing to do.
- **missed:** none of the moves. A failure the facilitator never found is missed.

`cohort_kept_moving` is `true` when the other learner had work to do and was doing it while the
failure was handled, and `false` when they waited. It says nothing about whether the failure was
fixed.

`what_was_done` is at most 600 characters and holds no names: not the facilitator's, not a
learner's. Say what the facilitator did, in order, with roughly when. An example:

```yaml
lab: aggregates-only-export
failure: stale-room-code            # an id from the lab's failure_catalogue
against_expected: met
cohort_kept_moving: true
what_was_done: At min 3 counted one device on the page against two learner laptops and said so. Sent the other learner on to step 2, asked who saw "refused", had that learner join again with today's code and re-run step 1. Told the pod the result had passed all along and only the report was refused.
```

A partly, for comparison:

```yaml
lab: aggregates-only-export
failure: room-unreachable
against_expected: partly
cohort_kept_moving: false
what_was_done: Noticed the page had gone at min 6 and asked the trainer to restart the room with a new code. Both learners stopped work to join again and re-run step 1. No show of hands while the page was down.
```

### T-7 -- send to learners

- [ ] `LEARNER.md` (as DOCX or PDF)
- [ ] The lab starter, as a zip of `scenarios/aggregates-only-export/starter/` from proving-ground.
      Check the folder has no `.checkpoint-room` file before you zip it
- [ ] Nothing from `staff/`. The lab note lists the seeded defects, and the catalogue, the hidden
      tests and the solution stay with you too
- [ ] One blank form, and each participant's instructor id in a message to that person alone, as for
      sessions 1 and 2
- [ ] A request to reply by T-3 with two things: whether their laptop runs Windows, macOS or Linux,
      and whether the pre-session self-check in `LEARNER.md` passed

**A laptop that cannot run the lab** (no Python, or a managed laptop that blocks installs). The
participant still takes the session. As a learner they work on a pod neighbour's laptop with them, and
the facilitator is told at launch that one device is shared. As the facilitator they need only a
browser to show the room page. No card that changes a laptop goes to them. If more than one
participant in a pod has no working laptop, move one to the other pod at T-1.

### T-1 -- prepare

- [ ] **Your laptop.** A current proving-ground checkout, Python 3, and two terminal windows open
      in the proving-ground folder, titled POD A and POD B. Start one collector to check it runs:
      `py tools/checkpoints/collector.py --steps scenarios/aggregates-only-export/starter/checkpoints.json --port 8765 --room MAPLE`.
      If Windows asks whether to allow Python on the network, allow it, or the other laptops cannot
      reach the room. Stop it with Ctrl+C.
- [ ] **The collector card.** One line per slot, which you start from the window named. Each
      command is the one above with the port and code in this table. The codes avoid the letters I
      and O so that nobody misreads them.

| When | Window | Port | Room code |
|---|---|---|---|
| Phase 1 | POD A | 8765 | `MAPLE` |
| Slot 1 | POD A / POD B | 8765 / 8766 | `AMBER` / `BERRY` |
| Slot 2 | POD A / POD B | 8765 / 8766 | `ASPEN` / `BEECH` |
| Slot 3 | POD A / POD B | 8765 / 8766 | `ATLAS` / `BRAVE` |
| Slot 4 (group of four only) | POD A | 8765 | `AZURE` |

- [ ] **The injection plan.** Fill in the group's table below with positions, and decide where
      `backslash-glob` goes from the T-3 replies. Keep the plan on paper, with you.

| Group | Slot 1 | Slot 2 | Slot 3 | Your pod in each slot |
|---|---|---|---|---|
| 6 | A: `stale-room-code`, early. B: `room-unreachable`, late | A: `room-unreachable`, late. B: `stale-room-code`, early | A: `jsonschema-missing`, early. B: `jsonschema-missing`, late (card at 5:30) | A then B; B then A; A then B |
| 5 | As for 6 | As for 6 | A only: `jsonschema-missing`, early. Pod B's two join pod A as learners and do not score | A then B; B then A; A throughout |
| 4 | One pod of four, four slots: `stale-room-code`, `room-unreachable` (you stop it at 4:00), `jsonschema-missing`, then `backslash-glob` in slot 4 if a slot 4 learner has a Mac or Linux laptop, otherwise `stale-room-code` again | | | The pod, throughout |

`backslash-glob` can replace the early failure of any slot whose card holder has a Mac or Linux
laptop; each pod's three failures stay different whichever early slot you pick. A pod's three
facilitators always get three different failures. The two learner-peers in a slot never both hold
an active card.

- [ ] **The envelopes.** Each participant gets one envelope marked "Phase 1" and one marked with
      each slot they are a learner in ("Slot 2", "Slot 3"). Write their pod and position on the
      outside, never the failure. Inside is one card. Most cards are blank; one card per slot per
      pod is active. The wording of every card is below.
- [ ] **The slot slips.** One per participant: pod, position, slot, room code, the folder their
      learners use (`lab-slot1` for slot 1, and so on), and two blank lines for the room page address
      and the join command, which you fill in at T-15.
- [ ] **The failure log templates.** One file per participant on your laptop, named by instructor
      id, for example `ttt3-0007.yaml`. Fill in `lab` and `failure` from the plan now and leave the
      rest blank. A blank template fails the check, so an unfinished log cannot be recorded by
      mistake.

```yaml
lab: aggregates-only-export
failure: stale-room-code
against_expected:            # met, partly or missed
cohort_kept_moving:          # true or false
what_was_done:
```

- [ ] **Print the forms.** The lab is not placed in a unit yet, so run `teachermodel paper --unit
      sl:unit/example-agent-loop@1` and print its `rubric.html` twice per participant (three times
      in a group of four), plus two spares. Write "Session 3: aggregates-only-export lab opening"
      under the title.
- [ ] **Fill in the headers.** On every form: Date; Instructor id is the facilitator's id; Delivery
      reference is "TTT-3 lab opening"; Length is "lab opening 9 min" (7 in a group of four); Mode is
      in person; Instructor led is yes; From a recording is no. Write "FORMATIVE: lab opening, not an
      observation" across the top. In the evidence notes for technical depth, prior knowledge,
      conceptual questioning and remote and inclusive delivery, write "not seen; session 3 scores
      lab facilitation only". Leave Observer id blank.
- [ ] **The catalogue sheet.** Print only the `failure_catalogue` part of `staff/catalogue.yaml`
      (id, inject, expected_handling for the four) once per participant and once for you. Put the
      participants' copies in one sealed envelope.
- [ ] **The wheels.** On your laptop run `py -m pip download jsonschema --no-deps -d wheels` and
      copy the `wheels` folder onto two USB sticks, one per pod. The jsonschema wheel is pure Python,
      so it installs on any laptop whose other packages are still in place, which they are after
      `pip uninstall jsonschema`. Label the sticks "Lab kit: offline wheels".
- [ ] **Keep the session 1 pods and positions,** and write them on the pod cards. If the group has
      changed, rebuild the pods from the session 1 table, with people from different specialisms
      together.
- [ ] **Book the room.** One room with a projector or large screen, a flipchart at each end, and a
      network all the laptops join. Ask the venue whether laptops on its network can reach each
      other; many guest networks block it.

**The cards.** Print each on its own card. The commands are written for Windows; on a Mac or
Linux laptop `python3` may stand in for `python`.

| Card | Wording |
|---|---|
| Blank | "Nothing to do this slot. Work the lab as yourself, and when anyone asks, say what your screen shows. Keep this card face down." |
| Phase 1, wrong folder | "Join the room as everyone else does. Then type `cd ..` and run `python checkpoint.py 1` from there. Keep working as a learner who has not noticed anything odd. If anyone asks what your screen shows, read it to them; say nothing about this card." |
| `stale-room-code` | "When the facilitator gives the join command, type it with the code `OLD1` in place of the code shown: `python checkpoint.py --join <the address shown> OLD1`. Then keep working as a learner. If anyone asks what your screen shows, read it to them; say nothing about this card until the slot ends." |
| `jsonschema-missing`, early | "Before you run step 1, run `python -m pip uninstall -y jsonschema`. Then keep working as a learner. If anyone asks what your screen shows, read it to them; say nothing about this card until the slot ends. The package goes back on before the slot ends." |
| `jsonschema-missing`, late | "When the pod's timer shows 5:30, run `python -m pip uninstall -y jsonschema`, then run `python checkpoint.py 2` whatever state your test is in. Keep working as a learner. If anyone asks what your screen shows, read it to them; say nothing about this card until the slot ends. The package goes back on before the slot ends." |
| `backslash-glob` (Mac or Linux only) | "Before you run step 1, open `sample/manifest.json` in this slot's folder and change the first results line to the line printed below. Save it and keep working as a learner. If anyone asks what your screen shows, read it to them; say nothing about this card until the slot ends." |

Print this line on the `backslash-glob` card, exactly as it is here. JSON needs each backslash
written twice, so the file then asks for `results\cohort-a\*.json` with single backslashes:

```text
    "results": "results\\cohort-a\\*.json",
```

### T-15min -- room

- [ ] **Test the room.** Start the Phase 1 collector (POD A window, port 8765, `MAPLE`). From the
      first participant to arrive, or a second device of your own, join with the command the
      collector printed and run `python checkpoint.py 1` in a copy of the starter. The last line
      must end "reported to the room", and the page must show one device. If it says "the room
      could not be reached", see the network fallback under Recovery moves before anyone else
      arrives.
- [ ] Write the address the collector printed (`http://<address>:8765` and `:8766`) on every slot
      slip, with the join command for that slot's code.
- [ ] The room page on the projector, and a USB stick of wheels at each end of the room.
- [ ] Each end of the room has its pod card, a timer, a flipchart with pens, and that pod's forms in
      slot order.
- [ ] The envelopes in pod and position order, and the sealed catalogue sheets with you.
- [ ] `LEARNER.md` open at the step list. Your time calls refer to step numbers.

---

## DURING

### Demo list

Declared per the cadence rule. A phase gets a 5-minute demo when it introduces a software tool no
earlier phase used (**4a**) or needs a non-obvious feature interaction (**4b**). Phase 1 introduces
the lab, its checkpoint script and the room page, which is a 4a trigger. It gets a gate-check, and no
separate demo, because Phase 1 is itself the demonstration: you open the lab with the participants as
your learners, and they use every tool on their own laptops while you do. A demo card before it
would show the same nine minutes twice.

| Phase | Tool | Demo | Trigger |
|---|---|---|---|
| 1 | Lab, checkpoint script and room page | gate-check | 4a met; Phase 1 is your modelled opening, with participants working the lab hands-on |
| 2 | Paper plan -- no tool | gate-check | n/a; individual planning in `LEARNER.md` |
| 3 | Lab, checkpoint script and room page | gate-check | n/a; the tools from Phase 1, used again |
| 4 | Paper -- no tool | gate-check | n/a; reading the catalogue sheet against what happened |

### The clock

Four gate-checks at 1 minute, 73 minutes of modelling, planning, lab openings and debriefing in four
phases, and 13 minutes of welcome, share-out, reflection and wrap. That is 90 exactly. If you are
running late, take the minutes from the share-out and then from the reflection. Never shorten a
Phase 3 slot: an opening that loses two minutes may never reach the failure.

| From | To | Min | Segment | Kind |
|---|---|---|---|---|
| 0:00 | 0:05 | 5 | Welcome: the lab, delivery failures and the four anchors | framing |
| 0:05 | 0:06 | 1 | GATE-CHECK -- Phase 1, the modelled opening | gate-check |
| 0:06 | 0:20 | 14 | Phase 1 work -- you open the lab for the room, a failure appears, then taken apart | work |
| 0:20 | 0:21 | 1 | GATE-CHECK -- Phase 2, plan your opening | gate-check |
| 0:21 | 0:28 | 7 | Phase 2 work -- read the lab and plan the nine minutes | work |
| 0:28 | 0:29 | 1 | GATE-CHECK -- Phase 3, facilitation rounds | gate-check |
| 0:29 | 1:14 | 45 | Phase 3 work -- three slots of 15 min: opening, scoring, feedback | work |
| 1:14 | 1:15 | 1 | GATE-CHECK -- Phase 4, the catalogue | gate-check |
| 1:15 | 1:22 | 7 | Phase 4 work -- read the catalogue against your pod's slots | work |
| 1:22 | 1:26 | 4 | Share-out: what showed, and when it was named | share-out |
| 1:26 | 1:28 | 2 | Reflection | reflection |
| 1:28 | 1:30 | 2 | Wrap, forms and catalogue sheets | wrap |

**The phases are the participants' work.** In Phase 1 they are your learners; in Phase 2 they plan;
in Phase 3 they open the lab, work it as learners and score; in Phase 4 they read the catalogue.

### 0:00-0:05 Welcome: the lab, delivery failures and the four anchors (plenary)

- **0:00** Everyone in the middle of the room, laptops open, the room page on the projector.
- **0:01** Frame the session: *"Today each of you opens a hands-on lab for the rest of your pod. You
  have nine minutes to get them from a fresh copy to work on the second check, with the room page
  showing where everyone is. Somewhere in those nine minutes something in the room will go wrong,
  because I will make it go wrong. What we are watching is what you do then."*
- **0:02** The lab: *"The lab is an exporter that turns learners' results into pass rates for a
  review outside the team. Its visible tests pass, and the export is still not safe to send. The
  learners' job is to find out why and prove it with their own tests. Each check they run reports to
  a room page, so you can see from the front who has passed which step and who is stuck."*
- **0:03** Delivery failures and the anchors: *"A delivery failure is something in the room, not in
  the learner's code: the laptop, the network, the room server, the lab's own files. The rubric has
  four anchors for it. One: the lab stalls. Two: you fix the learner with the problem, and everyone
  else waits. Three: you say in front of the room what is wrong, and everyone else keeps working.
  Four: you use the failure to teach something about checking your evidence."*
- **0:04** *"The scores work as they did in session 1. They are practice, they are not observations,
  they never count toward clearance, and only the training function sees them. Today they cover one
  domain, lab facilitation. The record for this session is a short log I write about your slot."*

> Watch for a participant whose self-check failed and who did not reply. Find out now whether their
> laptop runs the lab, and pair them with a neighbour if it does not. See the T-7 note.

#### GATE-CHECK -- Phase 1, the modelled opening (1 min, broadcast)

Hand every participant their Phase 1 envelope as you speak.

*"For the next nine minutes you are my learners, working in your lab-trainer folder. Open your
envelope now and read the card without showing anyone. Most of you have a card that says nothing to
do. If yours asks you to do something, do it at the moment it says, and otherwise behave as a learner
would. After nine minutes you score me in silence, and then we take the opening apart."*

### 0:06-0:20 Phase 1 -- you open the lab for the room, a failure appears, then taken apart (plenary)

This is the opening participants run in Phase 3, at the same length: nine minutes, then one minute
of silent scoring. The planted failure is not one of the catalogue's four. A learner runs step 1 from
the folder above the lab, so the check never runs and the laptop never reports.

- **0:06** The task, in a minute: *"You have an exporter that turns grader results into one row per
  delivery: learners assessed, the pass rate, and a baseline. It goes to a review outside the team,
  so nothing in it may identify a learner and every number has to mean what it says. The visible
  tests pass. That does not make it safe, and your job is to show why with your own tests."*
- **0:07** Write the join command from the collector window on the flipchart. *"From your lab-trainer
  folder, run this once. It tells the room page which step you reach, and nothing else: no name and
  no code."* Watch the device count on the projector climb.
- **0:08** *"Now step 1: `python checkpoint.py 1`. Read the last line it prints."*
- **0:09** Read the page aloud and count the room, for example: *"Step 1 has passed on five devices,
  and I count six laptops."* Give
  the room work first: *"If your last line says 'reported to the room', start step 2 now: open
  `exporter/export.py` and look for anything in a row that could lead back to a learner."*
- **0:09:30** Then, to the room: *"Who does not have 'reported to the room' on their last line?"* Go
  to that laptop and have its owner read the first line of the output aloud: it cannot open
  `checkpoint.py`. Say what you see so the room hears it: *"The terminal is one folder above the lab,
  so the check never ran. `cd lab-trainer` and run it again."* Watch the page reach six.
- **0:11** The verification point, to everyone: *"That check never ran, and nothing on the page told
  us. The page counts the reports it receives, so a laptop that never reports looks the same as a
  laptop that is not in the room. This lab is about the same thing: its visible tests pass, and they
  cover less than they seem to. So when a check finishes, read its last line, and before you trust
  the page, count it against the room."*
- **0:12** Brief step 2: *"Step 2 checks your own tests. Write a test with `identity` in its name,
  for example `test_identity_file_names_stay_out`, that fails while anything in the output can lead
  back to a learner. Then run `python checkpoint.py 2`. While the exporter still leaks, 'not yet' is
  the right answer, and the page will show you as stuck on step 2. That is where you should be."*
- **0:13** Walk the room. Read the page aloud once: how many have passed step 1, how many are
  stuck on step 2.
- **0:15** *"Stop. One minute: score my opening in box 1.1, lab facilitation only, with one line of
  evidence."*
- **0:16** Take it apart, by the clock:
  - *"At 0:09 I saw five devices on the page and six laptops. That is noticing, and the page alone
    could not have done it: I had to count the room."*
  - *"The first thing I said was to everyone else: go on to step 2. Then I went to the one laptop.
    If I had gone straight to the laptop and said nothing, five of you would have waited, and that
    is the anchor for 2."*
  - *"I said what was wrong where you could all hear it. That is the anchor for 3."*
  - *"Then I said something about evidence that you could use in the lab. That is the anchor for 4."*
- **0:18** Ask for their scores by a show of fingers. If anyone gave 4, ask what they would have
  needed to see to give 3, and the other way round.
- **0:19** The record: *"At the end of your slot I write a short log: which failure it was, whether
  you did what the lab's catalogue expects for it, whether the rest of your pod kept working, and two
  or three sentences on what you did. No names. You see the catalogue at 1:14, and I read you your
  log then."*

| Broadcast at | Say | Step gate |
|---|---|---|
| ~0:08 | "Run step 1 of the lab and read the last line it prints. That is step 2 in your pack." | step 1 done |
| ~0:12 | "Start step 2 of the lab: a test with identity in its name. That is step 3 in your pack." | step 2 done |
| ~0:15 | "Stop. Score my opening in silence in box 1.1. Step 4." | step 3 done |
| ~0:16 | "Pens down. We take it apart now, step 5." | step 4 done |

> **If the planted learner reports anyway** (the card was misread), say so to the room, read the
> page as it is, and take the opening apart from what did happen. The anchors still apply to the
> parts they saw.

#### GATE-CHECK -- Phase 2, plan your opening (1 min, broadcast)

Stop the `MAPLE` collector. Hand out the slot slips and the slot envelopes as you speak.

*"Seven minutes, alone, steps 6 to 8. Your slip says your pod, your slot, your room code and the
folder your learners use. Plan your nine minutes in box 2.1: what you say about the task, when they
join, when they run step 1, what you say about step 2, and where you will look while they work. The
envelopes are for the slots where you are a learner. Do not open them until that slot starts."*

### 0:21-0:28 Phase 2 -- read the lab and plan the nine minutes (individual)

Participants plan in `LEARNER.md` box 2.1 with the README in front of them.

**While they plan, walk the room.** In each plan, look for these four things in order:

1. **A launch that runs past minute 3 before anyone types anything.** Ask: *"At what minute does
   your first learner run a command?"*
2. **No plan for where to look.** Ask: *"While they work on step 2, what are you watching: the page,
   the screens, or both?"*
3. **A plan that puts the facilitator at one laptop for minutes.** Ask: *"If one learner's check
   goes wrong at minute 4, what is the other one doing?"*
4. **A step 2 brief that does not say the test name must contain `identity`.** Without it the check
   finds no test and stays at "not yet".

- **0:27** Start the slot 1 collectors: `AMBER` on 8765 in the POD A window and `BERRY` on 8766 in
  the POD B window. With a group of four, start only `AMBER`.

| Broadcast at | Say | Step gate |
|---|---|---|
| ~0:23 | "Two minutes in. Plan your nine minutes in box 2.1 now. Step 7." | step 6 done |
| ~0:27 | "One minute left. Open a terminal in your lab-slot1 folder, or the room page from your slip if you open the lab in slot 1. Step 8." | step 7 done |

#### GATE-CHECK -- Phase 3, facilitation rounds (1 min, broadcast)

Everyone moves to their pod. Say this to the whole room as they go.

*"Three slots of fifteen minutes, steps 9 to 11, in your session 1 positions. The facilitator has
nine minutes to open the lab for the other two, using the room code on their slip. Learners, open
the envelope for the slot when it starts, work in that slot's folder, and work the lab as yourselves.
The timekeeper stops the opening at nine minutes. Then one minute of silent scoring on lab
facilitation only, and the feedback round on your card. I move between the pods. Position 1, open
the room page and begin."*

### 0:29-1:14 Phase 3 -- opening, scoring and feedback (two pods, three slots)

| Slot | Opening | Silent scoring | Feedback round | You start in (early failure) | You move to (late failure, and its feedback) |
|---|---|---|---|---|---|
| 1 | 0:29-0:38 | 0:38-0:39 | 0:39-0:44 | A | B |
| 2 | 0:44-0:53 | 0:53-0:54 | 0:54-0:59 | B | A |
| 3 | 0:59-1:08 | 1:08-1:09 | 1:09-1:14 | A | B |

In each slot the facilitator is the person whose position matches the slot. **Peer 1** is the
person who opens the lab next (in slot 3, position 1), and **peer 2** is the remaining person, who keeps
time. Both are learners during the opening and scorers afterwards.

**What you do in each slot, by the pod's timer:**

| Timer | What you do |
|---|---|
| 0:00 | From slot 2 on, restart both collectors with the slot's codes. Go to the early pod |
| 0:00-4:30 | Watch the early pod from outside the learners' line of sight. Note minute stamps: "min 3: page 1 device, 2 laptops", "min 4: asks who sees refused" |
| 4:30 at the latest | Leave the early pod, whatever is happening. Stand at the late pod and finish the early pod's log in its template |
| 5:30 | In a `room-unreachable` slot, press Ctrl+C in that pod's collector window. In slot 3 the pod B card holder acts on their own at 5:30 |
| 5:30-9:00 | Watch the late pod. If the facilitator asks you to restart the room, ask *"Same code or a new one?"* and do what they say |
| 9:00-10:00 | While the late pod scores in silence, finish its log |
| 10:00-15:00 | The late pod's feedback round, with your turn in it. The early pod runs its round without you |
| Slot end | Check that any laptop with an active card is back as it was: `python -c "import jsonschema"` runs without error, or the manifest has forward slashes again. If not, the card holder puts it right now |

**The opening (9 minutes).** The facilitator runs it as they planned. Learners work in this slot's
folder, `lab-slot1` for slot 1 and so on, which has no room joined until the facilitator gives them
the join command.

**The feedback round (5 minutes):**

| Turn | Who | Time | What happens |
|---|---|---|---|
| Score | Everyone except the facilitator | 1:00 | Silent. A score or "not seen" for lab facilitation, with one line of evidence. The other four domains are already marked not seen |
| 1 | Facilitator | 0:45 | What they noticed, at what minute, and what they thought it was |
| 2 | Peer 1 | 0:45 | Lab facilitation, in the stem: the minute the failure showed and the minute the facilitator named it out loud |
| 3 | Peer 2 | 0:45 | Lab facilitation, in the stem: what the other learner was doing while it was handled |
| 4 | You | 2:00 | Your turn, below. In a pod without you, each peer names the minute the pod stopped moving, if it did, and one move that would have kept it moving (1 min each) |
| 5 | Facilitator | 0:45 | Names the one move they will make next time, writes it in box 3.1, and takes the forms |

**Your turn, in this order:**

1. Your score on lab facilitation, with the anchor's words. If yours differs from a peer's by two or
   more, read the anchor wording that decided it for you, once.
2. The two minutes that decided it: when the failure showed, and when the facilitator said out loud
   what it was. Use your minute stamps.
3. One move for next time, in your own words. Do not read out the catalogue entry: the pod reads it
   in Phase 4.

*"Lab facilitation, I scored 3. The anchor for 3 says 'diagnoses a failing environment or
non-deterministic output in front of the room and keeps the cohort moving'. At minute 3 you counted
one device on the page against two laptops and said so, and the other learner was already on step 2
while you sorted it out. The anchor for 4 says 'turns a live failure into a teaching moment on
verification'. The check had passed and only the report was refused, which is this lab's own point
about evidence. One sentence to the pod would have made it a 4."*

**Where to look in nine minutes.** The anchor wording is on the form; this table says what each
anchor looks like in an opening.

| Score | What you see |
|---|---|
| 1 | The opening stops. The facilitator is at one laptop and nobody else has anything to do, or the failure is never found and a learner stays stuck to the end |
| 2 | The learner with the failure is put right, and the other learner waited, with nothing to do, while it happened |
| 3 | The facilitator says out loud what they see and what they think is wrong, and the other learner has work to do throughout |
| 4 | As 3, and the facilitator uses the failure to say something about checking evidence that the learners can use in the lab: what the check showed, and what it could not show |

**While the opening runs:**

- Stay out of the learners' line of sight, and never where the facilitator can watch you watching
  one laptop.
- Do not help, and do not hint. If the facilitator asks you what is wrong, say: *"I'm your technician
  today. I can do things to the room server for you."*
- If a learner asks you anything, send them to the facilitator.

| Broadcast at | Say | Step gate |
|---|---|---|
| ~0:38 | "Nine minutes. Stop the opening now, wherever it is. One minute of silent scoring, and nobody talks. Step 10." | step 9 done |
| ~0:39 | "Pens down. Feedback round in the order on your card, facilitator first. Step 11." | step 10 done |
| ~0:44 | "Slot 2. Forms to the slot 1 facilitator. Learners, open your slot 2 envelope and move to lab-slot2. Position 2, begin. Step 9." | step 11 done |
| ~0:53 | "Nine minutes. Stop now. Silent scoring, step 10." | step 9 done |
| ~0:54 | "Pens down. Feedback round, step 11." | step 10 done |
| ~0:59 | "Slot 3. Forms to the slot 2 facilitator. Open your slot 3 envelope and move to lab-slot3. Position 3, begin. Step 9." | step 11 done |
| ~1:08 | "Nine minutes. Stop now. Silent scoring, step 10." | step 9 done |
| ~1:09 | "Pens down. Feedback round, step 11." | step 10 done |

**With a group of five,** pod A has three and pod B two. In pod B's slots the facilitator has one
learner, who takes both peer turns. In slot 3 pod B's two join pod A as learners with blank cards and
do not score, and you stay in pod A for the whole slot and its feedback round.

**With a group of four,** the one pod runs four slots of eleven minutes and you stay in it. The
opening is 7 minutes, the silent scoring 1, and the feedback round 3 (facilitator 15 s, peer 1 30 s,
peer 2 30 s, you 1 min 15 s, facilitator 30 s). The third learner scores without a turn. In the
`room-unreachable` slot you stop the collector at 4:00. You write each log during the silent minute.
Use 0:29-0:30 to hand the slot 1 envelopes round, and call time at these points instead of the table
above.

| Slot | Opening | Silent scoring | Feedback round |
|---|---|---|---|
| 1 | 0:30-0:37 | 0:37-0:38 | 0:38-0:41 |
| 2 | 0:41-0:48 | 0:48-0:49 | 0:49-0:52 |
| 3 | 0:52-0:59 | 0:59-1:00 | 1:00-1:03 |
| 4 | 1:03-1:10 | 1:10-1:11 | 1:11-1:14 |

> **A facilitator who goes to the failing laptop and stays there** has not finished. Do not step in.
> Note the minute the other learner ran out of work, and use it in your turn.

> **A facilitator who restarts the room with a new code** makes every learner join again. Restart
> it as they ask, and judge the log as partly.

#### GATE-CHECK -- Phase 4, the catalogue (1 min, broadcast)

Open the sealed envelope and hand one catalogue sheet to each participant as you speak.

*"This is the lab's failure catalogue: the four things that can go wrong in its room, how each is
injected, and what a facilitator is expected to do. Every slot today had one of them. Seven minutes,
steps 12 and 13. In your pod, find each slot's failure on the sheet and read its expected handling
against what happened. Then fill in box 4.1 for your own slot. I will come round and read each of
you your log."*

### 1:15-1:22 Phase 4 -- read the catalogue against your pod's slots (pods, then individual)

Participants read in their pods, then write box 4.1 alone.

**Visit every participant, one minute each.** Show them their log on your laptop and read out
`against_expected`, `cohort_kept_moving` and `what_was_done`. If they say something happened that
you did not see, and the peers agree, correct the log now. The log must be final before they leave.

**A log you could not write from your own observation** (you left the early pod before the failure
showed): ask both peers in that pod what happened, in front of the facilitator, and write the log
from their account. Note it in the capture list.

| Broadcast at | Say | Step gate |
|---|---|---|
| ~1:18 | "Fill in box 4.1 for your own slot now. Step 13." | step 12 done |
| ~1:21 | "One minute left. Finish box 4.1." | step 13 closing |

### 1:22-1:26 Share-out: what showed, and when it was named (plenary)

- **1:22** Both pods to the middle. Pod A, then pod B. A minute and a half per pod: for each slot,
  the failure, the minute it showed, and the minute the facilitator said out loud what it was.
- **1:25** Name the move from the catalogue that was missed most often today, and read its line from
  the sheet once.

### 1:26-1:28 Reflection (silent)

Participants write boxes R.1 and R.2 in `LEARNER.md`. You start collecting forms at each end of the
room while they write.

1. Which of the four failures would hurt your own lab most, and what will you check before the
   cohort arrives?
2. What did you say in front of your pod that you would say again?

### 1:28-1:30 Wrap

- **1:28** Collect every form from every facilitator, and every catalogue sheet. Count both before
  anyone leaves: one form from each peer who scored (two per participant in a group of six), and
  one sheet each.
- **1:29** Ask each card holder from today to check their laptop: `python -c "import jsonschema"`
  runs without error. Stop both collectors. They keep nothing on disk.
- **1:29** Say where things go: *"The forms go to the coordinator today and are kept in the private
  store with your session 1 forms. They are feedback, not the record for this session, and only the
  training function sees them. Your record is the failure log I read you. The coordinator checks it
  and records the session. The catalogue stays with me: the next group has not seen it."*
- **1:30** End.

### Recovery moves

| Situation | Move |
|---|---|
| **The laptops cannot reach yours** (the T-15 check says "the room could not be reached") | First, a phone hotspot or travel router that all the laptops join, then repeat the T-15 check. If that is not possible, run each slot's room on one learner laptop: copy `tools/checkpoints/collector.py` and the starter's `checkpoints.json` to it from a stick, start the collector there with `--host 127.0.0.1`, and have that laptop join `http://127.0.0.1:<port>`, not the address the collector prints, which the others cannot reach. The page is read on that laptop, and the other learner works without joining. Put the `stale-room-code` card on that laptop, and for `room-unreachable` give its holder a card that says to press Ctrl+C in the collector window at 5:30. If even that is too much on the day, replace the two room failures with `jsonschema-missing` and, on a Mac or Linux laptop, `backslash-glob`. Two facilitators in a pod may then get the same failure; note it in the capture list |
| **A collector will not start** (address in use) | Use the next free port (8767, 8768) and correct the slips for that pod. |
| **You stopped the wrong pod's collector** | Restart it at once with the same code, tell that pod's facilitator plainly what you did, and ask their learners to re-run their latest step. It is not their failure; do not count it in their log. |
| **An early failure has not shown by 4:30** | The cohort has not run step 1 yet. Leave anyway at 4:30, as planned. Write that log in Phase 4 from both peers' account. |
| **A card holder acts at the wrong moment, or shows the card** | Let the slot run. A failure that showed early is still a failure to handle. If the facilitator saw the card, say so in the log and judge only what they did with the failure. |
| **A card holder does not want their laptop changed** | They hand the card back unopened at the start of the slot, and the other learner-peer gets an active card instead, or you inject `room-unreachable` in its place. |
| **`jsonschema` is still missing at slot end** | The card holder runs `python -m pip install jsonschema`, or `python -m pip install --no-index --find-links <stick>/wheels jsonschema`, during the feedback round. The next slot's step 1 fails without it. |
| **A facilitator overruns nine minutes** | The timekeeper stops them at nine. An unhandled failure is evidence for the log. Never extend a slot; the next slot's start is fixed. |
| **You are 3+ minutes late at 0:29** | Take the time from the share-out (down to two minutes), then from the reflection. Do not shorten Phase 2 or any slot. |
| **A participant's laptop cannot run the lab** | See the T-7 note: they share a neighbour's laptop as a learner, and open the lab with only a browser. No active card goes to them. |
| **A participant is absent on the day** | Rebuild the pods from the group-size tables before 0:20, and move the envelopes to match. Do not run a pod of one. |
| **A participant has not done session 1** | They cannot take this session: there is no pod or feedback routine for them. They join the next session 1 and take session 3 afterwards. |
| **Someone asks whether the scores count** | No. They are formative, they are not observations, they never count toward clearance, and only the training function sees them (decision 0005). |

---

## AFTER

### Close protocol

- [ ] Count the forms again away from the room. Each should have an Instructor id, an Observer id
      and lab facilitation scored or marked not seen.
- [ ] Hand the forms to the coordinator the same day in a closed folder. They hold scores against
      instructor ids: do not photograph them and do not leave them in the room. The coordinator
      files them in the private store with the participant's session 1 and 2 forms. They are not the
      evidence for this session.
- [ ] Give the coordinator the failure log files the same day, by the route the coordinator uses
      for private-store material. Delete your copies once the coordinator confirms they have them.
      Each file is named by instructor id and holds no names.
- [ ] The coordinator checks each file:
      `teachermodel check-failure-log <file> --catalogue <proving-ground>/scenarios/aggregates-only-export/staff/catalogue.yaml`.
      It prints each problem and then "ok" or "N problem(s)", and exits 0 only when the file is well
      formed. If it lists problems, the coordinator sends the list back to you, and you correct the
      file from your notes.
- [ ] Once the check prints "ok", the coordinator stores the file in the private store under one key
      and records the session, with the date of the session:
      `teachermodel course record --instructor tm:instructor/<id> --session lab-facilitation --evidence-ref <key> --on <YYYY-MM-DD>`
- [ ] The coordinator checks it with `teachermodel course status --instructor tm:instructor/<id>`:
      session 3 now shows a date instead of "missing".
- [ ] Put the catalogue sheets with your copy of this run sheet. Keep the paper until the head of
      training says what happens to it: `standards/retention.yaml` has no entry for training
      evidence yet.

### If a participant missed the session

They join the next group's session 3. There is no solo route: the session needs learners in the
room and a failure to handle in front of them, and the course record takes a session only once it
has happened.

### What participants take forward

- **Session 4** has them teach remotely and read the room from checkpoint progress rather than
  faces. It uses the same room page.
- **Session 5** scores reference recordings on all five domains, lab facilitation among them.
- **Their own labs.** Box R.1 is a check to run before their first real cohort arrives.

### Capture for next run

Counts only, never names.

- [ ] Whether the slots ran to time, and how often the early failure had shown by 4:30
- [ ] Per failure: how many times it was injected, and how many logs said met, partly and missed
- [ ] How many logs were written from the peers' account rather than your own observation
- [ ] Whether the network let the laptops reach yours, and which fallback you used if not
- [ ] Whether `backslash-glob` could be used, and how many laptops ran macOS or Linux
- [ ] How many logs passed `teachermodel check-failure-log` first time, and the commonest problem
- [ ] How often a peer's score and yours differed by two or more
- [ ] Update the session log
