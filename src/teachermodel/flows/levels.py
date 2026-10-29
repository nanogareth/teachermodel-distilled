"""Level moves to and from cleared and clearer (standards/workflows/levels.yaml): the proposal, the head's decision per row and
the level changes.

    propose-levels (auto, programme)       ->  generated/levels.json (rows), or a system skip of the decision
    levels-decided (head of training)      ->  one approve page, a decision (approve or decline) per row; hook: one
                                               `level_change` per approved row that is still proposed

Spec v0.2 Users and roles: an instructor progresses lead under observation -> cleared -> clearer, and a clearer is a cleared
instructor who has passed observer calibration. A level moves only by a recorded decision, so the software proposes and the
head of training decides. The decision is not a batch page (signoff.BATCH_STEPS, where every row must be
approved): the head may decline a row and approve the others.

The rules of the proposal on the day of the run, by the instructor's latest level (the last `level_change`, else the
registration). A valid clearance is one in force on that day (`rules.clearance_valid` over records.clearances: cleared, or
cleared with conditions before its recheck, not expired, judged against the current framework major; its scope is not read):
- lead-observed -> cleared   while they hold a valid clearance;
- cleared -> clearer         while they hold a valid clearance AND rules.is_calibrated holds for them (the level alone is
                             not evidence of a clearance);
- clearer -> cleared         when a calibration they passed has lapsed and no current one remains;
- cleared -> lead-observed   when a clearance they held (cleared or conditional at some time) is on record and no valid
                             one remains.
The two demotions need evidence on record that has lapsed: a level the roster registered, with nothing in the log, is not
demoted. A demotion is a proposal like any other; the head may decline it.

The hook recomputes the proposal at the time of the sign-off and skips an approved row that is no longer proposed (its
basis lapsed or the instructor moved meanwhile).
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from .. import events, records, rules, signoff
from ..workflow import PROGRAMME, SYSTEM_ACTOR
from . import auto_step, content_check, on_signoff, register
from ..util import write_if_changed
from .common import PageProblem, State, generated, latest_level, per_signer

STEP_PROPOSE = "tm:step/propose-levels"
STEP_DECIDE = "tm:step/levels-decided"
OUTPUT = "generated/levels.json"
DECISIONS = ("approve", "decline")
_HELD = ("cleared", "cleared_with_conditions", "expired", "revoked")  # outcomes that show a clearance was once in force


def level_change_id(signoff_id: str, instructor: str) -> str:
    """Deterministic id of the level change an approved row causes: a replay cannot add a second one."""
    return signoff.input_sha256({"level_change_for_row": [signoff_id, instructor]})[:32]


def field_name(instructor: str) -> str:
    """The page field that holds the head's decision on the instructor's row."""
    return "decide-" + instructor.split("/", 1)[1]


def _valid_clearance(cleared: list[rules.Clearance], uri: str, on: date, rules_doc) -> rules.Clearance | None:
    """The instructor's longest-lasting clearance in force on `on`, whatever its scope (`rules.clearance_valid`; integration
    review finding 8: a partner's scoped clearance is a clearance)."""
    found = [c for c in cleared if c.instructor == uri and rules.clearance_valid(c, on, rules_doc)]
    return max(found, key=lambda c: (c.expires, c.id)) if found else None


def _ever_held(cleared: list[rules.Clearance], uri: str) -> bool:
    """A clearance of theirs was in force at some time: its outcome says so, or it is a lapsed conditional clearance."""
    return any(c.instructor == uri and (c.outcome in _HELD or (c.outcome == "not_yet" and c.recheck is not None))
               for c in cleared)


def proposals(st: State, on: date) -> list[dict[str, Any]]:
    """The rows for `on`: {key (the instructor), summary, changed, from, to, basis}, sorted by instructor."""
    rules_doc = st.standards["rules"]
    cleared = records.clearances(st.events)
    passed, referred = records.calibrations(st.events), records.lapses(st.events)
    rows = []
    for uri in sorted(st.registrations):
        level = latest_level(st.registrations.get(uri), st.events, uri)
        held = _valid_clearance(cleared, uri, on, rules_doc)
        calibrated = rules.is_calibrated(uri, on, passed, rules_doc, referred.get(uri))
        to = basis = None
        if level == "lead-observed" and held is not None:
            to, basis = "cleared", f"clearance {held.id} ({held.unit}, {', '.join(held.modes)}) until {held.expires}"
        elif level == "cleared" and held is not None and calibrated:
            last = max(p for p in passed[uri] if p <= on)
            to, basis = "clearer", (f"clearance {held.id} ({held.unit}) until {held.expires}; observer calibration passed "
                                    f"on {last}")
        elif level == "cleared" and held is None and _ever_held(cleared, uri):
            to, basis = "lead-observed", f"no valid clearance remains on {on}"
        elif level == "clearer" and not calibrated and passed.get(uri):
            last = max(passed[uri])
            referral = max((d for d in referred.get(uri, ()) if last <= d <= on), default=None)
            to, basis = "cleared", (f"observer calibration passed on {last} lapsed by an audit referral on {referral}"
                                    if referral else f"observer calibration passed on {last} has lapsed by {on}")
        if to:
            rows.append({"key": uri, "summary": f"{uri}: level {level} to {to}; {basis}", "changed": True,
                         "from": level, "to": to, "basis": basis})
    return rows


def _inputs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"rows": rows}


@auto_step(STEP_PROPOSE, refresh=True)
def propose_levels(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    """Write the rows for the day of the run and a `step` event when they differ from the latest one on record (its id
    counts the earlier proposals, so a proposal that returns to an earlier one is recorded again and the latest event
    always names the file). With no rows, also the system `step` event marked skipped that closes levels-decided for the
    empty page (workflow `skippable`)."""
    rows = proposals(st, now.date())
    data = (json.dumps({"rows": rows}, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    write_if_changed(st.private / OUTPUT, data)
    sha = hashlib.sha256(data).hexdigest()
    stamp = now.isoformat(timespec="seconds")
    earlier = [e for e in st.events
               if e["kind"] == "step" and e["subject_uri"] == PROGRAMME and e["payload"].get("step") == STEP_PROPOSE]
    out = []
    if not earlier or earlier[-1]["payload"].get("output_sha256") != sha:
        out.append(events.make_event(
            "step", PROGRAMME, SYSTEM_ACTOR, {"step": STEP_PROPOSE, "output": OUTPUT, "output_sha256": sha},
            id=signoff.input_sha256({"levels_proposed": [sha, len(earlier)]})[:32], at=stamp))
    if not rows:
        empty = signoff.input_sha256(_inputs([]))
        out.append(events.make_event(
            "step", PROGRAMME, SYSTEM_ACTOR,
            {"step": STEP_DECIDE, "skipped": True, "reason": "no level move to decide", "input_sha256": empty},
            id=signoff.input_sha256({"levels_skipped": empty})[:32], at=stamp))
    return out


def _rows(st: State) -> list[dict[str, Any]]:
    text, _ = generated(st, STEP_PROPOSE)
    try:
        rows = json.loads(text)["rows"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PageProblem(f"{OUTPUT} is unreadable") from exc
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("key"), str) for r in rows):
        raise PageProblem(f"{OUTPUT} is unreadable")
    return rows


def _fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": field_name(r["key"]), "label": r.get("summary", r["key"]), "kind": "enum",
             "options": list(DECISIONS), "required": True,
             "help": "approve records the level change; decline leaves the level as it is"} for r in rows]


@register(STEP_DECIDE)
def _b_levels(st: State, subject: str):
    rows = _rows(st)
    return per_signer(st, STEP_DECIDE, subject, "approve", _inputs(rows), _fields(rows),
                      intro="A level moves only by this decision. Each row names the clearance or the calibration it "
                            "rests on, or the lapse that ends it. Approve or decline each row; an approved row records "
                            "the level change, a declined one leaves the level as it is.")


@content_check(STEP_DECIDE)
def _check_levels(st: State, document: dict[str, Any]) -> list[str]:
    """Every row the page showed needs a decision: approve or decline."""
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return ["the sign-off carries no fields"]
    try:
        rows = _rows(st)
    except PageProblem as exc:
        return [str(exc)]
    return [f"{field_name(r['key'])}: approve or decline is required" for r in rows
            if fields.get(field_name(r["key"])) not in DECISIONS]


@on_signoff(STEP_DECIDE)
def _level_changes(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """One `level_change` per row the head approved that the proposal recomputed now still holds (the same instructor,
    from and to; so the instructor is still at the row's `from` level and its basis has not lapsed). The rows come from
    the proposal as the page showed it (ingest accepted the sign-off against its hash; `st.events` holds the earlier events
    of the same receipt). The actor is the signer."""
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return [], []
    try:
        rows = _rows(st)
    except PageProblem:
        return [], []
    still = {(r["key"], r["from"], r["to"]) for r in proposals(st, now.date())}
    sid = signed["payload"]["signoff_id"]
    out = []
    for row in rows:
        uri = row["key"]
        if fields.get(field_name(uri)) != "approve" or uri not in st.registrations:
            continue
        if (uri, row.get("from"), row.get("to")) not in still:
            continue
        change = events.make_event(
            "level_change", uri, signed["actor"],
            {"from": row["from"], "to": row["to"], "basis": f"signoff {sid}; {row.get('basis', '')}".rstrip("; ")},
            id=level_change_id(sid, uri), at=now.isoformat(timespec="seconds"))
        if not events.check_event(change):
            out.append(change)
    return out, []
