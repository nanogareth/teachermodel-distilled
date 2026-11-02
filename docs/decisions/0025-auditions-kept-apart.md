---
status: accepted
date: 2026-10-29
supersedes: null
---
# 0025 Auditions are evidence for a hiring decision, kept apart from the instructor record

Amended by 0031 (2026-11-01): observers score on their own signed page, returned through the sign-off mailbox and kept with the audition; the coordinator's transcription is the paper fallback. Auditions still write nothing to the event log.

## Context
Hiring an instructor and clearing one were judged on different evidence. A candidate taught a sample session that
someone liked or did not, and months later the same person was observed on the five-domain rubric for clearance.
The roadmap's audition kit (system 4) puts the hiring judgement on the clearance evidence: a candidate teaches a
15-minute slice of a real lab, and two observers score it on the same rubric and form.

A candidate is not an instructor. Hiring is a different use of a person's data from coaching and clearance
(decision 0005 limits scores to those two). A new purpose in `purposes.yaml` reopens legal verification of every
jurisdiction profile, and no retention period is set for any category yet. Hiring decisions made by a rule are
regulated as automated decisions (GDPR Article 22; recruitment is a high-risk use under the EU AI Act).

## Decision
The owner chose each of these on 2026-10-29.

- **Kept apart.** An audition lives in `auditions/<id>/` in the private store, keyed by an opaque
  `tm:audition/<id>`. The candidate's name is only in `identities/auditions.yaml`. Nothing enters the event log, so
  the event, subject and purpose contracts do not change.
- **The same evidence.** The form is the rubric's five domains and four-point scale. Both observers must be in the
  observer pool on the audition day (a clearer by level, calibrated, not bench-blocked: `common.observer_pool`), and
  they must be two different people. Each observer's form is recorded once and cannot be replaced. The scores stay
  hidden until both forms are in: `status` shows who has scored, never what.
- **Evidence only.** `audition result` reports, per domain, each observer's score, the average, whether the two
  observers are within one point, and whether the average meets the clearance bar (`clearance.min_domain_average`,
  and `clearance.min_overall_mean` for the overall mean). It never recommends. The panel decides hired or not hired
  and records its reasons (`audition decide`). An audition cannot clear anyone: it is one short observation, and
  clearance needs two observations, one of them full and lead, and a passed dry run.
- **On hire.** Once the candidate is registered through the roster, `audition carry` links the audition to the new
  instructor (privately) and writes their starting plan to `generated/audition/<slug>.md`. The plan is seeded the
  way the CPD plan is (`cpd.seed_gaps`: the two lowest domains below 3), with the observers' notes for those domains.
- **No real auditions before retention.** A store that is not simulated refuses to open an audition until
  `standards/retention.yaml` has an entry for the `audition-records` category. That entry needs legal review: the
  lawful basis for hiring data, and how long the record of a candidate who was not hired is kept.

No new threshold: the clearance bar and the within-one agreement measure are the ones clearance and calibration
already use.

## Consequences
- The coordinator transcribes each observer's paper or form file with `audition score`; there is no signed receipt
  as there is for observations in W2. The record is evidence for a panel, and the panel's decision carries the
  reasons. Moving auditions into signed pages is possible later without changing the files' meaning.
- An audition does not count toward clearance, and its scores are not observation events. The new instructor's
  first W2 observations start their record.
- Before real use: an `audition-records` category with a purpose and a lawful basis, a retention entry, and a notice
  line for candidates.
