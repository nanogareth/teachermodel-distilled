# Train-the-trainer session 2: Diagnosing prior knowledge -- Participant Pack

> **Your name**: ____________________  **Date**: ____________________  **Pod and position**: ________
>
> Everything you need for session 2, in the order you need it: what to do **before**, how the
> session **runs**, the steps you work through **during** it, and what happens **after**.
>
> **Format**: one continuous 90-minute block, in person, in the same two pods as session 1. One
> trainer moves between them.
>
> **What you do**: write one diagnostic question for the slice you taught in session 1, run it on
> your pod with a vote, a discussion, a second vote and a debrief, and revise it from what the votes
> showed.
>
> **No software.** You vote with printed cards and write on paper. After the session you type your
> question into a short file and send it to the coordinator.

<!-- pack:brief -->

## Before the session

### At a glance

| Field | Value |
|-------|-------|
| **Course** | Train-the-trainer, session 2 of 5 |
| **Duration** | One 90-minute block, and about ten minutes afterwards to type your question set file |
| **Group** | Four to six participants and one trainer, in your session 1 pods |
| **Scored on** | Two rubric domains, prior knowledge and conceptual questioning, on the printed form |
| **You keep** | Your question, its routes, and this pack |
| **Recorded** | Your question set file, which the coordinator checks and records |
| **Counts toward clearance** | No. The forms are practice, not observations |

### What this session is for

A worked example helps a learner who is new to a topic. The same worked example slows down a
learner who already knows it. This is called expertise reversal, and it is one of the better
supported findings about teaching. It means that a plan pitched at one level is pitched wrongly for
part of any room, and the instructor has to find out which part before deciding what to teach.

The question you write today is how you find out. It is a multiple-choice question whose wrong
options were each written from a known misconception, so the letter a learner holds up tells you
which wrong idea they hold. You run it in the way peer instruction does: everyone votes at once,
argues with someone who voted differently, and votes again, and then you go through every wrong
option. The research on peer instruction found that the learning happens in the argument. That
research was done in university computing courses, so the course uses the method and promises no
particular result.

### What you will be able to do

1. Write a multiple-choice question in which every wrong option is the answer a person holding a
   named misconception would choose.
2. Run a vote, a pair discussion, a revote and a debrief that addresses each wrong option.
3. Read a vote and say what you will do next: move on, discuss, or reteach.
4. Score a peer's cycle on the prior-knowledge and conceptual-questioning anchors.

### Your unit's misconceptions list

Every unit lists the misconceptions its topics are known for, each with an id and a statement. The
coordinator has sent you your unit's list. Here is the one entry in the example unit,
`sl:unit/example-agent-loop@1`:

| id | statement |
|---|---|
| `model-retries-itself` | The model will retry a failed tool call without the loop returning the error |

Your question must use at least one id from your unit's list. If none of the ids fits the slice you
taught in session 1, tell the coordinator by the date in their message: the unit owner may add one,
or you may be asked to write for the example unit instead.

### What makes a question diagnostic

A question about a fact ("What is the default timeout?") has one kind of wrong answer: not knowing.
A diagnostic question asks about something people get wrong, and each wrong option is a different
wrong idea. Before you write an option, name the person who would choose it and what they would
have to believe.

Your question passes when it meets these four tests. Your partner checks it against them in Phase 2.

1. **One idea.** The question tests one idea from your slice, and it is an idea people get wrong,
   not one they forget.
2. **Each wrong option matches its misconception.** Read the misconception statement, then read the
   option. Someone who believes the statement would choose that option.
3. **The answer cannot be spotted.** The correct option is not the longest. It is not the only one
   with a hedge such as "usually", and it does not repeat words from the question.
4. **The options are of similar length,** within a few words of each other.

### What you do with the result

After the first vote you decide what to do next. Crouch and Mazur (2001), who ran peer instruction
for years, give a rule of thumb, and it is practitioners' advice rather than a measured result:

| First vote | What you do |
|---|---|
| Mostly right, above about 70 per cent | Explain briefly why the right answer is right, say a word about the commonest wrong option, and move on |
| In the middle, roughly 30 to 70 per cent | Discussion and a revote, then the debrief. This is where the discussion is worth the time |
| Mostly wrong, below about 30 per cent | Reteach first, then ask a new question on the same idea |

Your question comes with two **routes**: what you will do in the real session when the vote comes
back mostly right, and what you will do when it comes back mostly wrong. The middle needs no route,
because the discussion and revote are the route. Write each route as what happens in the next few
minutes, for example "skip the worked example and go straight to the exercise" or "worked example
first, then a second question on the same loop".

In your pod there are only two or three voters, so the bands are coarse. Two out of two right is
mostly right, one out of two is the middle, and none is mostly wrong. In Phase 3 you run the whole
cycle whatever the first vote shows, so that you practise every part of it, and you say out loud
which route a real room would take.

### Your question set file

Your record for this session is a short YAML file in the shape a unit uses for its `pre_check`.
Here is a worked example for the example unit:

```yaml
unit: sl:unit/example-agent-loop@1
pre_check:
  - topic: tool-use loop
    question: Which stop condition prevents an agent from calling tools forever?
    options:
      - text: A maximum number of turns checked by the loop
        correct: true
      - text: The model notices it is repeating itself and stops
        misconception: model-retries-itself
      - text: The API rejects the tenth call in a row
        proposed_misconception: The API enforces a cap on consecutive tool calls
    routes: {correct: skip worked example, incorrect: worked example first}
```

The second option uses an id from the unit's list. The third option is a wrong idea the list does
not have yet, so it is written out as a statement under `proposed_misconception`. The coordinator
passes proposed misconceptions to the unit owner, who decides whether to add them to the list.

The coordinator runs a checker on your file before recording it. These are the rules it checks:

- `unit` names a unit in the course's unit catalogue. Use the unit id the coordinator confirmed.
- Each item under `pre_check` has a `topic`, a `question`, and `routes` with both `correct` and
  `incorrect`. You write one item today.
- Each item has 3 to 5 options.
- Exactly one option has `correct: true`.
- Every other option has either `misconception`, an id from the unit's list, or
  `proposed_misconception`, a statement of the wrong idea.
- At least one wrong option uses an id from the unit's list.
- The file holds no names: not yours, not a peer's, not a learner's.

The options go on your voting card in the order they appear in the file, as A, B, C and so on, so
do not always put the correct one first.

### Pre-work (light)

1. Reread your session 1 slice plan and your reteach plan, box 2.1 of the session 1 pack.
2. Read your unit's misconceptions list. Choose one idea from your slice that people get wrong, and
   the id that goes with it.
3. Reply to the coordinator by the date in their message with that id, or with "none of these fits
   my slice".
4. Note what you would do in your real session if most of a room got the idea right, and what you
   would do if most got it wrong. These become your routes.

### What to bring

- Your session 1 slice plan and reteach plan
- Your unit's misconceptions list, printed
- Your instructor id, which you write on every form you fill in as a scorer
- A pen

No laptop is needed in the room.

### Pre-session self-check

- [ ] I know which idea from my slice my question will test.
- [ ] I have the misconception id that goes with it, and I have sent it to the coordinator.
- [ ] I have a rough idea of my two routes.
- [ ] I have read the four tests and the file rules above.
- [ ] I know my instructor id.

<!-- pack:demo -->

## How the session runs

One continuous 90-minute block in one room. There is no software and no demo. Instead, the trainer
runs one full cycle on the whole room at the start, with a question about teaching, so that you see
the cycle as a learner before you run your own. Before each phase the trainer gives a one-minute
briefing to the whole room.

| When | What runs |
|------|-----------|
| 0:00-0:05 | Welcome, and why find out what the room knows first |
| 0:05-0:06 | Briefing: the trainer's cycle |
| 0:06-0:18 | **Phase 1**: the trainer runs a cycle on the room, then you take the question apart |
| 0:18-0:19 | Briefing: writing |
| 0:19-0:34 | **Phase 2**: write your question and routes, check a partner's, copy yours onto a card |
| 0:34-0:35 | Briefing: run rounds |
| 0:35-1:11 | **Phase 3**: three slots of 12 minutes, seven running the cycle and five of feedback |
| 1:11-1:12 | Briefing: revising |
| 1:12-1:20 | **Phase 4**: revise from the votes and write your final question |
| 1:20-1:25 | Share-out, both pods together |
| 1:25-1:28 | Reflection, written |
| 1:28-1:30 | Wrap: the trainer collects every form |

### Pods, positions and partners

You are in the same pod and position as in session 1, and you run your cycle in the slot that
matches your position. In each slot the other members of your pod are **peers**: they vote on your
question, discuss it, and then score you.

| Slot | Runs the cycle | Peer 1: speaks first, then sets up | Peer 2: keeps time, speaks second |
|---|---|---|---|
| 1 | Position 1 | Position 2 | Position 3 |
| 2 | Position 2 | Position 3 | Position 1 |
| 3 | Position 3 | Position 1 | Position 2 |

In Phase 2 your **partner** is the person in the same position in the other pod. They check your
question and you check theirs. Because your partner is in the other pod, they never vote on your
question, so it does no harm that they know the answer. If your group is four or five, the trainer
tells you how the pods and partners work.

**As a voter, vote as yourself.** Do not play a misconception, and do not vote for the answer you
think the teacher wants. You are probably new to the topic, which is what the teacher needs.

### The voting cards

You have five cards, A to E. When the teacher has read the question and options, choose a card on
your own and keep it face down. On "three", everyone holds their card flat against their chest,
letter facing the teacher, at the same moment. Nobody shows early and nobody looks around first: a
vote that copies a neighbour tells the teacher nothing.

### The cycle (7 minutes)

| Part | Time | What happens |
|---|---|---|
| Vote | 1:00 | The teacher reads the question and options, everyone thinks alone for 30 seconds, and cards go up on three. The teacher writes the counts on the flipchart without saying which is right |
| Discussion | 2:00 | Voters find someone who chose differently and try to convince them. If everyone chose the same, each voter explains why someone might choose one of the wrong options |
| Revote | 0:30 | The timekeeper calls it at three minutes. Cards up on three again, and the counts go under the first |
| Debrief | 2:30 | The teacher gives the answer, then takes each wrong option in turn by the misconception behind it, then says why the right one is right |
| Route call | 1:00 | The timekeeper calls it at six minutes. The teacher says what the first vote showed, which band it falls in, and what they would do next in the real session |

The timekeeper stops the cycle at seven minutes, finished or not.

### The form

The form is the same one as in session 1. This time only two domains are scored: prior knowledge and
conceptual questioning. The other three come marked "not seen", and you leave them that way. Write
your own instructor id as **Observer id**.

Scores of 3 and 4 are possible today, because the task is built to show both domains. Score what
happened:

- **Prior knowledge** shows in the route call. A route that does not follow from the votes is a 2:
  the check ran and nothing was done with it. A route that names what the vote showed and follows
  from it is a 3.
- **Conceptual questioning** shows in the question and the debrief. Explaining the answer straight
  after the first vote is a 2. The full cycle, with every wrong option addressed in the debrief, is
  a 4. Leave one wrong option out of the debrief and it is a 3.

Score alone and in silence, and write one line of evidence for every score.

### The feedback routine (5 minutes)

| Turn | Who | Time | What happens |
|---|---|---|---|
| Score | Everyone except the teacher | 1:00 | Silent. A score or "not seen" for the two domains, with a line of evidence for each score |
| 1 | Teacher | 0:30 | What the first vote showed against what you expected, and which option surprised you |
| 2 | Peer 1 | 0:45 | Prior knowledge, in the stem below |
| 3 | Peer 2 | 0:45 | Conceptual questioning, in the stem |
| 4 | Trainer | 1:30 | Scores on the two domains, then one revision to the question: the option that did least work, and what to change. If the trainer is in the other pod: each peer names the option that told them least about what the voters believed, and one change to it, 45 seconds each |
| 5 | Teacher | 0:30 | You name the one revision you will make, write it in box 3.1, and take the forms |

### How to say a score

The stem is the session 1 stem:

> "I scored [domain] at [number]. The anchor for [number] says [its words]. What I saw was [what
> happened, and roughly when]."

Two invented examples, from a cycle on the example unit's question:

> "I scored prior knowledge at 3. The anchor for 3 says 'runs the pre-check, names what it showed,
> and skips or adds worked examples accordingly'. After the first vote you said one of the two of
> us had it right, which is the middle, and that in a real room you would run the discussion before
> the worked example."

> "I scored conceptual questioning at 3. The anchor for 4 says 'a debrief that addresses each wrong
> answer'. You explained why the model does not notice it is repeating itself, and then went
> straight to the right answer, so the API option was never addressed."

<!-- pack:worksheet -->

## During the session

This is your own record, and you keep it. The forms are collected at the end; this pack is not.

In the step lists, **[A]** is everyone, **[T]** is the teacher and **[P]** is the peers. When you are
not running the cycle, you are a peer.

### Phase 1 -- The trainer's cycle (12 min, 0:06-0:18, whole room)

> **Briefing at 0:05**, one minute. For twelve minutes you are the trainer's learners. You vote on a
> question about teaching, discuss it, vote again, and then take the question apart.

```text
1. Read the trainer's question, choose a card on your own, and vote on      [A]  1 min
   three
   done when: the trainer has written the counts on the flipchart
2. Find someone who chose a different letter and try to convince them      [A]  2 min
   done when: the trainer calls the revote
3. Vote again, then listen to the debrief of each wrong option             [A]  3 min
   done when: the trainer has explained every wrong option
4. Listen to the route call: what the first vote showed, and what a real   [A]  1 min
   session would do next
   done when: the trainer has named the route
5. Match each misconception to the option its holder would choose, then   [A]  5 min
   see the four tests and the file shape
   done when: every wrong option has its misconception
```

**1.1 -- One thing the trainer did in the cycle that you will do in yours.**

> ______________________________________________________________________

### Phase 2 -- Write, check and copy (15 min, 0:19-0:34, on your own, then with your partner)

> **Briefing at 0:18.** Write alone for ten minutes, check with your partner from the other pod for
> three, and copy onto your card for two.

```text
6. Choose one idea from your slice and the misconception id that goes      [A]  2 min
   with it
   done when: the first two rows of box 2.1 are filled in
7. Write the question and 3 to 5 options, with the misconception id or a   [A]  6 min
   proposed statement next to each wrong option
   done when: every option row in box 2.1 has its text and its mark
8. Write your two routes                                                   [A]  2 min
   done when: both route rows in box 2.1 say what happens next
9. Swap with your partner and check each other's question against the     [A]  3 min
   four tests and the file rules, 90 seconds each
   done when: every box in the 2.2 checklist is ticked or has a fix next
   to it
10. Copy the question and options onto your A3 card in large letters,      [A]  2 min
    without the ids
    done when: the card is ready to hold up
```

**2.1 -- Your draft.**

| | |
|---|---|
| Unit id | |
| The one idea this question tests | |
| The question | |

| Option | Text | Correct, or misconception id, or proposed statement |
|---|---|---|
| A | | |
| B | | |
| C | | |
| D | | |
| E | | |

| Route | What you do in the next few minutes of the real session |
|---|---|
| Mostly right (above about 70 per cent) | |
| Mostly wrong (below about 30 per cent) | |

**2.2 -- Partner check.** Your partner ticks each line, or writes the fix next to it.

- [ ] One idea, and an idea people get wrong rather than forget
- [ ] Each wrong option is what someone holding its misconception would choose
- [ ] The correct answer cannot be spotted from its wording or length
- [ ] The options are of similar length
- [ ] 3 to 5 options, exactly one correct
- [ ] At least one wrong option uses an id from the unit's list
- [ ] The two routes lead to different next minutes

### Phase 3 -- Run the cycle and feedback (36 min, 0:35-1:11, in your pod)

> **Briefing at 0:34.** Three slots of twelve minutes, in your session 1 positions. Seven minutes of
> the cycle, one of silent scoring, four of feedback. The timekeeper calls the revote at three
> minutes, the route call at six, and stops you at seven.

```text
11. Run your cycle: vote, discussion, revote, debrief of each wrong        [T]  7 min
    option, route call
    done when: peer 2 calls seven minutes, finished or not
12. Score the cycle in silence, prior knowledge and conceptual             [P]  1 min
    questioning only
    done when: every peer has a score or "not seen" for both domains and a
    line of evidence for each score
13. Run the feedback round in the order of the table, and name the one     [P]  4 min
    revision
    done when: the teacher has written the revision in box 3.1 and has the
    forms
```

**3.1 -- Your cycle's result** (fill in when you are the teacher).

| | |
|---|---|
| First vote, count per letter | |
| Revote, count per letter | |
| The band the first vote fell in, and the route you named | |
| What the discussion told you about any option | |
| The one revision | |

- [ ] Ran the whole cycle, and every wrong option came up in the debrief
- [ ] Scored every cycle I voted in, in the silent minute, with evidence for each score
- [ ] Spoke in the stem when it was my turn

### Phase 4 -- Revise and write the final question (8 min, 1:12-1:20, on your own)

> **Briefing at 1:11.** Make the one revision, then write the final version into box 4.1 in the
> order the file needs. The trainer visits some of you.

```text
14. Read your counts, box 3.1 and your forms, and confirm the one revision [A]  2 min
    done when: you know which option or route changes, and how
15. Make the revision in box 2.1                                           [A]  3 min
    done when: the changed option or route is rewritten and still passes
    the four tests
16. Write the final question into box 4.1, every field                     [A]  3 min
    done when: every row of box 4.1 is filled in
```

A wrong option that nobody chose stays, unless your peers said its wording gave it away. Two or
three votes cannot show that an option is useless; a room of twenty might choose it.

**4.1 -- Your final question, in file order.**

| Field | Your entry |
|---|---|
| `unit` | |
| `topic` | |
| `question` | |
| Option A `text` | |
| Option A: `correct: true`, or `misconception`, or `proposed_misconception` | |
| Option B `text` | |
| Option B: mark | |
| Option C `text` | |
| Option C: mark | |
| Option D `text` (if used) | |
| Option D: mark | |
| Option E `text` (if used) | |
| Option E: mark | |
| `routes` `correct` | |
| `routes` `incorrect` | |

- [ ] Exactly one option marked `correct: true`
- [ ] At least one `misconception` id from the unit's list
- [ ] No names anywhere

### Share-out (1:20-1:25, both pods together)

Forty seconds each, pod A first: the misconception your question targets, the first vote and revote
counts, and the one revision. A first vote that came back mostly right is a result to report. Its
route is to explain briefly and move on.

### Reflection (1:25-1:28)

**R.1 -- Where in your real session does this question go, and what will you do in the minute
after the first vote if the room splits?**

> ______________________________________________________________________

**R.2 -- Which part of the cycle was hardest to run as the teacher, and what will you do
differently?**

> ______________________________________________________________________

<!-- pack:rubric -->

## After the session

### Sending your question set file

Within two working days, type box 4.1 into a file in the shape of the worked example under "Your
question set file", and send it to the coordinator. Name the file anything you like; the coordinator
files it under a key of their own. Leave every name out of it.

If you have the teachermodel repository, you can check the file yourself first with
`teachermodel check-questions <file>`. It prints each problem it finds, then "ok" or the number of
problems. The coordinator runs the same check either way. If it finds problems, you get the list
back and send a corrected file.

Once the file passes, the coordinator stores it in the private store and records session 2 on your
course record, dated the day of the session.

### What happens to your forms

The trainer collects every form at 1:28 and gives them to the coordinator the same day. They are
kept in the private store with your session 1 forms. They are not the record for this session: the
question set file is.

The forms are formative. They are not observations, they never count toward your clearance, and
only the technical training function sees them: your manager does not, and neither does anyone
running a performance review.

### What you keep for later sessions

- **Your question and its routes.** Session 4 has you teach your session 1 slice remotely, and the
  question goes into it, with remote learners voting too.
- **Box R.2.** Session 5 asks you to score recordings on all five domains, two of which you were
  scored on today.

### How this is marked

It is not marked, and there is no pass mark. Session 2 counts as complete once the coordinator has
recorded your question set file. The course is complete when all five sessions are recorded.
