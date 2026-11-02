"""The freshness register: when each source last reported, against how often it should (decision 0027).

standards/freshness.yaml lists the sources the role surfaces read, each with an owner, a cadence and grace, and how its
last report is read. `assess` is pure: a source is `ok`, `stale` (past cadence plus grace), `never` (no report yet) or
`not-connected` (nothing reads it yet). `status` reads the store and assesses. A stale or silent source becomes an item
on its owner's page, so silence is never shown as success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import feeds, matching, schedule
from .standards import ROOT, load_yaml

REGISTER = Path("standards") / "freshness.yaml"


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    owner: str
    every_days: int
    grace_days: int
    read: str


@dataclass(frozen=True)
class Status:
    source: Source
    last: datetime | None
    due: datetime | None
    state: str  # ok | stale | never | not-connected
    days_late: int = 0  # whole days past due, at least 1 once stale


def sources(root: Path = ROOT) -> list[Source]:
    doc = load_yaml(Path(root) / REGISTER) or {}
    return [Source(s["id"], s["title"], s["owner"], int(s["every_days"]), int(s["grace_days"]), s["read"])
            for s in doc.get("sources") or []]


def assess(found: list[Source], seen: dict[str, datetime | None], now: datetime) -> list[Status]:
    out = []
    for s in found:
        last = seen.get(s.id)
        if s.read == "not-connected":
            out.append(Status(s, None, None, "not-connected"))
        elif last is None:
            out.append(Status(s, None, None, "never"))
        else:
            due = last + timedelta(days=s.every_days + s.grace_days)
            late = now > due
            out.append(Status(s, last, due, "stale" if late else "ok", max(1, (now - due).days) if late else 0))
    return out


def _utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _daily_log(private: Path) -> datetime | None:
    path = private / "logs" / "daily.log"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return _utc(lines[-1].split(" ", 1)[0]) if lines else None


def _newest_outcome(private: Path) -> datetime | None:
    path = private / "events" / "events.jsonl"
    newest = None
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if '"kind": "outcome"' in line or '"kind":"outcome"' in line:
                    at = json.loads(line)["at"]
                    newest = at if newest is None or at > newest else newest
    return _utc(newest) if newest else None


def _schedule_export(private: Path) -> datetime | None:
    path = private / schedule.SCHEDULE
    if not path.exists():
        return None
    return _utc(str(schedule._read(path).get("exported_at")))


def _bookings_export(private: Path) -> datetime | None:
    """exported_at of a bookings@2 file; a bookings@1 file has none, so its modification time stands in."""
    path = private / matching.BOOKINGS
    if not path.exists():
        return None
    doc = schedule._read(path)
    if isinstance(doc, dict) and doc.get("exported_at"):
        return _utc(str(doc["exported_at"]))
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)


def _release_status(private: Path) -> datetime | None:
    kept = feeds.load(private, feeds.RELEASE)
    return _utc(kept["run_at"]) if kept else None


READERS: dict[str, Callable[[Path], datetime | None]] = {
    "daily-log": _daily_log, "newest-outcome": _newest_outcome, "schedule-export": _schedule_export,
    "bookings-export": _bookings_export, "release-status": _release_status,
}


def status(private: Path | str, now: datetime, root: Path = ROOT) -> list[Status]:
    """Every registered source's state in this store at `now`."""
    found = sources(root)
    seen = {s.id: READERS[s.read](Path(private)) for s in found if s.read in READERS}
    return assess(found, seen, now)
