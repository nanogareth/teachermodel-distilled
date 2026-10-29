"""The auto step of the pathway workflow (standards/workflows/pathway.yaml): `open-candidates`.

It has no page builders (nothing in it is signed); the module holds its runner and the id helper.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .. import events, records, rules, signoff, units, workflow
from ..util import iso_seconds
from . import auto_step
from .common import TARGET_LEVEL, State, bench_block, current_level

STEP_OPEN_CANDIDATES = "tm:step/open-candidates"


def subject_event_id(subject_uri: str) -> str:
    """Deterministic id of the `subject` event that opens `subject_uri`: a replay cannot open it twice."""
    return signoff.input_sha256({"subject_opened": subject_uri})[:32]


def _holds_valid_clearance(cleared: list[rules.Clearance], instructor: str, unit: str, mode: str, on: date,
                           rules_doc: dict[str, Any]) -> bool:
    """A clearance of `instructor` for the unit and mode in force on `on`, whatever its scope (`rules.clearance_valid`;
    integration review finding 8: a partner's scoped clearance is a clearance)."""
    return any(c.instructor == instructor and c.unit == unit and mode in c.modes and rules.clearance_valid(c, on, rules_doc)
               for c in cleared)


def _candidate_event(candidate: str, instructor: str, unit: str, mode: str, stamp: str) -> dict[str, Any]:
    """The `subject` event that opens the candidate (instructor, unit, mode)."""
    return events.make_event(
        "subject", candidate, workflow.SYSTEM_ACTOR,
        {"subject_kind": "candidate", "attrs": {"instructor": instructor, "unit": unit, "mode": mode},
         "opened_by": STEP_OPEN_CANDIDATES},
        id=subject_event_id(candidate), at=stamp)


def _author_candidates(st: State, known: set[str], stamp: str, today: date) -> list[dict[str, Any]]:
    """W12: `subject` events for the candidates of the SME authors of each unit version (standards/units `authors`): one per
    delivery mode of the unit, for an author who is a registered instructor and holds no valid clearance for that unit and
    mode. An author is exempt from the level floor of `open_candidates`: the unit is their own, and its dry run and clearance
    (W3, W4) are what put it into the catalogue. A unit file that cannot be read is skipped here (`validate` reports it).
    `known` gains the candidates it opens."""
    cleared = records.clearances(st.events)
    rules_doc = st.standards["rules"]
    out: list[dict[str, Any]] = []
    for path in units.unit_files(st.root):
        unit_uri = "sl:unit/" + path.stem
        try:
            unit = units.load(unit_uri, st.root)
        except units.UnitError:
            continue
        for author in units.authors(unit):
            if author not in st.registrations or bench_block(st, author, today) == "exit":
                continue
            for mode in unit["delivery_modes"]:
                candidate = workflow.candidate_uri(author, unit_uri, mode)
                if candidate in known or _holds_valid_clearance(cleared, author, unit_uri, mode, today, rules_doc):
                    continue
                known.add(candidate)
                out.append(_candidate_event(candidate, author, unit_uri, mode, stamp))
    return out


@auto_step(STEP_OPEN_CANDIDATES, refresh=True)
def open_candidates(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    """`subject` events for the candidates that do not exist yet, plus a `step` event {step, opened} when something
    was opened or the step has never run.

    A candidate is one (instructor, unit, mode) from a registration's `delivers`, for an instructor whose latest level
    (the last `level_change`, else the registration's) is TARGET_LEVEL or a later one in framework.levels. An existing
    candidate (in `st.subjects`) is left alone, so the step can run again whenever its needs are met. W12: also the
    candidates of the SME authors of each unit version (`_author_candidates`)."""
    levels = st.standards["framework"]["levels"]
    floor = levels.index(TARGET_LEVEL)
    known = {uri for uri, info in st.subjects.items() if info["kind"] == "candidate"}
    stamp = iso_seconds(now)
    out: list[dict[str, Any]] = []
    for uri in sorted(st.registrations):
        level = current_level(st, uri)
        if level not in levels or levels.index(level) < floor:
            continue
        if bench_block(st, uri, now.date()) == "exit":  # decision 0015, finding 3: their pathway ended by a decision
            continue
        for delivery in st.registrations[uri].get("delivers", []):
            for mode in delivery["modes"]:
                candidate = workflow.candidate_uri(uri, delivery["unit"], mode)
                if candidate in known:
                    continue
                known.add(candidate)
                out.append(_candidate_event(candidate, uri, delivery["unit"], mode, stamp))
    out += _author_candidates(st, known, stamp, now.date())
    ran = any(e["kind"] == "step" and e["subject_uri"] == workflow.PROGRAMME
              and e["payload"].get("step") == STEP_OPEN_CANDIDATES for e in st.events)
    if out or not ran:
        opened = sorted(e["subject_uri"] for e in out)
        out.append(events.make_event(
            "step", workflow.PROGRAMME, workflow.SYSTEM_ACTOR, {"step": STEP_OPEN_CANDIDATES, "opened": opened},
            id=signoff.input_sha256({"open_candidates": opened})[:32], at=stamp))
    return out
