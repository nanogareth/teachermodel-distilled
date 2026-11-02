---
status: accepted
date: 2026-10-29
supersedes: null
---
# 0026 Staffing is matched from the clearances and a private bookings file, with travel load flagged above 30%

## Context
The staffing check answers one question: may this instructor deliver this unit in this mode on this date? Staffing
another team's programme asks it the other way round: who may deliver it on these dates, who is free, and who is
already travelling too much? Trainers on a programme like this can travel 25 to 30 percent of working time (an operational
assumption), so a matching view that ignores travel would wear out the bench. teachermodel held no bookings or travel
data.

## Decision
The owner chose each of these on 2026-10-29.

- `teachermodel staffing-match --unit --mode --from --to [--region] [--partner]` runs the staffing check
  (`staffing.detailed`, every reason in full) for every active registered instructor on every working day of the
  programme. The worst day decides each instructor's verdict. Blocked instructors are left out unless `--all`. The
  result is printed and written to `views/staffing-match.html`.
- **Bookings** come from `inputs/bookings.yaml` in the private store (`tm:contract/bookings@1`): per booking the
  instructor, a programme reference (never a client or a person), the dates, the region and whether it is travel.
  A calendar or travel tool exports it. It is never an event.
- **Travel load** is the share of working days, in a window of `staffing.travel_window_days` (90) centred on the
  programme, that the instructor would spend travelling. That is the days of their travel bookings, plus the
  programme's own days when it is in person or hybrid and in a region they are not registered in. It is flagged above
  `staffing.travel_flag_share` (0.30), the top of that range. Both are **operational defaults**, not
  evidence-rated thresholds (decision 0002).
- **Bookings say where people will be.** As with auditions (decision 0025), a store that is not simulated refuses to
  read a bookings file until `standards/retention.yaml` has an entry for the `booking-records` category. Without the
  file, the view still answers who may teach and says it has no bookings.

## Consequences
- The view is for the head of training and stays in the private store. It shows the detailed reasons that the
  outbound staffing check reduces to status only (decision 0005); nothing new leaves the training function.
- Before real use: a `booking-records` data category under the staffing-check purpose, its retention entry, and the
  export from whatever calendar or travel tool is in use.
