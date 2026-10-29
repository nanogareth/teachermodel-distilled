---
status: accepted
date: 2026-10-27
supersedes: null
---
# 0019 A holder of the role can revoke a bound approval

## Context
A step with `done_when.bind: input` is done while its newest approving sign-off covers the inputs as they are now
(decision 0009). Only a change to the inputs reopened it. A signer who learned that an approval no longer stood (legal
finding a superseded statute behind a verified profile, a DPO withdrawing a ROPA approval) had no way to withdraw it short
of someone editing a file to force the hash to move. The head of training asked on 2026-10-27 for revocation, open since
the increment-2 handover.

## Decision
1. A sign-off may carry the decision `revoke` (signoff@1, a value added within major 1). It covers the same inputs as the
   approval it withdraws and needs a written `fields.reason`, which stays in the private store like every field.
2. Only steps whose `done_when` declares `revocable: true` (workflows@1, an optional property added within major 1) can
   be revoked. Validate refuses it without `bind: input` or with a fixed `signer`. At run time a step with a sign-off hook
   or a single-decision rule is never revocable, whatever the file says: a hook has already acted on the approval (a
   clearance issued, an event written), and withdrawing the sign-off would not undo that.
3. Marked revocable: the privacy approvals (base profile verified, ROPA approved, DPIA screening, retention approved,
   notice approved, overlay profile verified, DPIA delta, notice variant approved) and the gap-list approval. Not marked:
   clearer decisions, the dry run, the second score, bench and override decisions, levels, assignments and observer
   assignments. A clearance is withdrawn through its own `revoked` outcome (spec v0.2, Domain model), not by revoking a
   decision behind it. Approved by the head of training, 2026-10-27.
4. The engine and `privacy.approved_covers` read the newest sign-off of the step that approves or revokes: the step is
   done only when that one approves and covers the current inputs. A later approval on the same inputs closes the step
   again.
5. `teachermodel revoke-page --step <id> [--subject <uri>]` writes a page (template `revoke`) for each holder of the
   step's role, only while an approval is in force. The person signs and returns it by mail as usual. Ingest accepts a
   revocation only for a revocable step whose approval is in force, from a holder of the role, once per approval.
6. The DPIA screening binds to the ROPA approval in force (`privacy.ropa_approval_sha256`); a revoked one leaves it. The
   screening's need is then open, so it is not due. Re-approving the same text restores the same binding, and the
   screening stands again.

## Consequences
- Nothing a revoked approval already released is undone: notices already sent stay sent. The notice drafts are held
  again, because their reader already refused any newest notice sign-off that does not approve.
- Editing an input is no longer the only way to reopen a bound step.
- `tests/test_revoke.py` pins the edges: approve, revoke, approve again; a revocation with no reason, of an open step,
  twice, and from someone without the role; the page; and which steps are revocable.
