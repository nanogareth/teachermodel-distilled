"""`cpd` events -> one plain dict per logged activity (stream G, W9)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any


def cpd(events: Iterable[dict[str, Any]]) -> list[dict]:
    """The CPD activities on record, oldest first by `logged_on`.

    Input events: kind `cpd`, payload `cpd@1` (tm:contract/cpd@1). Every other kind is ignored.
    Output: one dict per event: the payload fields (instructor, activity_key, domains, hours, logged_on, signoff_id)
    with `logged_on` parsed to a `datetime.date`, plus `id` (the event id). The activity text is in the private store
    under `activity_key`; it is never in the dict.

    Activities logged on one day keep their order in the log. An event without the fields an activity needs is skipped,
    not guessed at.

    Consumers: the CPD plan (hours per domain gap) and the bench evidence pack.
    """
    found: list[dict] = []
    for e in events:
        if e.get("kind") != "cpd" or not isinstance(e.get("payload"), dict):
            continue
        p = e["payload"]
        try:
            logged = date.fromisoformat(p["logged_on"])
            row = {"id": e["id"], "instructor": p["instructor"], "activity_key": p["activity_key"],
                   "domains": list(p["domains"]), "hours": p["hours"], "logged_on": logged, "signoff_id": p["signoff_id"]}
        except (KeyError, TypeError, ValueError):
            continue
        found.append(row)
    return sorted(found, key=lambda c: c["logged_on"])
