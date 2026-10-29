"""`dry_run` events -> `rules.DryRun` (stream C, W3)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from .. import rules


def dry_runs(events: Iterable[dict[str, Any]], units: Mapping[str, str]) -> list[rules.DryRun]:
    """The dry runs that still count, oldest first.

    Input events: kind `dry_run`, payload `dry-run@1` (tm:contract/dry-run@1); `at` of the event is the run date.
    `units` maps a unit URI (`sl:unit/<slug>@<ver>`) to the unit's current `environment_sha256`
    (`units.environment_sha256(units.load(uri))`). A run counts only while its `environment_sha256` equals the current
    one for its unit; a run on a unit absent from `units`, or on an environment that has since changed, is left out.
    Output: `rules.DryRun` (instructor, unit, mode, passed, at).

    A run that did not pass is returned with `passed=False` (the rules decide what that means); only `passed: true` in
    the payload makes it passed. An event without the fields a `DryRun` needs is skipped, not guessed at.
    """
    found: list[rules.DryRun] = []
    for event in events:
        if event.get("kind") != "dry_run":
            continue
        p = event.get("payload")
        if not isinstance(p, dict):
            continue
        unit, instructor, mode = p.get("unit"), p.get("instructor"), p.get("mode")
        current = units.get(unit) if isinstance(unit, str) else None
        if current is None or p.get("environment_sha256") != current:
            continue
        if not (isinstance(instructor, str) and isinstance(mode, str) and isinstance(event.get("at"), str)):
            continue
        try:
            at = date.fromisoformat(event["at"][:10])
        except ValueError:
            continue
        found.append(rules.DryRun(instructor=instructor, unit=unit, mode=mode, passed=p.get("passed") is True, at=at))
    return sorted(found, key=lambda r: r.at)  # stable: runs on one day keep their log order
