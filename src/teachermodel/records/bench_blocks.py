"""`bench_decision` (and `clearance`) events -> the bench decision that stops an instructor teaching (W10; decision 0015,
amended 2026-10-25 for integration review findings 2 and 3).

An exit or a return to co-teaching is a BLOCKING decision. It stops staffing until a clearance is issued after it; a later
renew or convert decision does not lift it (finding 2). Two readings:

- `latest_blocking`: the instructor's latest blocking decision decided on or before a day, whatever came after it. The
  staffing check and the clearance evidence use it: a clearance (or an observation) dated on or before its day never counts
  again for anything, even after the instructor is cleared again for some other unit.
- `blocking_decision`: the same decision, unless a clearance of the instructor issued after its day (and on or before the day
  asked about) has superseded it. The pools use it (observers, second observers, clearers, coaching and quality review): an
  instructor stays out of them until they are cleared again.

`is_exited` is `blocking_decision` whose decision is `exit`, the reading the coaching, quality and pathway steps use (an
instructor returned to co-teaching keeps being coached and observed; one who exited does not).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .bench import bench
from .clearances import clearances

BLOCKING = ("exit", "return-to-co-teaching")
IN_FORCE = ("cleared", "cleared_with_conditions")


def decisions(events: Iterable[dict[str, Any]], instructor: str) -> list[dict[str, Any]]:
    """The decisions of the instructor's bench reviews (`records.bench`: each review's latest `bench_decision` payload plus
    its `at` date), oldest first by the day decided; decisions of one day keep the order their reviews opened in."""
    found = [b["decision"] for b in bench(events) if b["instructor"] == instructor and b["decision"] is not None]
    return sorted(found, key=lambda d: d["at"])


def latest_decided(events: Iterable[dict[str, Any]], instructor: str, on: date) -> dict[str, Any] | None:
    """The instructor's latest bench decision of any kind decided on or before `on` (an override decided before it is
    ignored, finding 5); None when there is none."""
    found = [d for d in decisions(events, instructor) if d["at"] <= on]
    return found[-1] if found else None


def latest_blocking(events: Iterable[dict[str, Any]], instructor: str, on: date) -> dict[str, Any] | None:
    """The instructor's latest exit or return to co-teaching decided on or before `on`, whatever followed it."""
    found = [d for d in decisions(events, instructor) if d["at"] <= on and d.get("decision") in BLOCKING]
    return found[-1] if found else None


def blocking_decision(events: Iterable[dict[str, Any]], instructor: str, on: date) -> dict[str, Any] | None:
    """`latest_blocking`, unless a clearance of the instructor in force (cleared, or cleared with conditions) was issued after
    the day of the decision and on or before `on`: then None. A clearance issued on the day of the decision does not
    supersede it."""
    log = list(events)
    found = latest_blocking(log, instructor, on)
    if found is None:
        return None
    if any(c.instructor == instructor and c.outcome in IN_FORCE and found["at"] < c.issued <= on for c in clearances(log)):
        return None
    return found


def is_exited(events: Iterable[dict[str, Any]], instructor: str, on: date) -> bool:
    """True while the instructor's `blocking_decision` on `on` is an exit."""
    found = blocking_decision(events, instructor, on)
    return found is not None and found.get("decision") == "exit"
