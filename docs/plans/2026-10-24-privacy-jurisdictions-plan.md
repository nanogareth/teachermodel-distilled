# Privacy by jurisdiction (P1 and P2): implementation plan

**Goal:**
- Per-jurisdiction privacy rules as verified data.
- Retention per data category and purpose.
- Approvals that reopen when their inputs change.
- Notice versions per jurisdiction, generated without hand edits.
- The Irish base and California overlay profiles, drafted ready for legal verification.

**Spec:** `docs/specs/2026-10-24-privacy-jurisdictions-design.md`.
**Verify:** `py -m pytest`; `py scripts/e2e_fictional.py`; `PYTHONPATH=src py -m teachermodel.cli validate`.

**Conventions:**
- Commit with explicit pathspecs.
- Every check gets a test that is shown to fail before the fix.
- No names in events.
- Edit files with the Write/Edit tools, never heredocs.

**Order:** A and J5 run in parallel; then J1+J2, J3, J4; then the integration review.

## A. Enabling refactor (stream A, no behaviour change)
- [x] Workflows: `standards/workflows.yaml` becomes `standards/workflows/<slug>.yaml`, one file per
  workflow. `load_standards` merges them; step ids stay unique across files.
- [x] Page builders: the `PAGE_SPECS` builders move to `src/teachermodel/flows/<slug>.py`. Each
  module registers its own builders, and `app` collects them through a registry.
- [x] Event kinds: each workflow file declares the kinds it writes. `validate` checks that every
  `done_when.kind` is declared and is in the event@2 enum.
- [x] Packaging (carry-over 19): `standards/` and `contracts/` resolve through one
  `resources.root()` function. It keeps the editable-install path and is ready for packaged data.
- Done: the suite and the E2E script pass unchanged, and `git diff --stat` touches no test assertions.

## J5. Profile research (parallel with A; data files only)
- [x] Draft `standards/privacy/jurisdictions/ie.yaml` (base: GDPR and the Irish Data Protection Act
  2018) and `us-ca.yaml` (overlay: CCPA as amended by CPRA, CPPA regulations). Use the field list
  in spec §3.
- [x] Every rule cites a primary source (EUR-Lex, irishstatutebook.ie, dataprotection.ie,
  leginfo.legislature.ca.gov, cppa.ca.gov) with a URL and an access date. Each file is
  `status: draft`, `drafted_by: ai-assisted`, and carries a review-notes section listing every
  judgement call for legal.
- [x] Draft `standards/privacy/purposes.yaml`. Purposes come from the workflows (clearance,
  coaching, calibration and audit, quality review, staffing check, record of actions), and the data
  categories from `setup.data_categories`.
- Done: the files parse as YAML; every rule has a source; the review notes list every open question.

## J1+J2. Contracts, decisions, engine
- [x] Contracts: `jurisdiction@1`, `purposes@1` and `retention@2`. Keep v1 in `contracts/v1/`.
  Add stable category ids to `data_categories`.
- [x] Decisions: 0009 (base plus overlay, verified by legal) and 0010 (`retention@2`).
- [x] Engine:
  - `done_when.bind: input`. Completion needs the newest approving sign-off whose `input_sha256`
    equals `current_input(step, subject)`, injected into `next_steps`. App passes its existing reader.
  - New subject kind `jurisdiction`: one subject per overlay code found in registrations.
  - `applies_to.jurisdiction`.
- [x] Add the `legal` role to `config.ROLES` and the workflows role enum.
- Tests first:
  - an edited input reopens a `bind: input` step;
  - a non-bound step stays done;
  - a jurisdiction subject appears only for overlay codes;
  - an approving sign-off on old inputs does not complete the step.

## J3. privacy-base workflow
- [x] `standards/workflows/privacy-base.yaml` per spec §4. Remove the replaced setup steps;
  `roster-import` needs the base workflow complete.
- [x] Page builders:
  - the profile review page: profile, sources, and a diff from the last verified version;
  - the retention table page: refused while any entry is missing or breaks a profile limit;
  - the notice approval page.

  All are bound to their inputs.
- [x] `setup.notice_text` renders from purposes, retention, the profile's mandatory elements and the
  0005 text. It refuses when a mandatory element is missing. The template marks elements with ids.
- [x] `validate` coverage: every category-and-purpose pair has a retention entry, and every entry
  stays within the verified profile limits.
- [x] Tests use a fictional base profile under `tests/fixtures/` and never the J5 drafts.
- Done: the E2E script, rewritten for the base workflow, is green.

## J4. Overlay workflow and notice variants
- [x] `standards/workflows/privacy-overlay.yaml` per spec §4.
- [x] Notice drafts select the variant by the instructor's jurisdiction, with tag
  `[tm-notice <variant>]`. `notice-sent` matches on the variant.
- [x] E2E: add a fictional California instructor. Their W1 opens only after the `us-ca` variant
  is approved and sent. An Irish instructor proceeds on the base notice.
- [x] Wire the J5 drafts in once they validate against `jurisdiction@1`. They stay `draft`, and the
  verification pages are generated for legal.

## Integration review
One Opus reviewer over the whole diff, then fix the blockers, then push.

## Deferred
- Consent purposes (spec §5), until legal confirms one is needed.
- Jurisdictions beyond IE and US-CA.
- Increment 2 streams B to E, which follow A.
