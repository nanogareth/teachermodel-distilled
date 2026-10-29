"""`subject` (bench) and `bench_decision` events -> one plain dict per bench review (stream I, W10)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..util import parse_day as _day


def bench(events: Iterable[dict[str, Any]]) -> list[dict]:
    """The bench reviews on record, oldest first.

    Input events: kind `subject` with `subject_kind` "bench" (subject@2, tm:contract/subject@2; it opens the review and
    carries its attrs) and kind `bench_decision`, payload `bench-decision@1` (tm:contract/bench-decision@1). Every other
    kind is ignored.
    Output: one dict per bench review: `bench` (URI), `instructor`, `reason`, `opened` (a `datetime.date`, from the
    `subject` event), and `decision` (the `bench_decision` payload plus its `at` date, or None while undecided).

    The first `subject` event for a URI opens it; the latest `bench_decision` event for a review is its decision. A
    decision for a review the log never opened is ignored. Oldest first by `opened`; reviews opened on one day keep their
    order in the log.

    Consumers: the evidence pack, `open-bench` (no second open review for one instructor) and the level change that
    follows a decision. The rationale is not here: `decision["rationale_key"]` names where the private store keeps it.
    """
    opened: dict[str, dict[str, Any]] = {}
    decisions: dict[str, dict[str, Any]] = {}
    for e in events:
        p = e.get("payload")
        if not isinstance(p, dict):
            continue
        if e.get("kind") == "subject" and p.get("subject_kind") == "bench" and isinstance(p.get("attrs"), dict):
            uri, attrs, day = e.get("subject_uri"), p["attrs"], _day(e.get("at"))
            if isinstance(uri, str) and uri not in opened and day is not None:
                opened[uri] = {"bench": uri, "instructor": attrs.get("instructor"), "reason": attrs.get("reason"),
                               "opened": day, "decision": None}
        elif e.get("kind") == "bench_decision" and isinstance(p.get("bench"), str):
            day = _day(e.get("at"))
            if day is not None:
                decisions[p["bench"]] = {**p, "at": day}
    for uri, decision in decisions.items():
        if uri in opened:
            opened[uri]["decision"] = decision
    return sorted(opened.values(), key=lambda b: b["opened"])  # stable: reviews of one day keep their log order
