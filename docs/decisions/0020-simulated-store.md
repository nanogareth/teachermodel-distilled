---
status: accepted
date: 2026-10-27
supersedes: null
---
# 0020 A simulated store for development

## Context
The owner asked on 2026-10-27 for a complete set of dummy data, end to end, that emulates real use during development.
A store that is to be used afterwards with the ordinary CLI must run on the repository's real standards, or every page
hash would disagree. On the real standards the notice templates still carry their "DRAFT for legal review" banner and
draft markers, so no notice text renders, no notice is sent and no instructor's data collection opens. The pilot store
(decision 0016) has the same block.

## Decision
1. A store may be marked `simulated: true` in settings@1 (an optional field added within major 1). Validation refuses
   it without `pilot: true`, so every rule of decision 0016 applies: generated people only, at reserved domains.
2. Only `teachermodel dev-simulate` writes such a store. Everyone in it, the owner included, is generated.
3. In a simulated store the notice text and the notice variants render although their templates still carry draft
   markers: the markers are removed and the text starts with `SIMULATED DATA: generated for development. This is not
   a privacy notice.` Every other check on the notice (mandatory elements, placeholders, approvals, retention) stays.
4. The simulator answers read plans itself, with the fixture driver, through the `allowed_drivers` keyword of
   `app.do_ingest`, as the e2e script does. The CLI's `ingest` never accepts the fixture driver.

## Consequences
- Nothing changes for a real store or for the pilot store: both stay blocked on the notice until legal has reviewed it.
- A simulated store can be ticked, inspected and exported with the ordinary CLI.
- Its notice drafts carry the simulation banner, so one sent by mistake says what it is; and its addresses are all at
  example.com, so none can be sent.
