"""`observation` events -> `rules.Observation` (stream B, W2)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .. import rules


def observations(events: Iterable[dict[str, Any]]) -> list[rules.Observation]:
    """The observations on record, oldest first.

    Input events: kind `observation`, payload `observation@2` (tm:contract/observation@2); `at` of the event is the
    observation date. Every other kind is ignored. The event id becomes `Observation.id`.
    Output: `rules.Observation` (id, instructor, unit, observer, at, length, lead, scores, mode).

    Oldest first by observation date; events of one day keep their order in the log. Notes are not in the payload, so
    they are not here: `evidence_ref` names where they are kept.
    """
    found = []
    for e in events:
        if e["kind"] != "observation":
            continue
        p = e["payload"]
        found.append(rules.Observation(
            id=e["id"], instructor=p["instructor"], unit=p["unit"], observer=p["observer"],
            at=date.fromisoformat(e["at"][:10]), length=p["length"], lead=p["lead"], scores=dict(p["scores"]),
            mode=p.get("mode"), rubric_version=p.get("rubric_version"),
        ))
    return sorted(found, key=lambda o: o.at)
