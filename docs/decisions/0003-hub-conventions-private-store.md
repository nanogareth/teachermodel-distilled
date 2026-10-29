---
status: accepted
date: 2026-10-23
supersedes: null
---
# 0003 Follow hub conventions; personal data outside git

## Context
Work repos align with an integrated platform design (2026-09-30): PROJECT.yaml,
contracts, files as the database, append-only events, MADR decisions, personal data outside git.
v0.1 assumed a SQLite store inside the programme control centre.

## Decision
teachermodel is a spoke. Reference standards are versioned files in git; actuals are an
append-only JSONL event log; instructor personal data lives only in a private store outside git
(location given by `TEACHERMODEL_PRIVATE_DIR` or `--private-dir`, never inside the working tree); SQLite is a disposable index. The staffing check is
exposed through `contracts/staffing-check.schema.json`.

## Consequences
Events carry references, never names or evidence notes. Backups must cover the private store and
the event log. The event log location for live data is outside the repo.

## Amended 2026-10-24
The original text named `.private/` as the default private store. There is no in-tree default: the code
refuses any path inside the git working tree (`config.assert_outside_repo`, decision 0006).
