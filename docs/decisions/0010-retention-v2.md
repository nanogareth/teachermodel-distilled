---
status: accepted
date: 2026-10-24
supersedes: null
---
# 0010 retention@2: retention per data category and purpose

## Context
`retention@1` is a fixed list of five nullable periods (observations, recording references,
outcome summaries, event log, identities after the engagement ends). The privacy-jurisdictions
design (`docs/specs/2026-10-24-privacy-jurisdictions-design.md`, §2 and §3) needs a period for each
data category and purpose, the event that starts the clock, a plain-language reason that the notice
can quote, and room for an overlay jurisdiction to differ. Five fixed names cannot say that.

## Options
1. Add optional fields to `retention@1` in place. The fixed `periods` object stays the wrong shape
   and consumers that read it keep working only by accident.
2. Bump to `retention@2` with a list of entries; keep `retention@1` in `contracts/v1/`.
3. Keep the periods in the profile files. Mixes the programme's choices with the law's limits.

## Decision
Option 2 (owner approved the spec, 2026-10-24).

`retention@2` is `{schema_version: 2, status, basis, entries[]}`. Each entry has `category` (a data
category id from `setup.data_categories`), `purpose` (a `tm:purpose/` id), an optional
`jurisdiction` (a `tm:jurisdiction/` id; absent for the base entry), either `period_months`
(integer, 1 or more) or `until_event`, `starts` (the event that starts the clock), `reason`
(plain language, at least 20 characters) and `basis` (a GDPR Article 6(1) lawful basis).

- `validate` checks each entry names a known category and that no category, purpose and
  jurisdiction has two entries. That every category and purpose pair a workflow uses has an entry,
  and that entries stay inside a verified profile's limits, arrive with the privacy-base workflow.
- `standards/retention.yaml` is a `retention@2` document with `status: draft` and `entries: []`.
  No entry exists until the owner sets them on legal advice (decision 0002 applies: an entry
  cites evidence or is labelled an operational default).
- No entries means nothing is set: the notice refuses to render and no approval page is built,
  the same as the old null periods.
- `data_categories` gets stable ids (`identity-data`, `pseudonymous-identifier`,
  `employment-and-training-data`, `delivery-data`, `performance-data`, `record-of-actions`) so
  that purposes and retention entries can refer to them.

## Consequences
No retention values were ever set, so there is nothing to migrate. `contracts/v1/retention.schema.json`
keeps the @1 text byte for byte (pinned in `tests/test_contracts.py`). The ROPA entry and the
privacy notice list each entry with its period, start and reason instead of five fixed lines.
