"""`calibration` events -> the passed-calibration dates `rules.is_calibrated` reads (stream E, W5)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any


def calibrations(events: Iterable[dict[str, Any]]) -> dict[str, list[date]]:
    """Per observer, the dates of the calibrations they passed, oldest first.

    Input events: kind `calibration`, payload `calibration@1` (tm:contract/calibration@1); `at` of the event is the
    calibration date. Only `passed: true` results count. The observer key is the payload's `observer`.
    Output: the `calibrations` argument of `rules.is_calibrated` and `rules.clearance_check`
    (observer URI -> list of dates).

    Every pass is kept, audits or not. An audit referral (W6) lapses a calibration prospectively (decision 0015): the
    referral dates are `records.lapses`, which `rules.is_calibrated` takes beside these passes, so a day before the
    referral keeps its calibration and a day from it on needs a pass dated after it.
    """
    found: dict[str, set[date]] = {}
    for e in events:
        p = e["payload"]
        if e["kind"] == "calibration" and p.get("passed") is True and isinstance(p.get("observer"), str):
            found.setdefault(p["observer"], set()).add(date.fromisoformat(e["at"][:10]))
    return {o: sorted(days) for o, days in found.items()}
