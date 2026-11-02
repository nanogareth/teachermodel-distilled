# Train-the-trainer session 2: Diagnosing prior knowledge -- Run Sheet

> The only document you need on the day. Participant-facing content lives in `LEARNER.md`; the step
> numbers below refer to its step list. Course design: `docs/train-the-trainer/DESIGN.md`, row 2.

| Field | Value |
|-------|-------|
| **Envelope** | 90 min, one continuous block. Four phases on one clock, no break |
| **Mode** | In person. One trainer and one group of 4 to 6, in the same two pods as session 1, at opposite ends of one room |
| **Roles** | You run one full cycle on the whole room in Phase 1. In Phase 3, per slot: one teacher, two or more peers who vote and then score, and you in one of the two pods. Peer 2 keeps time |
| **Tools** | No software. The printed form from `teachermodel paper` (decision 0022), voting cards, a printed question card per participant, a timer and a flipchart per pod |
| **Slices** | Each participant's session 1 slice, and the `misconceptions` list of the unit it comes from |
| **Evidence** | Each participant's question set, a YAML file in the unit's `pre_check` shape, checked with `teachermodel check-questions` and recorded by the coordinator. The forms are feedback only: formative, not observations, never counted toward clearance |
| **Recording** | None. Nothing is filmed |
| **Hardware / cost** | The session 1 room, two timers, a set of five voting cards (A to E) per person including you, about 20 printed forms and 8 printed question cards for a group of six |

**Both pods run on one clock,** as in session 1. One call from you moves both pods to the next turn.
You watch one pod per slot and visit the participants you did not see during the revision phase.

**Every participant leaves with one question.** It tests one idea from their session 1 slice. Each
wrong option is the answer a person holding a named misconception would choose, and it comes with
two routes: what the participant does in the real session when the vote comes back mostly right,
and what they do when it comes back mostly wrong. They write it, run it once on their pod with a
vote, discussion, revote and debrief, revise it from what the votes showed, and send it to the
coordinator as a file.

---

## BEFORE

### What you need in your head

- **Why find out first.** Expertise reversal (Kalyuga et al. 2003) is the finding that support
  which helps a novice, such as a worked example, slows down a learner who already knows the topic.
  So one pace for the whole room is the wrong pace for part of it, and a pre-check is how the
  instructor finds out which part. The spec rates this evidence strong.
- **Why the discussion.** In peer instruction the learners vote, argue with a neighbour who voted
  differently, and vote again. The learning happens in the argument (Porter et al. 2011), and in
  four university computing courses fail rates halved (Porter, Bailey Lee & Simon 2013). That
  evidence comes from university computing courses, not from engineers teaching engineers, so the
  course adopts the method and promises no effect size. Do not quote one to the room.
- **The thresholds are a rule of thumb.** Crouch and Mazur (2001) suggest that discussion is worth
  the time when roughly 30 to 70 per cent of the room answers correctly on the first vote. Above
  that, explain briefly and move on; below it, reteach first and ask again. It is practitioners'
  advice, so say "rule of thumb", never "the evidence shows". With two to four voters in a pod it is
  coarse: two out of two right is mostly right, one out of two is the middle, none is mostly wrong.
- **A wrong option is only diagnostic if it was written from a misconception.** A wrong option
  made up to fill a gap tells you that someone did not know the answer. One that a person holding
  `model-retries-itself` would pick tells you which wrong idea is in the room and what to teach
  next. Phase 2 is spent making every wrong option the second kind.
- **Score two domains and nothing else.** The forms come pre-marked "not seen" on technical
  depth, lab facilitation and remote delivery. Prior knowledge and conceptual questioning are both
  visible in a seven-minute cycle, so scores of 3 and 4 are possible here, unlike session 1. Score
  what happened: a debrief that skips one wrong option is a 3 on conceptual questioning, not a 4.
- **You may not know the subject.** You cannot judge whether an option is technically correct, and
  you do not need to. Judge whether each wrong option says what its misconception statement says,
  and whether the correct answer can be spotted from its wording. If a peer argues in the
  discussion that the "correct" option is wrong, that is evidence for the teacher to take away;
  do not settle the technical point yourself.
- **The same scores, the same rules.** The forms are formative, they are not observations, they
  never count toward clearance, and only the training function sees them (decision 0005). The
  feedback routine is the session 1 routine: silent scores first, then the teacher, then the peers,
  then you, then the teacher again.

### T-7 -- send to learners

- [ ] `LEARNER.md` (as DOCX or PDF)
- [ ] **Check every participant's unit for a misconceptions list.** For each unit id they gave you
      for session 1, open `standards/units/<unit id>.yaml` and look for a `misconceptions` list with
      at least one entry. The question-set checker rejects a file whose unit is not in
      `standards/units/`, and it rejects a file in which no wrong option uses an id from the unit's
      list. If a unit fails either test, use the fallback below and tell the participant in the same
      message.
- [ ] To each participant, alone: their unit's misconceptions list (ids and statements), copied from
      the unit file, and a request to reply by T-3 with the misconception id they plan to build their
      question around, or "none of these fits my slice"
- [ ] A reminder to bring their session 1 slice plan and their reteach plan (box 2.1)

**Fallback when a unit has no misconceptions list.** First choice: ask the unit owner to add the
misconceptions the participant's slice deals with before T-3, so the question serves the slice they
will teach. If that cannot happen in time, the participant writes their question for the example
unit, `sl:unit/example-agent-loop@1`, using its list, and runs that on their pod. Say which it is in
your T-7 message, so nobody finds out in Phase 2.

**A reply of "none of these fits".** The participant may write one or two wrong options as
proposed misconceptions (a statement, not an id), but the checker needs at least one wrong option
that uses an id from the unit's list. Ask them to find the nearest id now, or use the fallback.

### T-1 -- prepare

- [ ] **Print the forms.** For each participant, run `teachermodel paper --unit <unit uri>` and print
      the `rubric.html` it writes three times (four for a group of four, where three peers score).
      Use the unit of the question they will run, which is the example unit for anyone on the
      fallback.
- [ ] **Fill in the headers.** On every form: Date; Instructor id is the teacher's id; Delivery
      reference is "TTT-2 diagnostic cycle"; Length is "diagnostic cycle 7 min"; Mode is in person;
      Instructor led is yes; From a recording is no. Write "FORMATIVE: diagnostic cycle, not an
      observation" across the top. In the evidence notes for technical depth, lab facilitation and
      remote and inclusive delivery, write "not seen; session 2 scores two domains". Leave Observer
      id blank.
- [ ] **Print the voting cards.** One set per person, you included, plus one spare set: five A5
      cards, each with one letter (A, B, C, D, E) printed large on one side, and each letter a
      different colour so that you can count a pod at a glance. Print them on card so that they do not flop.
- [ ] **Print the question cards.** One A3 sheet per participant plus two spares, laid out as below.
      There is no space for misconception ids: the voters must never see them.

```text
QUESTION
______________________________________________________________
______________________________________________________________

A  ___________________________________________________________
B  ___________________________________________________________
C  ___________________________________________________________
D  ___________________________________________________________
E  ___________________________________________________________
```

- [ ] **Write your own Phase 1 question** on a flipchart sheet (the question and options under
      Phase 1 below), and the three misconception statements on a second sheet. Fold the second
      sheet over or turn it to the wall: it stays covered until 0:13.
- [ ] **Keep the session 1 pods and positions,** and write them on the pod cards again. If the group
      has changed since session 1, rebuild the pods from the table below, with people from different
      specialisms together.
- [ ] **Make the peer-check pairs across pods,** from the table below. A partner who checks a
      question knows its answer, so they must not vote on it in Phase 3.
- [ ] **Bring spares:** one printout of each participant's unit misconceptions list, in case
      someone arrives without theirs.
- [ ] **Book the room.** As session 1: one room with a flipchart at each end, or two adjacent rooms
      with a timer each.

| Group | Pods | Phase 3 slots | Your pod per slot | Peer-check pairs |
|---|---|---|---|---|
| 6 | A 3, B 3 | Three slots of 12 min, both pods teaching | A, B, A | A1 with B1, A2 with B2, A3 with B3 |
| 5 | A 3, B 2 | Three slots of 12 min. In slots 1 and 2 the pod B teacher has one peer, so you join pod B as a second voter and then score. In slot 3 pod B's two join pod A as voters; they do not score | B, B, A | A1 with B1, A2 with B2, A3 with you |
| 4 | One pod of four | Four slots of 9 min, in one pod (table in Phase 3) | The pod, throughout | A1 with A2, A3 with A4. The partner who checked a question does not vote on it, and scores it without a turn |

Every teacher needs at least two voters, so that the pair discussion has a pair. That is why the
group of five puts you in pod B as a voter, and the group of four runs as a single pod. When you
vote, vote as a learner new to the topic, and score afterwards as usual.

### T-15min -- room

- [ ] Each end of the room has its pod card, a timer, a flipchart with pens, and that pod's forms
      in slot order.
- [ ] A set of voting cards and a blank question card on every seat, and marker pens.
- [ ] Your two Phase 1 flipchart sheets at the front, the misconceptions sheet covered.
- [ ] `LEARNER.md` open at the step list. Your time calls refer to step numbers.

---

## DURING

### Demo list

Declared per the cadence rule. A phase gets a 5-minute demo when it introduces a software tool no
earlier phase used (**4a**) or needs a non-obvious feature interaction (**4b**). This session uses
no software, so every phase gets a 60-second gate-check. Phase 1 is itself a modelled cycle, run by
you on the room.

| Phase | Tool | Demo | Trigger |
|---|---|---|---|
| 1 | Voting cards -- no tool | gate-check | n/a; no software. You run one full cycle on the room with a question about teaching |
| 2 | Paper -- no tool | gate-check | n/a; individual writing in `LEARNER.md` and on the question card, then a peer check |
| 3 | Voting cards -- no tool | gate-check | n/a; each participant runs the Phase 1 cycle on their pod |
| 4 | Paper -- no tool | gate-check | n/a; individual revision in `LEARNER.md` |

### The clock

Four gate-checks at 1 minute, 71 minutes of modelling, writing, running and revising in four
phases, and 15 minutes of welcome, share-out, reflection and wrap. That is 90 exactly. If you are
running late, take the minutes from the share-out and then from the reflection. Never shorten a
Phase 3 slot: a cycle that loses its debrief is not the cycle the participant is practising.

| From | To | Min | Segment | Kind |
|---|---|---|---|---|
| 0:00 | 0:05 | 5 | Welcome, and why find out first | framing |
| 0:05 | 0:06 | 1 | GATE-CHECK -- Phase 1, the modelled cycle | gate-check |
| 0:06 | 0:18 | 12 | Phase 1 work -- one full cycle on the room, then taken apart | work |
| 0:18 | 0:19 | 1 | GATE-CHECK -- Phase 2, write and check | gate-check |
| 0:19 | 0:34 | 15 | Phase 2 work -- write the question and routes, peer check, question card | work |
| 0:34 | 0:35 | 1 | GATE-CHECK -- Phase 3, run rounds | gate-check |
| 0:35 | 1:11 | 36 | Phase 3 work -- run the cycle and feedback in three slots | work |
| 1:11 | 1:12 | 1 | GATE-CHECK -- Phase 4, revise | gate-check |
| 1:12 | 1:20 | 8 | Phase 4 work -- revise from the votes and write the final question | work |
| 1:20 | 1:25 | 5 | Share-out: what the votes showed | share-out |
| 1:25 | 1:28 | 3 | Reflection | reflection |
| 1:28 | 1:30 | 2 | Wrap and form collection | wrap |

**The phases are the participants' work.** In Phase 1 they are your learners; in Phase 2 they
write; in Phase 3 they teach, vote and score; in Phase 4 they revise.

### 0:00-0:05 Welcome, and why find out first (plenary)

- **0:00** Everyone in the middle of the room, seated, with their voting cards.
- **0:01** Frame the session: *"Today you leave with one question for the slice you taught in
  session 1. It is a question whose wrong answers tell you what the room believes, and you will run
  it on your pod with a vote, a discussion and a second vote. You also leave with two plans: what
  you do when most of the room gets it right, and what you do when most get it wrong."*
- **0:02** Why find out first: *"A worked example helps someone who is new to a topic. The same
  worked example slows down someone who already knows it, and that finding has held up in a lot of
  studies. So if you teach one way to the whole room, you are teaching the wrong way to part of it.
  A question at the start tells you which part."*
- **0:03** Why the discussion: *"In the method we use today, people vote, argue with someone who
  voted differently, and vote again. The people who studied it found that the learning happens in
  the argument. Their evidence comes from university computing courses, so we use the method and
  promise no numbers."*
- **0:04** *"The scores work as they did in session 1. They are practice, they are not
  observations, they never count toward clearance, and only the training function sees them. This
  time they cover two domains, prior knowledge and conceptual questioning, and the rest are marked
  not seen."*

> Watch for a participant who arrives without their unit's misconceptions list. Give them your
> spare printout now. If their unit has no list and the T-7 fallback was missed, see Recovery moves.

#### GATE-CHECK -- Phase 1, the modelled cycle (1 min, broadcast)

*"For the next twelve minutes you are my learners. I will ask you one question about teaching. You
choose a card on your own and keep it face down, and when I count to three everyone holds their
card flat against their chest, letter facing me, at the same moment. Then you find someone who
chose a different letter and try to convince them, and we vote again. After that we take the
question apart. Cards ready."*

### 0:06-0:18 Phase 1 -- one full cycle on the room, then taken apart (plenary)

This is the cycle participants run in Phase 3, at the same timings: vote 1 min, discussion 2 min,
revote 30 s, debrief 2 min 30 s, route call 1 min. Then five minutes to take it apart.

**The question** (on your first flipchart sheet; the letters stay in this order):

> A learner picks one of the wrong options on a pre-check question. What does their choice tell you?
>
> A. Only that they do not know the answer yet
> B. Which wrong idea about the topic they most likely hold
> C. That the question was pitched too hard for the group
> D. Nothing, because learners mostly guess on these

**The misconceptions behind it** (on the covered sheet):

| Option | Misconception id | Statement |
|---|---|---|
| A | `wrong-means-not-known` | Every wrong answer means the same thing: the learner does not know the answer |
| B | correct | |
| C | `wrong-means-hard-question` | When learners choose a wrong answer, the fault is in how hard the question is, not in what they believe |
| D | `votes-are-guesses` | Learners mostly guess on multiple-choice questions, so their votes tell you nothing |

- **0:06** Uncover the question. Read it and the four options aloud once. *"Thirty seconds on your
  own. Choose a card and keep it face down."*
- **0:06:30** *"Cards up on three. One, two, three."* Count each letter aloud and write the counts on
  the flipchart under "Vote 1". Do not say which is right, and keep your face still: a nod at B
  ends the discussion before it starts.
- **0:07** *"Find someone who chose a different letter and try to convince them. If everyone near
  you chose the same letter, take the wrong option you find most tempting and explain to each other
  why someone would choose it. Two minutes."* Walk between the pairs. Note one sentence you hear for
  a wrong option, to quote in the debrief.
- **0:09** *"Vote again, on three. One, two, three."* Count, and write the counts under "Vote 2".
- **0:09:30** Debrief. Say the answer, then take each wrong option by the idea behind it:
  - *"The answer is B, and I will come back to why. If you chose A, you were treating every wrong
    answer as the same thing, not knowing. That is true when the wrong options were made up to fill
    space. When each wrong option is what someone holding one particular wrong idea would choose,
    the letter they hold up tells you which idea it is."*
  - *"If you chose C: a question can be pitched too hard, and if almost nobody gets it right you
    reteach before you ask again. But a single wrong choice is about what that learner believes. It
    tells you nothing about the question until you see the whole room's votes."*
  - *"If you chose D: one vote on its own can be a guess. That is why you look at the whole room,
    and why the discussion matters. Someone arguing for their answer to a neighbour is not guessing,
    and you can hear what they believe."* Quote the sentence you noted, without saying who said it.
  - *"B is right, with one condition: the wrong options have to be written from real misconceptions.
    Writing them that way is most of the next hour."*
- **0:12** Route call, out loud, from your Vote 1 counts. For example: *"On the first vote, four of
  six chose B. That is between about a third and two thirds, which is where a discussion is worth
  the time, so in a real session I would do what we just did. If five or six had chosen B, I would
  have explained B in a minute and moved on. If one or none had, I would have taught this first and
  asked a new question afterwards."*
- **0:13** Uncover the misconceptions sheet with the option column folded back. *"In your pairs:
  which option would someone holding each of these choose? One minute."*
- **0:14** Unfold the option column and confirm. Then run the four-point checklist from step 9 in
  `LEARNER.md` against your own question, out loud: it tests one idea; each wrong option is what a
  holder of its misconception would choose; B is not the longest and repeats no words from the
  question; the four options are within a couple of words of each other in length.
- **0:16** Point to the worked example in `LEARNER.md`, "Your question set file". *"Your question
  goes into a file like this. Every wrong option names a misconception id from your unit's list, or
  states a new one, and at least one must come from the list."*
- **0:17** The routes: *"The rule of thumb I used in the route call comes from people who ran this
  method for years. It is advice, not a result: roughly between thirty and seventy per cent right
  on the first vote, discuss and revote. Above that, explain briefly and move on. Below it, reteach
  first. Your file holds the two ends: what you do when most get it right, and what you do when most
  get it wrong."*

| Broadcast at | Say | Step gate |
|---|---|---|
| ~0:07 | "Find someone who chose a different letter and convince them. That is step 2." | step 1 done |
| ~0:09 | "Vote again, on three. Then listen to the debrief: step 3." | step 2 done |
| ~0:12 | "Here is the route call: step 4." | step 3 done |
| ~0:13 | "In pairs, match the misconceptions to the options. Step 5." | step 4 done |

> **If the room is unanimous on the first vote,** say what the route would be in a real session,
> then run the discussion anyway: *"In a real room I would stop here. You need to see the whole
> cycle today, so tell your partner why each wrong option is wrong."*

#### GATE-CHECK -- Phase 2, write and check (1 min, broadcast)

*"Now you write your own, alone, for the slice you taught in session 1. Steps 6 to 10. Pick one
idea from the slice and the misconception from your unit's list that goes with it. Write the
question and the options in box 2.1, with the misconception id next to each wrong option, and then
the two routes. At 0:29 you swap with your partner from the other pod and check each other's
against the checklist. In the last two minutes you copy the question and options onto your A3
card, without the ids. Your partner will not vote on your question, so they can know the answer."*

### 0:19-0:34 Phase 2 -- write the question and routes, peer check, question card (individual, then pairs)

Participants write in `LEARNER.md` box 2.1, then copy onto their A3 question card. Call the pairs
from your list at 0:29.

**While they write, walk the room.** In each draft, look for these four things in order:

1. **A recall question.** "What is the default timeout?" has one wrong answer: not knowing. Ask:
   *"What do people get wrong about this, not what do they forget?"*
2. **A wrong option with no misconception behind it.** Ask: *"Who would choose this, and what
   would they have to believe?"* If they cannot say, the option goes.
3. **A giveaway.** The correct option is the longest, the only one with a qualifier ("usually",
   "in most cases"), or the only one that repeats the question's words.
4. **Routes that say the same thing twice.** The two routes must lead to different next minutes.
   "Explain it again" is not a route for the mostly-wrong case unless it says how the explanation
   changes.

| Broadcast at | Say | Step gate |
|---|---|---|
| ~0:21 | "Two minutes in. You should have one idea and one misconception id. Now write the question and the options. Step 7." | step 6 done |
| ~0:27 | "Write your two routes: what you do when most get it right, and when most get it wrong. Step 8." | step 7 done |
| ~0:29 | "Swap with your partner from the other pod. Ninety seconds each, against the checklist in step 9." | step 8 done |
| ~0:32 | "Copy the question and options onto your A3 card, in large letters, without the ids. Step 10." | step 9 done |

#### GATE-CHECK -- Phase 3, run rounds (1 min, broadcast)

Everyone moves to their pod. Say this to the whole room as they go.

*"Three slots of twelve minutes, steps 11 to 13, in your session 1 positions. The teacher runs the
cycle you saw me run: one minute to read the question and vote, two minutes of discussion, a
revote, a debrief that takes each wrong option in turn, and a route call. The timekeeper calls the
revote at three minutes, the route call at six, and stops the cycle at seven. Peers, vote as
yourselves: do not play a misconception, and do not vote for the answer you think the teacher
wants. Then one minute of silent scoring on two domains, and the feedback round on your card.
Position 1, card up."*

### 0:35-1:11 Phase 3 -- run the cycle and feedback (two pods, three slots)

| Slot | Cycle | Silent scoring | Feedback round | You are in pod (group of 6) |
|---|---|---|---|---|
| 1 | 0:35-0:42 | 0:42-0:43 | 0:43-0:47 | A |
| 2 | 0:47-0:54 | 0:54-0:55 | 0:55-0:59 | B |
| 3 | 0:59-1:06 | 1:06-1:07 | 1:07-1:11 | A |

In each slot, **peer 1** is the person who teaches next (in slot 3, position 1) and **peer 2** is the
remaining person, who keeps time, as in session 1. For a group of five, your pods are B, B, A.

**The cycle inside each slot (7 minutes):**

| Part | Time | What the teacher does |
|---|---|---|
| Vote | 1:00 | Reads the question and options aloud, 30 s of silent thinking, cards up on three. Writes the counts on the pod flipchart without saying which is right |
| Discussion | 2:00 | Voters convince each other. The teacher listens and notes what they hear |
| Revote | 0:30 | Cards up on three, at the timekeeper's call. Counts written under the first |
| Debrief | 2:30 | The answer, then each wrong option by the misconception behind it, then why the right one is right |
| Route call | 1:00 | What the first vote showed, which band it falls in, and what they would do next in the real session |

**The feedback round (5 minutes):**

| Turn | Who | Time | What happens |
|---|---|---|---|
| Score | Everyone except the teacher | 1:00 | Silent. A score or "not seen" for prior knowledge and conceptual questioning, with one line of evidence for each score. The other three domains are already marked not seen |
| 1 | Teacher | 0:30 | What the first vote showed against what they expected, and which option surprised them |
| 2 | Peer 1 | 0:45 | Prior knowledge, in the stem |
| 3 | Peer 2 | 0:45 | Conceptual questioning, in the stem |
| 4 | You | 1:30 | Your turn, below. In a pod without you, each peer names the option that told them least about what the voters believed, and one change to it (45 s each) |
| 5 | Teacher | 0:30 | Names the one revision they will make in Phase 4, writes it in box 3.1, and takes the forms |

In a pod where the teacher has one peer (group of five, pod B, slots 1 and 2), that peer takes
both peer turns and you take turn 4 as usual.

**Your turn, in this order:**

1. If the discussion showed that an option is worded so that two answers can be defended, say so and
   name the option. Fifteen seconds. Do not decide the technical point.
2. Give your score on each of the two domains. If yours differs from a peer's by two or more, read
   the anchor wording that decided it for you, once.
3. Name one revision to the question: the option that did least diagnostic work, why (nobody would
   choose it, it was chosen for its wording rather than for the idea behind it, or it gave the
   answer away), and what to change.

*"Conceptual questioning, I scored 3. The anchor for 4 says 'runs vote, peer discussion and revote,
then a debrief that addresses each wrong answer'. You ran all of that, but in the debrief you
explained C and went straight to why B was right, so D, which one person chose, was never
addressed. For the revision: in the discussion both voters said C was obviously wrong because it
says 'always'. Take the 'always' out, and C will tell you something."*

**Where to look in seven minutes.** The anchors are on the form; this table says where the evidence
for them shows up in the cycle.

| Domain | Look at |
|---|---|
| Prior knowledge | The route call. Did the teacher say what the first vote showed, and does the route they named follow from it? A route call that ignores the counts is a 2: the pre-check ran and nothing was done with it. A 3 names the result and the route that fits it. A 4 needs a re-check and different tasks by result: in one cycle, a route call that uses the revote and sends the learners who still chose a wrong option somewhere different from the rest |
| Conceptual questioning | The question and the debrief. A recall question is a 1. Explaining the answer straight after the first vote, without discussion, is a 2. Wrong options tied to misconceptions, with a route that changes on the result, is a 3. The full cycle with every wrong option addressed in the debrief is a 4 |
| Technical depth, lab facilitation, remote and inclusive | Not seen in this session. Already marked on the form |

**While the cycle runs:**

- Stay out of the voters' line of sight, and never where you can see a card before the count.
- Write minute stamps: "min 1: counts A0 B1 C1", "min 4: debrief skips D".
- Do not vote, unless the group-of-five table puts you in pod B as a voter. A vote from you changes
  the result the teacher is reading.

| Broadcast at | Say | Step gate |
|---|---|---|
| ~0:42 | "Seven minutes. Stop the cycle now, wherever it is. One minute of silent scoring, and nobody talks. Step 12." | step 11 done |
| ~0:43 | "Pens down. Feedback round in the order on your card, teacher first. Step 13." | step 12 done |
| ~0:47 | "Slot 2. Forms to the slot 1 teacher. Position 2, card up, start your vote. Step 11." | step 13 done |
| ~0:54 | "Seven minutes. Stop now. Silent scoring, step 12." | step 11 done |
| ~0:59 | "Slot 3. Forms to the slot 2 teacher. Position 3, card up. Step 11." | step 13 done |
| ~1:06 | "Seven minutes. Stop now. Silent scoring, step 12." | step 11 done |

**With a group of four,** the one pod runs four slots of nine minutes and you stay in it. The cycle is
5 min 30 s (vote 45 s, discussion 1 min 30 s, revote 15 s, debrief 2 min 15 s, route call 45 s), the
silent scoring 30 s, and the feedback round 3 min (teacher 15 s, peer 1 30 s, peer 2 30 s, you
1 min 15 s, teacher 30 s). Peers 1 and 2 are the two voters; the partner who checked the question
scores without a turn. Call time at these points instead of the table above.

| Slot | Cycle | Silent scoring | Feedback round |
|---|---|---|---|
| 1 | 0:35-0:40:30 | 0:40:30-0:41 | 0:41-0:44 |
| 2 | 0:44-0:49:30 | 0:49:30-0:50 | 0:50-0:53 |
| 3 | 0:53-0:58:30 | 0:58:30-0:59 | 0:59-1:02 |
| 4 | 1:02-1:07:30 | 1:07:30-1:08 | 1:08-1:11 |

> **A teacher who explains the answer straight after the first vote** has skipped the part the
> session is about. Do not stop them. Score it, and in your turn read the anchor for 2 and the anchor
> for 4.

> **A voter who says "I'd have got that if I knew the topic"** is telling the teacher something
> about the question. Ask them in the discussion which word gave them the most trouble.

#### GATE-CHECK -- Phase 4, revise (1 min, broadcast)

*"Eight minutes, alone, steps 14 to 16. Read your counts and your forms, and make the one revision
you named. A wrong option nobody chose stays, unless your peers said its wording gave it away: two
or three votes cannot show that an option is useless. Then copy the final version into box 4.1,
in the order the file needs. I will come round to some of you."*

### 1:12-1:20 Phase 4 -- revise from the votes and write the final question (individual)

Participants revise in `LEARNER.md` box 3.1, then write the final question into box 4.1.

**Visit the participants you did not score in Phase 3.** With six, that is pod A position 2 and pod
B positions 1 and 3. With five, it is pod A positions 1 and 2. With four you saw everyone, so visit
whoever had the flattest votes. Two minutes each, three questions:

1. "What did the first vote and the revote show?"
2. "Which option did least work, and what are you changing in it?"
3. "Read me your two routes. What happens in the first minute of each?"

If a route is a feeling ("go slower"), ask for the next thing they will put in front of the room.
If every wrong option is a proposed misconception, point them to the rule that one must come from
the unit's list.

| Broadcast at | Say | Step gate |
|---|---|---|
| ~1:14 | "Two minutes in. You should know your one revision. Make it now. Step 15." | step 14 done |
| ~1:17 | "Three minutes left. Copy the final version into box 4.1, every field. Step 16." | step 15 done |

### 1:20-1:25 Share-out: what the votes showed (plenary)

- **1:20** Both pods to the middle. Pod A in position order, then pod B. Forty seconds each: the
  misconception their question targets, the first vote and revote counts, and the one revision.
- **1:24** Ask for a show of hands: whose first vote came back mostly right? Say that a question
  everyone gets right on the first vote is a result, and the route for it is to explain briefly and
  move on. It is not a failed question, unless the wording gave the answer away.

### 1:25-1:28 Reflection (silent)

Participants write boxes R.1 and R.2 in `LEARNER.md`. You start counting forms at each end of the
room while they write.

1. Where in your real session does this question go, and what will you do in the minute after the
   first vote if the room splits?
2. Which part of the cycle was hardest to run as the teacher, and what will you do differently?

### 1:28-1:30 Wrap

- **1:28** Collect every form from every teacher. Count them against the pod stacks before anyone
  leaves: up to three per participant, four in a group of four.
- **1:29** Say where things go: *"The forms go to the coordinator today, to be kept in the private
  store with your session 1 forms. They are feedback, not the record for this session, and only the
  training function sees them. Your record is the question set file. Type box 4.1 into the file shape
  in your pack and send it to the coordinator within two working days. The coordinator checks it,
  and if anything in it breaks the rules, you get back a list of what to fix."*
- **1:30** End.

### Recovery moves

| Situation | Move |
|---|---|
| **A participant's unit has no misconceptions list, discovered on the day** | They write for their own slice, with proposed misconceptions, and run it in Phase 3. The file cannot pass the check without one id from the unit's list, so after the session either the unit owner adds the list and the participant swaps one proposal for its id, or the participant writes a second question for `sl:unit/example-agent-loop@1`. Note which in the capture list. |
| **The room is unanimous on your Phase 1 vote** | Say what the real route would be, then run the discussion anyway, with each pair explaining why someone would choose each wrong option. |
| **Nobody in a pod voted differently** | The voters each take a different wrong option and explain why someone would choose it. The timekeeper still calls the revote at three minutes. |
| **A teacher's cycle overruns** | The timekeeper stops it at seven minutes. A debrief cut short is evidence on the form. Never extend a slot; the next slot's start is fixed. |
| **You are 3+ minutes late at 0:35** | Take the time from the share-out (down to two minutes), then from the reflection. Do not shorten Phase 2's peer check or any slot. |
| **Voters peek, or show cards one after another** | Restart the vote: *"Cards down. On three, all together."* Ten seconds lost is cheaper than a vote that copied itself. |
| **A peer argues that the "correct" option is wrong** | Let the discussion run; it is evidence. The teacher takes it into Phase 4. You do not settle the technical point. |
| **A question tests recall** | Score it as it is (1 on conceptual questioning) and use your turn on what people get wrong about the topic. Phase 4 is where it changes. |
| **A partner from the peer check ends up in the same pod as the question** | They do not vote on it. They score it, and take no turn. |
| **A participant has not done session 1** | They cannot take this session: there is no slice and no pod for them. They join the next session 1 and take session 2 afterwards. |
| **Someone asks whether the scores count** | No. They are formative, they are not observations, they never count toward clearance, and only the training function sees them (decision 0005). |

---

## AFTER

### Close protocol

- [ ] Count the forms again away from the room. Each should have an Instructor id, an Observer id
      and two domains scored or marked not seen.
- [ ] Hand the forms to the coordinator the same day in a closed folder. They hold scores against
      instructor ids: do not photograph them and do not leave them in the room. The coordinator
      files them in the private store with the participant's session 1 forms. They are not the
      evidence for this session.
- [ ] Each participant sends their question set file to the coordinator within two working days.
      The file holds no names: no participant's, no peer's and no learner's.
- [ ] The coordinator checks each file with `teachermodel check-questions <file>`. It prints each
      problem and then "ok" or "N problem(s)", and exits 0 only when the file is well formed. If it
      lists problems, the coordinator sends the list back to the participant, and the participant
      sends a corrected file.
- [ ] Once the check prints "ok", the coordinator stores the file in the private store under one key
      and records the session, with the date of the session, not the date the file arrived:
      `teachermodel course record --instructor tm:instructor/<id> --session prior-knowledge --evidence-ref <key> --on <YYYY-MM-DD>`
- [ ] The coordinator checks it with `teachermodel course status --instructor tm:instructor/<id>`:
      session 2 now shows a date instead of "missing".
- [ ] The coordinator sends every `proposed_misconception` statement, without the file it came from,
      to the owner of that unit, who decides whether to add it to the unit's list.

### If a participant missed the session

They join the next group's session 2. There is no solo route: the session needs voters for the
cycle, and the course record takes a session only once it has happened.

### What participants take forward

- **Session 4** has them teach the session 1 slice remotely. Their question goes into it, and remote
  learners vote on it too.
- **Session 5** scores reference recordings on all five domains. The two anchors they were scored on
  today are two of them.
- **The real session.** The question, its options and its routes are in the unit's `pre_check`
  shape, so the unit owner can adopt it.

### Capture for next run

Counts only, never names.

- [ ] Whether the slots ran to time, and which part of the cycle overran
- [ ] How many first votes in Phase 3 came back mostly right, in the middle, and mostly wrong
- [ ] What the room's first vote on your Phase 1 question was, by letter
- [ ] How many units had no misconceptions list at T-7, and how many participants used the fallback
- [ ] How many files passed `teachermodel check-questions` first time, and the commonest problem
- [ ] How many proposed misconceptions were written, and how many unit owners added one
- [ ] How often a peer's score and yours differed by two or more, and on which domain
- [ ] Update the session log
