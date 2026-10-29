# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is
teachermodel: instructor clearance, coaching and quality rules for a technical training function
(spec v0.2, experienced-engineer edition). A spoke following hub conventions
(`docs/hub-alignment.md`). Current phase: see `docs/plans/phase-plan.md`.

## Commands
```bash
py -m pip install -e . pytest      # install with test deps
py -m pytest                       # all tests
py -m pytest tests/test_rules.py -k clearance -v
teachermodel validate              # schema + cross-checks on standards/
teachermodel verify-events <path>  # schema, receipts, duplicate ids in an event log
teachermodel staffing-check --instructor <uri> --unit <uri> --mode <mode> --date <YYYY-MM-DD>  # exit 0 ok/warn, 2 block
teachermodel check-roster <path>   # roster file against tm:contract/roster@1
teachermodel revoke-page --step <id> [--subject <uri>]  # a page to revoke an approval in force (0019)
teachermodel gates                 # phase gates and acceptance criteria computed from the store (read only)
teachermodel index                 # rebuild the disposable SQLite index (index/teachermodel.sqlite)
teachermodel views                 # index + read views in views/: clearance matrix, coaching logs, quality review, records
teachermodel history --clearance <uri>  # a clearance's full history from the log alone
teachermodel audit-export --quarter <YYYYQn>  # a quarter's audit samples as JSON (exports/)
teachermodel paper --unit <uri>    # printable run sheet and rubric (paper fallback, 0022)
teachermodel handoff --unit <uri>  # expert-to-session handoff and what the unit still lacks
teachermodel init-pilot --owner-name <name> --owner-email <work mailbox>  # pilot store: layout, settings, people, generated inputs, env var (0016)
teachermodel pilot-sign <signoff.json>...  # pilot store only: sign-offs of generated signers, who have no mailbox (0016)
teachermodel dev-simulate --store <dir> [--weeks 26] [--end YYYY-MM-DD] [--reset]  # a simulated store: months of generated use (0020)
teachermodel dev-autosign [--generated-only]  # pilot store only, development: tick, import, calibrate, sign every due page
teachermodel export-pack --bench <uri> [--out <pdf>]  # a bench evidence pack as PDF ([browser] extra)
teachermodel graph-read            # latest plan through the Graph driver (TEACHERMODEL_GRAPH_* env), ingest, tick
teachermodel daily                 # the daily job: tick (or dev-autosign when dev-mode is on); logs to logs/daily.log
teachermodel dev-mode on|off|status  # pilot store only: the development toggle (settings dev_autosign)
teachermodel schedule-daily [--time HH:MM] [--every-day] [--remove]  # the Windows task that runs `daily`
py scripts/tour.py [--gui] [--audience leadership|instructors|team] [--check] [--sheet]  # live demo on ~/teachermodel-tour; --gui presents from the browser (docs/tour/run-sheet.md)
```

## Layout
- `standards/` reference data (YAML/markdown). Source of truth for thresholds; the spec snapshot is not.
  `standards/workflows/<slug>.yaml` is one workflow per file (each declares its `event_kinds`); `load_standards` merges them.
- `contracts/` JSON Schemas, `$id` `tm:contract/<name>@<major>`. Breaking change = new major + decision record.
- `src/teachermodel/rules.py` pure, deterministic rule functions. `events.py` append-only JSONL log.
  `standards.py` loading and validation. `resources.py` where `standards/` and `contracts/` live (`root()`).
  `flows/<slug>.py` page builders per workflow, registered in `flows/__init__.py`. `cli.py` entry point.
- `docs/` spec snapshot, evidence summary, phase plan, MADR decisions.

## Rules for changes
- **Evidence gate (decision 0002):** change a threshold or domain in `standards/` only with a
  decision record citing evidence rated strong, or label it an operational default.
- **No model in the decision path.** Rule functions stay pure and deterministic; no LLM calls in
  `rules.py`, and no randomness (the audit sample is hash-ranked).
- **Personal data never in git** (decision 0003). Events hold `tm:` URIs and private-store keys,
  never names, evidence notes or recording links. Do not add fixtures with real people.
- **Append-only events.** Never rewrite or delete log lines; corrections are new events.
- **Automate all setup and processes (owner, 2026-10-26).** Every setup step and every recurring process is a
  committed script, CLI command, workflow step or scheduled tick. Never a manual procedure in a runbook. A person
  does only what policy or law makes theirs: a sign-off, a decision, a consent click, or an action in a system we
  cannot reach. Even then, the system prepares the page or draft, records the result and checks it. A runbook
  step a script could do is a defect: build the script.
- Every rule change ships with a unit test for the threshold edge.
- IDs are stable and meaningless (`tm:<kind>/<slug>`); never encode order.
- Windows host: use `py`, keep paths portable, keep `.gitattributes` LF rules for hashed files.
- Concurrent sessions may share the working tree: commit with explicit pathspecs.

## Open decisions that block real data
0004 ownership, 0005 performance-management separation (status only, never scores) and 0006
private store are accepted. Still open before real data: retention periods per data category and
purpose, verified jurisdiction profiles (Ireland/EU, California), and the IT library.
