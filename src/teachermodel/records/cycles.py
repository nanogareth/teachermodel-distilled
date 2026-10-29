"""`subject` (cycle) and `coaching_cycle` events -> one plain dict per coaching cycle (stream G, W7)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

PHASES = ("opened", "feedback", "practice", "closed")  # in the order a cycle moves through them


def _day(event: dict[str, Any]) -> date:
    return date.fromisoformat(event["at"][:10])


def cycles(events: Iterable[dict[str, Any]]) -> list[dict]:
    """The coaching cycles on record, ordered by instructor then cycle number.

    Input events: kind `subject` with `subject_kind` "cycle" (subject@2, tm:contract/subject@2; it opens the cycle and
    carries its attrs) and kind `coaching_cycle`, payload `coaching-cycle@1` (tm:contract/coaching-cycle@1; one per
    completed phase). Every other kind is ignored.
    Output: one dict per cycle: `cycle` (URI), `instructor`, `coach`, `number`, `intensity`, `focus` (the CURRENT ones: the
    latest `coaching_cycle` event's, as `flows.coaching.derive_cycles` reads them, so a switch to triggered shows), `trigger` (or
    None), `phase` (the latest phase written, "opened" when only the `subject` event exists), `opened` (a `datetime.date`,
    from the `subject` event), `closed` (a date, or None until the "closed" phase), `change` (the "closed" payload's
    domain deltas, or None).

    The latest phase is the furthest along (opened, feedback, practice, closed), whatever the order of the log; a cycle
    closed twice reports the later `closed` event. A cycle with no `subject` event is read from its first phase event
    (`opened` is then that event's date); one whose attrs lack a field a cycle needs is skipped, not guessed at.

    Consumers: `rules.coaching_overdue` (the latest `closed` per instructor), the next cycle's intensity, CPD seeding and
    the bench evidence pack.
    """
    opening: dict[str, dict[str, Any]] = {}
    phases: dict[str, list[dict[str, Any]]] = {}
    for e in events:
        if e.get("kind") == "subject" and isinstance(e.get("payload"), dict) and e["payload"].get("subject_kind") == "cycle":
            opening.setdefault(e["subject_uri"], e)
        elif e.get("kind") == "coaching_cycle" and isinstance(e.get("payload"), dict) and isinstance(e["payload"].get("cycle"), str):
            phases.setdefault(e["payload"]["cycle"], []).append(e)
    found: list[dict] = []
    for uri in set(opening) | set(phases):
        first = opening.get(uri)
        attrs = first["payload"].get("attrs") if first is not None else (phases[uri][0]["payload"])
        if not isinstance(attrs, dict) or not all(k in attrs for k in ("instructor", "coach", "number", "intensity", "focus")):
            continue
        written = [e for e in phases.get(uri, []) if e["payload"].get("phase") in PHASES]
        latest = max(written, key=lambda e: PHASES.index(e["payload"]["phase"]), default=None)
        closes = [e for e in written if e["payload"]["phase"] == "closed"]
        opened_by = first if first is not None else min(phases[uri], key=_day)
        intensity, focus = attrs["intensity"], list(attrs["focus"])
        for e in phases.get(uri, []):  # a mid-cycle switch to triggered changes both; the latest in log order wins
            p = e["payload"]
            if p.get("intensity") in ("standard", "triggered"):
                intensity = p["intensity"]
            if isinstance(p.get("focus"), list) and p["focus"]:
                focus = list(p["focus"])
        found.append({
            "cycle": uri, "instructor": attrs["instructor"], "coach": attrs["coach"], "number": attrs["number"],
            "intensity": intensity, "focus": focus, "trigger": attrs.get("trigger"),
            "phase": latest["payload"]["phase"] if latest is not None else "opened",
            "opened": _day(opened_by),
            "closed": _day(closes[-1]) if closes else None,
            "change": dict(closes[-1]["payload"]["change"]) if closes and closes[-1]["payload"].get("change") else None,
        })
    return sorted(found, key=lambda c: (c["instructor"], c["number"]))
