"""`clearance` events -> `rules.Clearance` (stream D, W4)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .. import rules


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _scope(raw: Any) -> rules.Scope | None:
    """The payload's optional `scope` ({partner?, regions?}, W11) as a `rules.Scope`; None when absent. A scope that is
    present but unreadable is kept as a scope that covers nothing (regions ()), never as no scope: a clearance is not widened
    by a payload that cannot be read."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return rules.Scope(regions=())
    partner, regions = raw.get("partner"), raw.get("regions")
    readable = (partner is None or isinstance(partner, str)) and (
        regions is None or (isinstance(regions, list) and all(isinstance(r, str) for r in regions)))
    if not readable:
        return rules.Scope(regions=())
    return rules.Scope(partner=partner, regions=tuple(regions) if regions is not None else None)


def clearances(events: Iterable[dict[str, Any]]) -> list[rules.Clearance]:
    """The clearances on record, oldest first.

    Input events: kind `clearance`, payload `clearance@1` (tm:contract/clearance@1). `Clearance.id` is the payload's
    `clearance` URI, `outcome`, `modes`, `issued`, `expires`, `recheck` and `framework_version` come from the payload
    (dates parsed).
    Output: `rules.Clearance` (id, instructor, unit, modes, outcome, issued, expires, recheck, framework_version, scope), the
    input of `rules.staffing_check`. `scope` is the payload's optional `scope` as a `rules.Scope` (W11), None when the
    clearance is unscoped.

    The log is append-only, so a clearance is changed by a later event with the same `clearance` URI (a conditional
    clearance whose recheck was missed lapses to not_yet that way): the latest event in log order per URI wins, and an
    earlier one is superseded. Oldest first by `issued`; clearances issued on one day keep the order of their first event
    in the log. An event without the fields a `Clearance` needs is skipped, not guessed at.
    """
    latest: dict[str, rules.Clearance] = {}
    first: dict[str, int] = {}
    for n, e in enumerate(events):
        if e.get("kind") != "clearance" or not isinstance(e.get("payload"), dict):
            continue
        p = e["payload"]
        cid, issued, expires = p.get("clearance"), _day(p.get("issued")), _day(p.get("expires"))
        modes = p.get("modes")
        if not (isinstance(cid, str) and issued and expires and isinstance(modes, list)
                and all(isinstance(m, str) for m in modes) and isinstance(p.get("outcome"), str)
                and isinstance(p.get("instructor"), str) and isinstance(p.get("unit"), str)):
            continue
        first.setdefault(cid, n)
        latest[cid] = rules.Clearance(
            id=cid, instructor=p["instructor"], unit=p["unit"], modes=tuple(modes), outcome=p["outcome"],
            issued=issued, expires=expires, recheck=_day(p.get("recheck")),
            framework_version=p["framework_version"] if isinstance(p.get("framework_version"), str) else None,
            scope=_scope(p.get("scope")))
    return sorted(latest.values(), key=lambda c: (c.issued, first[c.id]))
