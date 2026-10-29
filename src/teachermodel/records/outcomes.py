"""`outcome` events -> `rules.Outcome` (stream H, W8)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .. import rules


def outcomes(events: Iterable[dict[str, Any]]) -> list[rules.Outcome]:
    """The delivery outcomes on record, oldest delivery first.

    Input events: kind `outcome`, payload `outcome@1` (tm:contract/outcome@1; event@4). Every other kind is ignored.
    Output: `rules.Outcome` (delivery, instructor, at, learners_assessed, score, baseline, feedback, feedback_median):
    `delivery` is the payload's `delivery_ref`, `at` its `delivered_on` parsed to a date. Aggregates only; no learner
    data is in the payload or in the result.

    Oldest first by `delivered_on`; the same `delivery_ref` imported twice appears once (the later event wins).
    `rules.quality_triggers` reads the list. Deliveries of one day keep the order of their first appearance in the log.
    """
    found: dict[str, rules.Outcome] = {}
    for e in events:
        if e["kind"] != "outcome":
            continue
        p = e["payload"]
        found[p["delivery_ref"]] = rules.Outcome(
            delivery=p["delivery_ref"], instructor=p["instructor"], at=date.fromisoformat(p["delivered_on"]),
            learners_assessed=p["learners_assessed"], score=p["score"], baseline=p["baseline"],
            feedback=p.get("feedback"), feedback_median=p.get("feedback_median"))
    return sorted(found.values(), key=lambda o: o.at)
