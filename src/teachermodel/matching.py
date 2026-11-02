"""`teachermodel staffing-match`: who may teach this unit, in this mode, on these dates, and who is free (decision 0026).

    staffing-match --unit <sl:unit/..> --mode <mode> --from <YYYY-MM-DD> --to <YYYY-MM-DD> [--region IE] [--partner tm:org/..]
                   [--all]

The staffing check asked the other way round. For every active registered instructor: the verdict over the programme's
working days (the worst day counts: `staffing.detailed`, every reason in full, since this is the head of training's view),
the clearance's expiry, their regions, the bookings that overlap the programme, and their travel load. Blocked instructors
are left out unless --all. Sorted: ok before warn, free before booked, lighter travel first.

Travel load is the share of working days in a window of `staffing.travel_window_days` centred on the programme that the
instructor would spend travelling: the days of their bookings marked as travel, plus the programme's own days when it is
in person or hybrid and in a region the instructor is not registered in. Above `staffing.travel_flag_share` it is flagged.
Both are operational defaults (decision 0026).

Bookings come from inputs/bookings.yaml in the private store (tm:contract/bookings@2; @1, without an export date, is
still read). They say where people will be, so a store that is not simulated refuses to read them until
standards/retention.yaml has an entry for the `booking-records` category (decision 0026); without them the view still
answers who may teach, and says it has no bookings.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from . import app, records, staffing
from .standards import ROOT, load_schema, load_yaml
from .util import esc, write_if_changed

BOOKINGS = Path("inputs") / "bookings.yaml"
CURRENT = "tm:contract/bookings@2"  # @2 adds exported_at (decision 0028); @1 files are still read
SCHEMAS = {CURRENT: "bookings.schema.json", "tm:contract/bookings@1": "v1/bookings.schema.json"}
VIEW = Path("views") / "staffing-match.html"
CATEGORY = "booking-records"
ORDER = {"ok": 0, "warn": 1, "block": 2}
COVERED = ("cleared", "cleared_with_conditions")


class MatchError(Exception):
    pass


@dataclass(frozen=True)
class Booking:
    instructor: str
    ref: str
    start: date
    end: date
    region: str
    travel: bool


@dataclass
class Row:
    instructor: str
    verdict: str
    reasons: list[str]
    regions: list[str]
    expires: date | None
    booked: list[str] = field(default_factory=list)
    travel_days: int = 0
    window_days: int = 0
    travel_share: float = 0.0
    travel_flag: bool = False


# --- bookings ------------------------------------------------------------------------------------------------------


def gate(settings: Mapping[str, Any], root: Path = ROOT) -> str | None:
    """Why bookings may not be read in this store, or None: as for auditions (decision 0025), a simulated store may."""
    if settings.get("simulated") is True:
        return None
    retention = load_yaml(root / "standards" / "retention.yaml") or {}
    if any(e.get("category") == CATEGORY for e in retention.get("entries") or []):
        return None
    return (f"bookings say where people will be: standards/retention.yaml needs an entry for the {CATEGORY} category "
            "before they are read (decision 0026)")


def load_bookings(private: Path, settings: Mapping[str, Any], root: Path = ROOT) -> list[Booking] | None:
    """The store's bookings, or None when there is no bookings file. Raises MatchError on a refused or invalid file."""
    path = private / BOOKINGS
    if not path.exists():
        return None
    if reason := gate(settings, root):
        raise MatchError(reason)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    version = SCHEMAS.get(doc.get("schema") if isinstance(doc, dict) else None, SCHEMAS[CURRENT])
    errors = sorted(Draft202012Validator(load_schema(version, root)).iter_errors(doc), key=str)
    if errors:
        where = "/".join(str(p) for p in errors[0].absolute_path) or "the file"
        contract = doc["schema"] if version != SCHEMAS[CURRENT] else CURRENT
        raise MatchError(f"{BOOKINGS.as_posix()}: {where} does not fit {contract} ({len(errors)} problem(s))")
    out = []
    for b in doc["bookings"]:
        start, end = date.fromisoformat(b["from"]), date.fromisoformat(b["to"])
        if end < start:
            raise MatchError(f"{BOOKINGS.as_posix()}: booking {b['ref']} ends before it starts")
        out.append(Booking(b["instructor"], b["ref"], start, end, b["region"], b["travel"]))
    return out


# --- pure ----------------------------------------------------------------------------------------------------------


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(n) for n in range((end - start).days + 1)]


def working(ds: Iterable[date]) -> set[date]:
    return {d for d in ds if d.weekday() < 5}


def window(start: date, end: date, width: int) -> tuple[date, date]:
    """`width` days centred on the programme (the middle of start..end)."""
    middle = start + (end - start) / 2
    first = middle - timedelta(days=width // 2)
    return first, first + timedelta(days=width - 1)


def travel_load(bookings: Iterable[Booking], programme: set[date], away: bool, span: tuple[date, date],
                share: float) -> tuple[int, int, float, bool]:
    """(travel days, working days, share, flagged) in the window `span`: the working days of travel bookings, with the
    programme's days when the programme itself is away. A day counts once however many bookings cover it."""
    in_window = working(days(*span))
    travel = {d for b in bookings if b.travel for d in days(b.start, b.end)} | (programme if away else set())
    travel_days = len(travel & in_window)
    total = len(in_window)
    ratio = round(travel_days / total, 2) if total else 0.0
    return travel_days, total, ratio, ratio > share


def match(log: list[dict[str, Any]], registrations: Mapping[str, Mapping[str, Any]], bookings: list[Booking] | None,
          request: Mapping[str, Any], rules_doc: Mapping[str, Any], *, include_blocked: bool = False) -> list[Row]:
    unit, mode = request["unit"], request["mode"]
    start, end = request["start"], request["end"]
    region, partner = request.get("region"), request.get("partner")
    programme = working(days(start, end)) or set(days(start, end))
    rules_staffing = rules_doc["staffing"]
    span = window(start, end, rules_staffing["travel_window_days"])
    clearances = records.clearances(log)
    rows = []
    for uri, reg in sorted(registrations.items()):
        if (reg.get("engagement") or {}).get("status", "active") != "active":
            continue
        verdicts = [staffing.detailed(log, uri, unit, mode, d, rules_doc, partner=partner, region=region)
                    for d in sorted(programme)]
        worst = max(verdicts, key=lambda v: ORDER[v["verdict"]])
        if worst["verdict"] == "block" and not include_blocked:
            continue
        mine = [b for b in bookings or [] if b.instructor == uri]
        regions = list(reg.get("regions") or [])
        away = mode != "remote" and region is not None and region not in regions
        travel_days, total, ratio, flag = travel_load(mine, programme, away, span, rules_staffing["travel_flag_share"])
        held = [c for c in clearances if c.instructor == uri and c.unit == unit and mode in c.modes
                and c.outcome in COVERED and c.issued <= start]
        rows.append(Row(uri, worst["verdict"], list(worst["reasons"]), regions,
                        max((c.expires for c in held), default=None),
                        [b.ref for b in mine if b.start <= end and b.end >= start],
                        travel_days, total, ratio, flag))
    return sorted(rows, key=lambda r: (ORDER[r.verdict], bool(r.booked), r.travel_share, r.instructor))


# --- the view and the command --------------------------------------------------------------------------------------


def page(rows: list[Row], request: Mapping[str, Any], rules_doc: Mapping[str, Any], has_bookings: bool) -> str:
    from .views import _page, _slug, _table

    s = rules_doc["staffing"]
    where = ", ".join(x for x in (request.get("region"), request.get("partner")) if x) or "any region"
    intro = (f"<p>{esc(_slug(request['unit']))}, {esc(request['mode'])}, {esc(request['start'])} to {esc(request['end'])}, "
             f"{esc(where)}. The worst working day decides the verdict. Travel load is over {s['travel_window_days']} days "
             f"centred on the programme and is flagged above {s['travel_flag_share']:.0%} (operational defaults, decision "
             "0026).</p>" + ("" if has_bookings else '<p class="muted">No bookings file: nobody shows as booked, and '
                                                   "travel counts only this programme.</p>"))
    table = _table(
        ["Instructor", "Verdict", "Reasons", "Regions", "Clearance expires", "Booked those dates", "Travel load"],
        [[esc(_slug(r.instructor)), esc(r.verdict), esc("; ".join(r.reasons)), esc(", ".join(r.regions)),
          esc(r.expires or ""), esc(", ".join(r.booked) or "free"),
          esc(f"{r.travel_share:.0%} ({r.travel_days} of {r.window_days} days)") + (" over" if r.travel_flag else "")]
         for r in rows],
        ["bad" if r.verdict == "block" else "flag" if r.verdict == "warn" or r.booked or r.travel_flag else "ok"
         for r in rows]) if rows else '<p class="muted">Nobody may teach it on these dates.</p>'
    return _page("Staffing match", intro + table, str(request["start"]))


def staffing_match(private: Path, request: Mapping[str, Any], *, include_blocked: bool = False,
                   root: Path = ROOT) -> tuple[list[Row], Path]:
    if request["mode"] not in ("in-person", "remote", "hybrid"):
        raise MatchError("mode must be in-person, remote or hybrid")
    if request["end"] < request["start"]:
        raise MatchError("--to is before --from")
    st = app.load_state(private, root)
    bookings = load_bookings(private, st.settings, root)
    rules_doc = st.standards["rules"]
    rows = match(st.events, st.registrations, bookings, request, rules_doc, include_blocked=include_blocked)
    write_if_changed(private / VIEW, page(rows, request, rules_doc, bookings is not None).encode("utf-8"))
    return rows, private / VIEW
