---
status: accepted
date: 2026-10-26
supersedes: null
---
# 0016 Interim OneDrive store for a synthetic-data pilot until the tenant move

## Context
IT has agreed to set up the private store as the IT request describes (0006: a restricted SharePoint library, one
security group, no sharing links, audit log, versioning, a nightly copy). It will do so only after the
organisation moves to a new Microsoft 365 tenant. Until then, IT has asked the programme owner to develop and test in a private OneDrive folder.

0006 rejected a personal OneDrive folder for real records: it leaves with its owner, and it has no security group
for the store and no nightly copy. Those reasons still hold. The owner also wants the pilot to exercise audit
logging before the library exists.

## Decision
Owner, 2026-10-26.

1. **Interim store.** Until the library exists, `TEACHERMODEL_PRIVATE_DIR` may point at a private OneDrive for
   Business folder of the programme owner, synced under `%USERPROFILE%`, never under `%LOCALAPPDATA%` or
   `%APPDATA%` (0006, Location). The folder is shared with nobody, and has no sharing links.
2. **Artificially generated data only.** The pilot may hold any amount of generated data: generated instructors,
   observations, outcome imports, sign-offs and events. It holds no record about a real instructor or learner and
   no real recording link. Every generated instructor's email address uses a reserved domain (`example.com`,
   `example.org`, `example.net`, or a `.example`, `.test` or `.invalid` name; RFC 2606). Real people may appear
   only as signers of the roles they hold, for example the programme owner signing as several roles.
3. **The pilot tests audit logging.** It runs the whole workflow, so it exercises both audit trails: the
   system's own record of actions (the append-only event log and `record_access` events), and the Microsoft 365
   audit log for the OneDrive folder. Searching that log needs an audit role in Microsoft Purview, which IT or the
   compliance team holds. The owner asks them to run one search during the pilot and records the result in the
   runbook.
4. **No migration.** The pilot store is never copied into the library. The real store starts empty, with a new
   event log, when the library exists and the privacy-base workflow is complete (0006, Before real data).
5. **Tenant.** The IT request and the record of processing keep naming the current tenant until the move
   (owner, 2026-10-26). They change when IT names the new tenant.

## Consequences
- `tm:step/it-done` stays open, and shows overdue on the daily tick, until IT creates the library. That
  is expected.
- The move may change who is the controller. The record of processing names the organisation as controller
  (decision 0004). When legal confirms the controller after the move, the record of processing changes, and its
  bound DPO approval reopens.
- The code enforces point 2 (owner, 2026-10-26):
  - `pilot: true` in `settings.yaml` (`tm:contract/settings@1`, an optional field) marks a pilot store.
  - Roster import into a pilot store refuses any instructor whose email is not on a reserved domain, before the
    file is copied into the store. The refusal names the instructor id and the domain, never the address.
  - A store inside the user's own OneDrive folder (`%OneDriveCommercial%`, `%OneDriveConsumer%` or `%OneDrive%`)
    must be marked as a pilot, so a forgotten flag also refuses the import. A synced SharePoint library has its
    own folder beside OneDrive, so it is not affected.
  - The guard checks emails only. A generated roster can still carry a real name; keep names generated too.
- `teachermodel init-pilot` sets the pilot store up in one command: the layout, `settings.yaml` with
  `pilot: true`, a people list in which the owner holds every office role, a generated roster, outcome export and
  calibration answer sheet under `inputs/`, and the environment variable.
- Generated people have example.com addresses, so no mail comes from them. `teachermodel pilot-sign <file>...`
  ingests the sign-off files saved from their pages, as a receipt of the `pilot` driver with every check of a real
  receipt. It refuses a store without `pilot: true` and any signer who is not generated, so the owner's own
  sign-offs still go through the mailbox and the connector. `teachermodel ingest` never accepts the `pilot` driver,
  and a pilot receipt is not recorded as a read of the sign-off mailbox.
