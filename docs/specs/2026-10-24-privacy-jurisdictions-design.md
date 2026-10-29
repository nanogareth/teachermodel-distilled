# Privacy by jurisdiction: design

Status: draft for review, 2026-10-24. It extends `2026-10-24-workflow-automation-design.md` (§7
setup) and builds on decisions 0003, 0005 and 0006. Owner answers of 2026-10-24:
- "the learner" means the instructors, who are the learners in train-the-trainer;
- 0005 option 1 is accepted;
- the first jurisdictions are Ireland/EU and California;
- internal legal verifies the profiles.

## 1. Goal

Each instructor gets a notice that explains every piece of data held about them: what it is, why
it is held, on what legal basis, for how long, and why that long. The rules that decide those
answers depend on where the instructor works, so they live in verified data files, one per
jurisdiction. The workflow opens the right steps on its own when a new jurisdiction appears.

## 2. Decisions

- **Base plus overlay.** The organisation is established in Ireland, so GDPR and the Irish Data Protection
  Act 2018 apply to all of its processing, wherever the instructor works. The Irish profile is the
  **base** and covers everyone. Each instructor's own jurisdiction adds an **overlay** with extra
  duties (California: CCPA as amended by CPRA). Where both apply, the stricter rule holds; for
  retention that is the shorter maximum and the longer minimum.
- **Profiles are data, verified by legal.** `standards/privacy/jurisdictions/<code>.yaml`
  (`tm:contract/jurisdiction@1`). Every rule cites a dated source. A profile counts only once
  internal legal has signed the exact file bytes on a generated review page. Changing the file
  reopens that sign-off.
- **Drafting.** A research agent may draft a profile from primary sources as preparation, which the
  spec allows. The draft is labelled AI-assisted and is never used before legal verifies it. No
  model ever decides anything about an instructor.
- **Retention per data category and purpose.** Each entry has a period, the event that starts it,
  a plain-language reason, the legal basis, and an optional jurisdiction. `validate` fails if any
  category-and-purpose pair a workflow uses has no entry.
- **Consent only where it is valid.** Instructors are employees or contractors. EU guidance (EDPB
  Guidelines 05/2020 on consent) says consent is rarely freely given at work. So:
  - each profile lists the lawful bases allowed for each purpose;
  - where a purpose rests on consent (an optional use, such as reusing a recording in teaching
    material), the instructor opts in or out on their own page and can withdraw at any time;
  - everything else rests on contract or legitimate interest, and the notice explains it in full.

  Legal confirms the basis per purpose when verifying the profile.
- **Sign-offs bound to their inputs.** A step may declare `done_when.bind: input`. It then counts as
  complete only while the sign-off's `input_sha256` equals the hash of the current inputs. Editing
  a profile, a retention entry or the notice text reopens the approval on its own. This also closes
  the "retention changed since approval" dead end left by increment 1.
- **Cohort location.** The data subjects here are instructors, so the instructor's `jurisdiction`
  field selects the overlay. Notices for cohort learners who appear in recordings stay with the
  delivery platform (spec v0.2, Recordings) and the hub.

## 3. Data

| File | Contract | Holds |
| --- | --- | --- |
| `standards/privacy/purposes.yaml` | `purposes@1` | id, name, plain-language description, the workflows that serve it, the data categories it uses (ids from `setup.data_categories`), and per jurisdiction a proposed basis with a `reason` (legal's reasoning, never printed) and a `notice_text` (what the instructor is told, in plain language; wording that states law carries "(legal review)") |
| `standards/privacy/retention.yaml` | `retention@2` | entries `{category, purpose, jurisdiction?, period_months or until_event, starts, reason, basis}` |
| `standards/privacy/jurisdictions/<code>.yaml` | `jurisdiction@1` | see below |

A jurisdiction profile holds:
- **identity:** `id` (`tm:jurisdiction/<code>`), `codes` (ISO 3166, e.g. `IE`, `US-CA`), `role`
  (`base` or `overlay`), laws, regulator;
- **legal bases:** the bases allowed per purpose, and whether consent is valid at work;
- **notice:** mandatory notice elements, each an id with a citation;
- **retention:** limits (a maximum or minimum per category);
- **DPIA:** triggers, mapped to the screening criteria;
- **transfers:** rules;
- **rights and incidents:** rights with response deadlines, the breach-notice window;
- **record:** `sources[]` (title, url, accessed), `status` (`draft` or `verified`).

`retention@1` becomes `retention@2` (breaking, decision 0010). `data_categories` gets stable ids so
that purposes and retention entries can refer to them.

## 4. Workflows

`tm:workflow/privacy-base` (programme subject) replaces setup's `dpia-screening`,
`retention-periods`, `notice-text` and `notice-text-approved`.

| Step | Type | Detail |
| --- | --- | --- |
| base-profile-verified | human (legal) | review page shows the profile, its sources and a diff from the last verified version; `bind: input` |
| ropa | auto | as today, plus purposes and per-purpose bases |
| ropa-approved | human (DPO) | added 2026-10-26 on the owner's instruction (GDPR Art. 30): the DPO approves the generated ROPA as written; `bind: input` to its exact text, so filling the retention table or changing the controller reopens it; the DPIA screening needs it |
| dpia-screening | human (DPO) | pre-filled from the base profile's triggers; `bind: input` to those triggers and the hash of `purposes.yaml` (a trigger that is not one of the nine screening criterion ids stops the page) |
| retention-approved | human (head of training) | table of every category and purpose with reasons; refused while any entry is missing or breaks a profile limit; `bind: input` |
| notice-text / notice-approved | auto, then human | the base notice; rendering fails if any mandatory element of the base profile is missing or any draft marker or "(to be " placeholder remains; the approval covers the text, the base profile and the retention inputs (`bind: input`); a text never changes under a version that has been sent |

`roster-import` needs the base workflow complete: the command checks the engine's `needs` before it copies or reads the roster, and `setup.import_roster` checks the facts again (library exists, base profile verified, DPIA cleared, retention approved).

`tm:workflow/privacy-overlay` has a new subject kind, `jurisdiction`. Its subjects are the codes
found in instructor registrations other than the base.

| Step | Type | Detail |
| --- | --- | --- |
| profile-present | auto | blocked check with "no verified profile for US-CA" until the file exists |
| profile-verified | human (legal) | as for the base; `bind: input` |
| retention-check | auto | the merged retention table against the overlay's limits |
| dpia-delta | human (DPO) | only when the overlay adds a trigger the base screening did not cover |
| notice-variant / variant-approved | auto, then human | base text plus overlay elements, e.g. `2026-11-us-ca`; refused while retention is not approved; the approval covers the text, both profiles and the retention inputs (`bind: input`), and waits for the base notice approval |

Effects on existing steps:
- **Notice drafts:** each instructor gets the variant for their jurisdiction, with tag
  `[tm-notice <variant>]`.
- **notice-sent:** matches on that variant.
- **W1:** unchanged. It already waits on notice-sent, so a California instructor's W1 waits for
  the California variant.
- **New role:** `legal` joins `config.ROLES`.

## 5. Consent purposes

A purpose with `basis: consent` adds a per-instructor human step, `consent-<purpose>`. It is done on
an opt-in page signed by the instructor, offering opt in or opt out. Withdrawal is a new sign-off. A
workflow that uses a consent purpose checks for the latest opt-in, so a withdrawal stops that use
from then on.

## 6. Engine and contract changes

- `workflow.next_steps` gains:
  - the `jurisdiction` subject kind;
  - `bind: input`, with completion read through an injected `current_input` (the reader `app`
    already has);
  - `applies_to.jurisdiction`.
- Decision 0009 records the base-plus-overlay model and verification by legal. Decision 0010
  records `retention@2`.
- New contracts: `purposes@1` and `jurisdiction@1`. `workflows@1` gains `bind`, a backward-
  compatible minor change recorded in its description.

## 7. Testing

- `validate` fails on any purpose or category with no retention entry, on a retention entry that
  breaks a verified profile's limits, and on a notice template missing a mandatory element.
- **Reopen on change.** Edit a verified profile and the profile, retention and notice approvals all
  reopen.
- **E2E.** The fictional run adds a California instructor. Their W1 opens only after the
  `us-ca` variant is approved and sent, while an Irish instructor proceeds on the base notice.
- **Profile content.** Every rule has a source with a URL and an access date. Legal verification is
  the gate; tests do not judge legal correctness.

## 8. Increments

- **P1:** contracts, `purposes.yaml`, `retention@2`, `bind: input`, and the base workflow, with a
  fictional base profile. This needs no legal input.
- **P2:** draft the Irish and California profiles from primary sources (research agent, Opus,
  cited), plus the overlay workflow and notice variants.
- **P3:** legal verifies both profiles on the generated pages. The head of training then approves
  retention and the notices.
- **Consent purposes:** only if legal confirms one is needed.

## 9. Out of scope

Deciding what the law requires (legal does that), jurisdictions beyond Ireland/EU and California,
notices for cohort learners, and the content of any legal advice.
