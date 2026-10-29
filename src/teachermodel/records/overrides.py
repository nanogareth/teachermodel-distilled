"""`subject` (override) and `check` events -> one plain dict per staffing override (spec Rules; decision 0015)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..util import parse_day as _day

STEP_DECISION = "tm:step/override-decision"  # the step whose `check` events carry the head of training's decision
RESULTS = {"granted": "approved", "declined": "rejected"}  # the check's result -> the override's decision


def overrides(events: Iterable[dict[str, Any]]) -> list[dict]:
    """The staffing overrides on record, oldest first.

    Input events: kind `subject` with `subject_kind` "override" (subject@2, tm:contract/subject@2; it opens the request and
    carries its attrs) and kind `check` with payload `{step: tm:step/override-decision, result: granted | declined,
    override: <uri>, decided_by, signoff_id, reason_key, block: [reasons]}` (written by the sign-off hook of the decision).
    Every other kind is ignored.
    Output: one dict per override: `override` (URI), `instructor`, `unit`, `mode`, `date` (the delivery date, a
    `datetime.date`), `request_ref` (the private key of the requester's note), `partner` and `region` (None when the request
    named none, decision 0018), `opened` (a `date`, from the `subject` event),
    and `decision` ("approved", "rejected" or None while undecided) with `decided_by`, `decided` (a `date`) and `block` (a
    tuple of the staffing check's reasons the head decided on, or None when the decision recorded none: such an override is
    bound to nothing and lifts nothing, decision 0015, integration review finding 5).

    The first `subject` event for a URI opens it; the latest decision `check` for it decides it (the log is append-only, so a
    later decision is a correction). A decision for an override the log never opened, or one that does not name that override
    in its payload, is ignored. An override whose date or attrs cannot be read is skipped, not guessed at. Oldest first by
    `opened`; requests of one day keep their order in the log.

    The reason of the decision is not here: it stays in the private store under `reason_key`."""
    opened: dict[str, dict[str, Any]] = {}
    decided: dict[str, dict[str, Any]] = {}
    for e in events:
        p = e.get("payload")
        if not isinstance(p, dict):
            continue
        if e.get("kind") == "subject" and p.get("subject_kind") == "override" and isinstance(p.get("attrs"), dict):
            uri, attrs, opened_on = e.get("subject_uri"), p["attrs"], _day(e.get("at"))
            when = _day(attrs.get("date"))
            if (isinstance(uri, str) and uri not in opened and opened_on is not None and when is not None
                    and all(isinstance(attrs.get(k), str) for k in ("instructor", "unit", "mode", "request_ref"))
                    and all(attrs.get(k) is None or isinstance(attrs[k], str) for k in ("partner", "region"))):
                opened[uri] = {"override": uri, "instructor": attrs["instructor"], "unit": attrs["unit"],
                               "mode": attrs["mode"], "date": when, "request_ref": attrs["request_ref"],
                               "partner": attrs.get("partner"), "region": attrs.get("region"),
                               "opened": opened_on, "decision": None, "decided_by": None, "decided": None,
                               "block": None}
        elif (e.get("kind") == "check" and p.get("step") == STEP_DECISION and p.get("result") in RESULTS
              and isinstance(p.get("override"), str) and p["override"] == e.get("subject_uri")):
            block = p.get("block")
            decided[p["override"]] = {"decision": RESULTS[p["result"]], "decided_by": p.get("decided_by"),
                                      "decided": _day(e.get("at")),
                                      "block": (tuple(block) if isinstance(block, list)
                                                and all(isinstance(r, str) for r in block) else None)}
    for uri, found in decided.items():
        if uri in opened:
            opened[uri].update(found)
    return sorted(opened.values(), key=lambda o: o["opened"])  # stable: requests of one day keep their log order
