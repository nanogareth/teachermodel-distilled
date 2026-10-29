"""`audit` events -> the referral dates `rules.is_calibrated` reads as calibration lapses (W6; decision 0015)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any


def lapses(events: Iterable[dict[str, Any]]) -> dict[str, list[date]]:
    """Per first observer, the dates of the audits that referred them back to calibration, oldest first.

    Input events: kind `audit`, payload `audit@1` (tm:contract/audit@1); `at` of the event is the audit date. Only
    `referred_to_calibration: true` counts. The observer key is the payload's `observer` (the first observer).
    Output: observer URI -> sorted, distinct dates; an observer never referred has no entry. Each observer's list is the
    `lapses` argument of `rules.is_calibrated` (and the dict that of `rules.clearance_check`).

    A referral is prospective (decision 0015): it makes the observer not calibrated from its date until a pass dated after
    it. The passes themselves stay in `records.calibrations`, so a day before the referral is judged as before.
    """
    found: dict[str, set[date]] = {}
    for e in events:
        p = e.get("payload")
        if e.get("kind") == "audit" and isinstance(p, dict) and p.get("referred_to_calibration") is True \
                and isinstance(p.get("observer"), str):
            found.setdefault(p["observer"], set()).add(date.fromisoformat(e["at"][:10]))
    return {o: sorted(days) for o, days in found.items()}
