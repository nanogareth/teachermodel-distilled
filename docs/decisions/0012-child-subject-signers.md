---
status: accepted
date: 2026-10-25
supersedes: null
---
# 0012 Child-subject signers and the people-to-instructor mapping

## Context
Increment 2 adds steps whose subject is an assignment or an exercise (`observe`, `self-assessment`,
`calibration-score`). Who signs them is named by the subject, not by the role alone: the assigned observer, the instructor
observed, any one of an exercise's observers. The ingest checked a role-bound signer against the subject URI itself, so no
one could sign these steps, and stream B matched people-list persons to instructors by slug, which only works while the two
lists happen to share names.

## Decision
1. `workflows@1` gains an optional step field `signer` (backward compatible): `attrs.observer`, `attrs.instructor` or
   `attrs.observers`. Ingest resolves the expected signer from the child subject's attrs. For `attrs.observers`, any listed
   observer who has not already had an approving sign-off accepted for that step and subject may sign. The signer must also
   hold the step's role.
2. Roster instructors hold `instructor`, and `clearer` while their latest level (the latest `level_change`, else the
   registration) is clearer.
3. `people@1` gains an optional `instructor` (`tm:instructor/<slug>`) on a person row (backward compatible). It is the only
   link between a people-list person and an instructor URI. Slug matching is removed. A mapped person signs as that
   instructor (signer = the instructor URI, sender = the person's mailbox) with the person's roles, `instructor`, and
   `clearer` when the instructor is at that level; a mapped person who holds `clearer` or `coach` counts as one for the
   observation rotation. A URI is mapped by at most one person.
4. A flow registers a content check per step (`flows.content_check`), run by ingest on approving sign-offs after the
   envelope is accepted, so a sign-off whose scores are missing or out of range is rejected at ingest and never stored.

## Consequences
No live data exists. A deployment that wants a person to observe adds `instructor: tm:instructor/<slug>` to their row; a
person without it is not an observer. Tests and the E2E use roster instructors at level clearer instead.

## Amended 2026-10-25 (integration review, finding 5)
Clearer status comes from the level, not from the people list. Points 2 and 3 above are tightened:
- An instructor holds `clearer` only while their latest level (the latest `level_change`, else the registration) is clearer.
  A people-list `clearer` role on a person mapped to an instructor no longer grants it by itself, under the person's own URI
  or the instructor's (`signoff.identities`, `flows.common.clearer_instructors`); the role counts only while the mapped
  instructor is a clearer by level. A mapped person's `coach` role is unchanged.
- The observer pool (`propose-observations`) is the instructors who are clearers by level AND calibrated on the day of the
  proposal (`rules.is_calibrated` over `records.calibrations`). A clearer who has never passed a calibration, or whose pass has
  lapsed, is not proposed.
- The dry-run signer pool (`tm:step/dry-run`) is the people-list persons who hold the `clearer` role and are mapped to an
  instructor in that same pool, other than the candidate's own instructor. The sign-off hook checks it again on the day the
  sign-off was signed and refuses (a `dry_run_refused` check, no `dry_run` event) anyone outside it.
- A person who holds the `clearer` role in the people list but is not mapped is therefore not offered a dry-run page and cannot
  record one. The consequence for a deployment: to let someone clear, set their instructor's level to clearer, have them pass a
  calibration, and map their people-list row to that instructor.
