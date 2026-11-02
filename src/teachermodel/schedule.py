"""The session schedule: what a calendar export lists (tm:contract/schedule@1, decision 0027).

    teachermodel import-schedule <file>    check an export and, when it passes, keep it as inputs/schedule.yaml

Sessions are plans, so the schedule is a private input like bookings (decision 0026), never an event: the facts of a
delivery still arrive as outcomes and observations. The role surfaces read it for sessions ahead, learners expected,
observers and the risk timeline. A refusal lists every problem at once and writes nothing. As for bookings, a store
that is not simulated reads a schedule only once standards/retention.yaml has an entry for `schedule-records`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from . import units
from .roster import _StringDates  # dates stay ISO strings, so they validate as the schema's strings
from .standards import ROOT, load_schema, load_yaml

SCHEDULE = Path("inputs") / "schedule.yaml"
CATEGORY = "schedule-records"


class ScheduleError(Exception):
    pass


@dataclass(frozen=True)
class Session:
    ref: str
    programme: str
    unit: str
    lab: str | None
    mode: str
    start: date
    end: date
    region: str
    lead: str
    co: tuple[str, ...]
    observer: str | None
    expected_learners: int
    status: str

    @property
    def people(self) -> tuple[str, ...]:
        """Everyone the session names: lead, co-instructors and observer."""
        return (self.lead, *self.co, *((self.observer,) if self.observer else ()))


@dataclass(frozen=True)
class Schedule:
    exported_at: str
    sessions: tuple[Session, ...]


def gate(settings: Mapping[str, Any], root: Path = ROOT) -> str | None:
    """Why a schedule may not be read in this store, or None (as for bookings, decision 0026)."""
    if settings.get("simulated") is True:
        return None
    retention = load_yaml(root / "standards" / "retention.yaml") or {}
    if any(e.get("category") == CATEGORY for e in retention.get("entries") or []):
        return None
    return (f"a schedule says where people will be: standards/retention.yaml needs an entry for the {CATEGORY} "
            "category before it is read (decision 0027)")


def problems(doc: Any, root: Path = ROOT) -> list[str]:
    """Every problem with an export, schema first, then each session in order; [] when it is good."""
    errors = sorted(Draft202012Validator(load_schema("schedule.schema.json", root)).iter_errors(doc),
                    key=lambda e: [str(p) for p in e.absolute_path])
    out = [f"{'/'.join(str(p) for p in e.absolute_path) or 'the file'}: {e.message}" for e in errors]
    if not isinstance(doc, dict) or not isinstance(doc.get("sessions"), list):
        return out or ["the file: needs sessions"]
    refs = [s.get("ref") for s in doc["sessions"] if isinstance(s, dict)]
    seen: set[str] = set()
    for s in doc["sessions"]:
        if not isinstance(s, dict):
            continue
        ref = s.get("ref")
        try:
            if date.fromisoformat(s["to"]) < date.fromisoformat(s["from"]):
                out.append(f"{ref}: ends before it starts")
        except (KeyError, TypeError, ValueError):
            pass  # the schema error says why
        if refs.count(ref) > 1 and ref not in seen:
            out.append(f"{ref}: the ref is used more than once")
            seen.add(ref)
        try:
            units.load(s.get("unit"), root)
        except units.UnitError:
            out.append(f"{ref}: unknown unit {s.get('unit')} (expected standards/units/)")
    return out


def _read(path: Path) -> Any:
    """An export as written: YAML or JSON, with unquoted dates kept as strings."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_StringDates)


def _sessions(doc: dict[str, Any]) -> tuple[Session, ...]:
    return tuple(Session(s["ref"], s["programme"], s["unit"], s.get("lab"), s["mode"], date.fromisoformat(s["from"]),
                         date.fromisoformat(s["to"]), s["region"], s["lead"], tuple(s.get("co") or ()),
                         s.get("observer"), s["expected_learners"], s["status"]) for s in doc["sessions"])


def load(private: Path, settings: Mapping[str, Any], root: Path = ROOT) -> Schedule | None:
    """The store's schedule, or None when there is none. Raises ScheduleError on a refused or invalid file."""
    path = Path(private) / SCHEDULE
    if not path.exists():
        return None
    if reason := gate(settings, root):
        raise ScheduleError(reason)
    doc = _read(path)
    if found := problems(doc, root):
        raise ScheduleError(f"{SCHEDULE.as_posix()}: " + "; ".join(found))
    return Schedule(str(doc["exported_at"]), _sessions(doc))


def import_schedule(private: Path, source: Path, settings: Mapping[str, Any], root: Path = ROOT) -> Schedule:
    """Check an export and keep it as inputs/schedule.yaml. Raises ScheduleError listing every problem; writes nothing
    then."""
    if reason := gate(settings, root):
        raise ScheduleError(reason)
    doc = _read(Path(source))
    if found := problems(doc, root):
        raise ScheduleError("\n".join(found))
    target = Path(private) / SCHEDULE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return Schedule(str(doc["exported_at"]), _sessions(doc))
