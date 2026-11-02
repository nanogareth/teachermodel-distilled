# Feeds (G2, G3, G4, G13) and Wave 0 fixes (spec and plan)

Date: 2026-10-30. Builds on the foundations (decision 0027), signed off by the owner on 2026-10-30. Decision 0028 records the contract choices.

## Feeds

Each feed is a small file that one system writes and teachermodel keeps under `inputs/`, never as events. None holds
a person's name, a score or a path; they hold lab slugs, delivery references and counts.

### G2 Lab registry (proving-ground)

`tools/release/checks.json` gains `labs`: per lab its slug, the unit it serves (`null` until linked; never guessed)
and its owner role. Every command names the `lab` it checks, or `null` for a shared check. `release_check.py` adds a
`registry` result: it fails when a folder under `scenarios/` is not registered, or a registered lab has no command.
The trial lab `aggregates-only-export` is registered and checked by `tools/check_scenario.py`; `jsonschema` and
`pyyaml` join the install list, since its tests and the checker need them.

### G3 Release status feed (`tm:contract/release-status@1`)

`release_check.py --status <file>` writes, per registered lab, its status (`passed` / `failed` / `not-run`) and counts
of checks and failures; the shared checks (SDK, model ids, CLIs, registry) are summarised once. No detail text, so no
path or output leaves. `release_check_local.py` writes it beside the reports and, when `TEACHERMODEL_PRIVATE_DIR` is
set on that machine, drops a copy into `<store>/inbox/`.

### G4 Results received (`tm:contract/results-received@1`)

`export_outcomes.py --received <file>` is the exporter's dry run: per delivery in the manifest, results received and
results unreadable, as counts. It never refuses on an unreadable result (that is what it counts) and writes no score.

### G13 Bookings with an export date (`tm:contract/bookings@2`)

`bookings@2` requires `exported_at`. `bookings@1` stays readable (moved to `contracts/v1/`); for it the freshness
register still reads the file's modification time.

### teachermodel side

- `teachermodel import-feed <file>` checks a `release-status@1` or `results-received@1` file and keeps it as
  `inputs/release-status.json` or `inputs/results-received.json`. A refusal lists every problem and writes nothing.
- The daily job imports every file in `inbox/` first: a kept file moves to `inbox/done/`, a refused one to
  `inbox/refused/` with its reasons beside it, and the log line says so.
- Freshness: `release-check` reads `run_at` from the kept status (no longer `not-connected`); `bookings` reads
  `exported_at` from a `bookings@2` file.
- This week: `lab-unchecked` is raised for a session whose lab is missing from the latest status, failed, or whose
  feed is not `ok`.
- Coordinator board: `received` and `unreadable` per delivery from `results-received` until an outcome arrives; the
  audience policy adds `deliveries.unreadable`.

## Wave 0 fixes

| Fix | Where | Test |
| --- | --- | --- |
| Train-the-trainer sign-off: no decision while a session is missing; the inherited delivery reference dropped | `flows/onboarding.py` `_b_train_the_trainer` | page has no decision control with 4 of 5 sessions; no `delivery` field |
| `lab-note` fails on `TODO(lab)`; `filled` gives a total | proving-ground `check_scenario.py` | scaffold fails lab-note; 19 placeholders reported as a total |
| `--join` checks the room before saying joined; refusals in words | proving-ground `checkpoints/checkpoint.py` | wrong code, unreachable, joined |
| The room page shows when the last report arrived, not the draw time | proving-ground `checkpoints/collector.py` | page carries the last report's time; none yet says so |
| `carry` refuses a second audition for the same instructor | `audition.py` | second carry refused, first plan kept |
| An observer can be replaced before they score | `audition.py`, `audition replace` | replace before scoring; refused after |
| A warn exits 3: `CLAUDE.md` and the systems map say so | docs | none (wording) |

## Plan

1. proving-ground: registry and `--status` (G2, G3), `--received` (G4), check_scenario fix, checkpoint fixes; tests.
2. teachermodel: contracts, `feeds.py`, `import-feed`, daily inbox, freshness readers, surfaces; `bookings@2`; tests.
3. Wave 0 fixes in teachermodel; tests.
4. Decision 0028, `CLAUDE.md`; full suites; commit and push both repos.
5. The head's This week page from `surfaces.project(this_week, "this-week", "head-of-training")`.
