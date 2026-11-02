# Role surfaces: foundations (spec and plan)

Date: 2026-10-30. Owner's choices on 2026-10-30: the session schedule comes from a calendar export; pages go out by
email once IT grants Mail.Send on the programme mailbox; build the foundations first. Decision 0027 records the choices this spec makes.

## Scope

Three foundations that every role surface reads, with no new pages yet:

1. **G1 Session schedule** (`tm:contract/schedule@1`): the sessions a calendar export lists, kept as a validated
   input file, never as events.
2. **G11 Freshness register** (`standards/freshness.yaml`): when each source last reported, against how often it
   should; a source past its limit is an item for its owner.
3. **G9 Audience policy and read models** (`standards/audience.yaml`, `src/teachermodel/surfaces.py`): one read model
   per surface (head's This week, coordinator board, instructor's My record) as data, each projected through the
   policy for a role, and a test that renders every surface for every role and fails on a field the role may not
   see.

Out of scope here: the HTML pages, outbound mail (G10), and the feeds from proving-ground (G2-G5).

## G1 Session schedule

`inputs/schedule.yaml`, like `inputs/bookings.yaml` (decision 0026): a calendar export says where people will be, so
it is a private input, read only by the commands that need it, and never an event. Sessions are plans; the facts of a
delivery still arrive as outcomes and observations.

```yaml
schema: tm:contract/schedule@1
exported_at: 2026-10-28T07:00:00Z
sessions:
  - ref: cohort12-agg-lab          # the session reference, never a client or a person
    programme: cohort-12
    unit: sl:unit/example-agent-loop@1
    lab: aggregates-only-export    # optional: a proving-ground scenario slug
    mode: hybrid                   # in-person | remote | hybrid
    from: 2026-11-12
    to: 2026-11-12
    region: IE
    lead: tm:instructor/g1x9d
    co: []                         # optional
    observer: tm:instructor/d7h2k  # optional
    expected_learners: 24
    status: confirmed              # held | confirmed | cancelled
```

- `teachermodel import-schedule <file>` checks the file and, when it passes, copies it to `inputs/schedule.yaml`.
  It lists every problem at once (schema, a session ending before it starts, a ref used twice, an unknown unit) and
  writes nothing on a refusal.
- The same gate as bookings: a store that is not simulated refuses to read a schedule until `standards/retention.yaml`
  has an entry for `schedule-records`.
- `schedule.load(private, settings)` returns the sessions or None; read models call it.

## G11 Freshness register

`standards/freshness.yaml` lists each source, its owner role, how often it should report and the grace before it is
stale, and how its last report is read:

| Source | Owner | Every | Last report read from |
| --- | --- | --- | --- |
| daily job | head of training | 1 day | the last line of `logs/daily.log` |
| lab outcomes | coordinator | 31 days | the newest `outcome` event |
| schedule | coordinator | 7 days | `exported_at` in `inputs/schedule.yaml` |
| bookings | coordinator | 7 days | the file's modification time, until `bookings@2` carries `exported_at` (G13) |
| release check | lab maintainer | 7 days | not connected yet (G3) |

`freshness.assess(sources, seen, now)` is pure: each source is `ok`, `stale` (past every plus grace), `never` (no
report yet) or `not-connected` (no reader yet). `freshness.status(private, now)` reads the store and calls it.

## G9 Audience policy and read models

`standards/audience.yaml` names, for each role, the surfaces it may open and, for each surface, the fields each role
keeps. Anything not listed is dropped. The coordinator's entry also lists the words that must never appear as a field
name in anything it receives (`score`, `baseline`, `pass_rate`, `mean`), so a field added to a read model later cannot
leak a score through a whitelist mistake.

`surfaces.py` builds three read models from the index, the schedule, the course records, the audition folders and the
freshness register, each a plain dict:

| Read model | For | Content |
| --- | --- | --- |
| `this_week` | head of training | decisions (open quality triggers, auditions awaiting a decision); risks in the next 21 days (a session whose lead's clearance expires or is due a recheck before it ends, a session whose lab has no release check yet); sources not reporting; waiting on others; counts of what is fine |
| `coordinator_board` | coordinator | this month's sessions with learners expected and results received as counts; the course grid; each audition's stage; sources the coordinator owns |
| `my_record` | one instructor | their sessions ahead, clearances, rubric scores per domain per observation, own outcomes, coaching cycles, course record |

`surfaces.project(model, surface, role, viewer=None)` applies the policy. An instructor may open `my_record` only for
themself: any other subject is refused.

## Tests (written first)

- `test_schedule.py`: a valid export loads; every problem in a bad export is listed at once; the gate refuses a
  non-simulated store without a retention entry; `import-schedule` writes nothing on a refusal.
- `test_freshness.py`: the edges of `assess` (one day before stale, the day it turns stale, never, not connected);
  `status` on a simulated store reads the daily log and the newest outcome.
- `test_surfaces.py`: each read model on a simulated store has the content above; and the privacy test, which builds
  every surface, projects it for every role and asserts: a role cannot open a surface it is not given; no projected
  field is outside the role's list; nothing the coordinator receives has a forbidden word in any key; an instructor's
  record carries no other instructor's id; no name from `identities/` appears in any projection.

## Plan

1. `contracts/schedule.schema.json`, `src/teachermodel/schedule.py`, `import-schedule` in the CLI; tests.
2. `standards/freshness.yaml`, `src/teachermodel/freshness.py`; tests.
3. `standards/audience.yaml`, `src/teachermodel/surfaces.py`; read model tests, then the privacy test.
4. Decision 0027, `CLAUDE.md` commands, the full suite; commit and push.
