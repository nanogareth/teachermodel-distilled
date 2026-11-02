# 0028: Lab feeds (release status, results received) and bookings@2

Date: 2026-10-30. Status: accepted (owner, 2026-10-30: foundations signed off, feeds next as planned in
`docs/specs/2026-10-30-feeds-and-wave0.md`).

## Context

The role surfaces (decision 0027) had two empty charts and one guess: the head's risk timeline could not say whether a
session's lab still passed against the newest releases, the coordinator board could not say how many results had
arrived before the outcome export, and the bookings source's freshness came from the file's modification time. The
weekly release check also missed one lab entirely (`aggregates-only-export`), because the list of checks was kept by
hand with nothing to say a lab was missing.

## Decision

1. **Two feeds, as inputs.** `tm:contract/release-status@1` (proving-ground `release_check.py --status`) and
   `tm:contract/results-received@1` (`export_outcomes.py --received`) are kept under `inputs/` by
   `teachermodel import-feed`, never as events. Both hold counts, lab slugs and delivery references only: no output
   text, file name, score, pass or person. They need no retention entry, since they hold no personal data.
2. **An inbox.** Files dropped in the store's `inbox/` are imported by the daily job first; kept files move to
   `inbox/done/`, refused ones to `inbox/refused/` with their reasons. proving-ground's weekly run drops its status
   feed there when `PROVING_GROUND_FEED_STORE` names a store on that machine, so no one carries the file by hand. It
   is an explicit opt-in: real release results reach a store only after the role surfaces have been tested on
   generated data (owner, 2026-10-30), never because the store's own variable is set.
3. **A lab registry.** `tools/release/checks.json` lists every lab and each command names its lab. The release check
   fails when a scenario folder is not registered or a registered lab has no command.
4. **bookings@2** requires `exported_at`; the freshness register reads it. `bookings@1` is kept in `contracts/v1/`
   and still read, with the file's modification time standing in.
5. The contracts are teachermodel's; proving-ground keeps pinned copies (`tools/contracts/`), as for outcome-import.

## Consequences

- This week raises `lab-failing` for a session whose lab failed the latest run, and `lab-unchecked` when the lab is
  missing from it or the feed is stale or absent. The coordinator board shows results received and unreadable.
- The registry's units are `null` until each lab's unit is confirmed: they are not guessed.
- A breaking change to either feed is a new major in both repositories at once.
