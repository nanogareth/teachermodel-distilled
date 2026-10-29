---
status: accepted
date: 2026-10-24
supersedes: null
---
# 0009 Privacy by jurisdiction: base plus overlay, profiles verified by internal legal

## Context
Instructors work in several jurisdictions (the roster already records each one), and the rules on
notice, lawful basis, retention and rights differ between them. The organisation is established in
Ireland, so GDPR and the Irish Data Protection Act 2018 apply to all of its processing wherever the
instructor works. Some jurisdictions add duties on top (California: CCPA as amended by CPRA). The
spec (`docs/specs/2026-10-24-privacy-jurisdictions-design.md`, §2) also asks how consent fits when
the data subjects are employees and contractors.

## Options
1. One generic notice and one retention table for everyone. Cheapest, and wrong wherever a local
   rule is stricter.
2. A full, separate rule set per jurisdiction. Duplicates the Irish rules that apply everywhere and
   drifts.
3. A base profile that covers everyone plus an overlay per instructor jurisdiction, where the
   stricter rule holds. Each profile is a data file that internal legal verifies.

## Decision
Option 3 (owner approved the spec, 2026-10-24).
- **Base plus overlay.** The Irish profile is the base. An overlay adds the duties of an
  instructor's own jurisdiction. Where both apply, the stricter rule holds: for retention, the
  shorter maximum and the longer minimum.
- **Profiles are data** (`tm:contract/jurisdiction@1`, one file per jurisdiction). Every rule cites
  a dated source. A profile counts only once internal legal (role `legal`) has signed the exact
  file bytes on a generated review page. Changing the file reopens that sign-off, through
  `done_when.bind: input` in the workflow definitions.
- **Drafting.** A research agent may draft a profile from primary sources as preparation, which the
  spec allows. The draft is labelled `drafted_by: ai-assisted`, stays `status: draft` and is never
  used before legal verifies it. No model decides anything about an instructor.
- **Consent only where it is valid.** EDPB Guidelines 05/2020 on consent say consent is rarely
  freely given at work. Each profile lists the lawful bases allowed per purpose and whether consent
  is valid in employment (`consent_valid_in_employment`). A purpose rests on consent only where the
  profile allows it and legal confirms it; everything else rests on contract or legitimate
  interest, and the notice explains the basis in full. Where a purpose does rest on consent, the
  instructor can opt in or out on their own page and withdraw at any time.
- **Cohort learners.** The data subjects here are instructors. Notices for cohort learners who
  appear in recordings stay with the delivery platform and the hub.

## Consequences
- New role `legal` in `config.ROLES` and the workflows schema; it sees the privacy profiles and
  the record of processing, not instructor records.
- New subject kind `jurisdiction` in the workflow engine: one subject per registration
  jurisdiction that the base profile does not cover. `applies_to.jurisdiction` filters steps by
  the instructor's registration jurisdiction.
- `workflows@1` gains the optional `done_when.bind` and the `jurisdiction` subject and filter. These
  are backward-compatible (existing files validate unchanged), so the contract stays at @1 and
  records the change in its descriptions.
- New contracts `jurisdiction@1` and `purposes@1`. Retention per category and purpose is decision
  0010.
- Deciding what the law requires is for legal; tests check the shape and the cited sources of a
  profile, not its legal correctness.
- Jurisdictions beyond Ireland/EU and California are out of scope until the owner asks.
