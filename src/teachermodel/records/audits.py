"""`audit` events -> one plain dict per audit (stream F, W6)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any


def audits(events: Iterable[dict[str, Any]]) -> list[dict]:
    """The audits on record, oldest first.

    Input events: kind `audit`, payload `audit@1` (tm:contract/audit@1); `at` of the event is the audit date. Every
    other kind is ignored.
    Output: one dict per audit event: the payload fields (sample, observation, observer, second_observer,
    within_one_share, exact_share, agreed, referred_to_calibration, signoff_id) plus `id` (the event id) and `at` (the
    audit date, a `datetime.date`). Oldest first; events of one day keep their order in the log.

    Consumers: `records.calibrations` (a referral lapses the first observer's calibration from `at`) and the bench
    evidence pack.
    """
    found = [{**e["payload"], "id": e["id"], "at": date.fromisoformat(e["at"][:10])} for e in events if e["kind"] == "audit"]
    return sorted(found, key=lambda a: a["at"])  # stable: one day keeps the log's order
