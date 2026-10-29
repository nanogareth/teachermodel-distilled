---
status: accepted
date: 2026-10-24
supersedes: null
---
# 0006 Private store location, access and backup

## Context
0003 puts instructor personal data and the live event log outside git; in a deployment they are the deploying
organisation's data (0004). A private store inside the working tree is refused by the code, so tests and fictional examples
use a directory outside the repo. It would not do for real records either: it sits on one laptop disk, outside company backup and access control,
one `git add -f` away from a commit. The store holds performance data about named employees and
contractors (spec, Privacy), so GDPR applies in full. Pseudonymised data, such as events keyed by
`tm:instructor/` URIs, is still personal data (GDPR Recital 26), so the event log needs the same
care as the identities.

## Options
1. Local folder outside the repo (e.g. `%USERPROFILE%\teachermodel-private`), BitLocker, own backup.
2. Restricted SharePoint document library in the Microsoft 365 tenant, synced locally with OneDrive.
3. A database server.

## Decision
Option 2 (owner, 2026-10-24). A company-controlled location gives access control, audit logging,
encryption at rest, versioning and retention labels without building any of them; option 1 makes
one person the backup system, and option 3 contradicts 0003.

- **Location.** A dedicated SharePoint library (not a personal OneDrive folder, which leaves with
  its owner), synced to a path under `%USERPROFILE%`. `TEACHERMODEL_PRIVATE_DIR` points at the
  synced path. Never under `%LOCALAPPDATA%`/`%APPDATA%`: Claude desktop sessions redirect new
  files written there into the app package, invisible to other programs.
- **Access.** Least privilege through one security group: head of training and the
  programme owner write; nobody else reads raw files. Other roles see views, not the store
  (spec, role table). No sharing links. Library audit log on.
- **Layout.**
  - `identities/roster.yaml` is the only file linking `tm:instructor/` URIs to names and emails.
  - `evidence/` holds observation notes and recording links, keyed by the event `payload` key.
  - `events/events.jsonl` is the live append-only log.
  - `imports/` holds roster and outcome files as received, read-only after import.
- **One writer.** A single machine appends to the event log. Two synced machines writing the same
  JSONL produce OneDrive conflict copies, which split the log. The SQLite index stays in `out/`,
  never in the synced folder: SQLite should not live on a synced or network filesystem.
- **Backup.** SharePoint versioning and the recycle bin are recovery, not backup. Add a nightly
  copy (spec, Backup) to a second company location, with a SHA-256 manifest of each file. Test a
  restore each quarter: `teachermodel verify-events` must pass on the restored log.
- **Erasure and retention.** Erasure deletes the identity row and evidence files. Events stay but
  can no longer be linked to a person. Retention periods (spec open question) are set with legal
  advice and applied as retention labels.
- **Before real data.** Record the processing in the organisation's record of processing activities.
  Ask the DPO whether a DPIA is needed (GDPR Art. 35): systematic evaluation of employees'
  performance is a common trigger. Issue the privacy notice (spec, Lawful basis) first; the
  roster contract requires a notice date per instructor.

## Consequences
When the event writers land (phase 3), the CLI reads `TEACHERMODEL_PRIVATE_DIR` and refuses live
writes to a path inside the git working tree. Tests and examples keep using fictional data in the repo.

## Amended 2026-10-24
Context sentence changed: it said a default `.private/` inside the working tree was fine for tests and
fictional examples. The code refuses any in-repo path (`config.assert_outside_repo`); tests and the
end-to-end script use a temporary directory outside the repo. The decision itself is unchanged.
