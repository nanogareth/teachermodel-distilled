---
status: accepted
date: 2026-10-25
supersedes: null
---
# 0013 Observations count toward a clearance in any delivery mode

## Context
A clearance covers one unit in one delivery mode (in-person, remote or hybrid). Spec v0.2 does
not say whether an observation of an in-person delivery counts as evidence for a remote or hybrid
clearance of the same unit. The increment 2 integration review flagged the gap (#16).

## Options
1. Observations in any mode count. Only the dry run must match the mode, because the dry run
   tests the mode's environment and fallback.
2. At least one observation must be in the mode being cleared.

## Decision
Option 1 (head of training, 2026-10-25). `rules.clearance_check` counts the instructor's
observations of the unit in any mode. The dry run must match the mode.

## Consequences
- **Delivery mode:** the "Remote and inclusive delivery" rubric domain still shows how an
  instructor handles remote delivery, but a remote clearance can be issued on in-person
  observations alone.
- **Revisiting:** if quality review (W8) shows mode-specific gaps, reopen this decision with
  evidence (decision 0002).
- **Tests:** `tests/test_clearance.py` pins this behaviour, so changing it means a new decision.
