"""`teachermodel request`: someone outside the training function asks for a programme to be staffed (decision 0034).

    teachermodel request new <file> --requester <mailbox>   the file the request page saves (or it comes by mail)
    teachermodel request propose <id> --instructor <uri>    must not be blocked on any working day of the programme
    teachermodel request confirm <id>                       checks every day again
    teachermodel request decline <id> --reason <reason>
    teachermodel request withdraw <id>
    teachermodel request status [<id>]

Each stage is a `request` event on `tm:programme-request/<id>`; nothing is rewritten. The requester's mailbox and the
programme's name in their words stay in the private document `requests/<id>.json`, so the log holds a key, never a
person. `surfaces.request_status` is what the requester sees: the stage in plain words and, once proposed, one person
and the staffing outbound words (decision 0005). They never see who else was considered or why.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from . import app, events, matching, setup, signoff, staffing, units
from .standards import ROOT, load_yaml, validate
from .util import iso_seconds

FORM = "tm:contract/programme-request@1"
CATEGORY = "programme-request-records"
DIR = "requests"
SUBJECT = "tm:programme-request/"
REPLY_WORKING_DAYS = 2  # when the requester hears back (operational default, decision 0002)
REMOTE = "remote"
OPEN = ("received", "proposed")
REASONS = {
    "no-one-cleared": "Nobody is cleared to deliver this unit in this mode on these dates.",
    "no-one-free": "Everyone cleared for this is already booked on these dates.",
    "too-soon": "These dates are too soon for us to staff.",
    "not-offered": "We are not able to offer this programme.",
}


class RequestError(Exception):
    """A request or a stage was refused; the message says what to fix."""


@dataclass(frozen=True)
class Made:
    request: str
    created: bool  # False when the same request was already in


def subject(request: str) -> str:
    return SUBJECT + request


def gate(settings: Mapping[str, Any], root: Path = ROOT) -> str | None:
    """Why a request may not be kept in this store, or None: it holds a person's mailbox (as for bookings, decision 0026)."""
    if settings.get("simulated") is True:
        return None
    retention = load_yaml(Path(root) / "standards" / "retention.yaml") or {}
    if any(e.get("category") == CATEGORY for e in retention.get("entries") or []):
        return None
    return (f"a request holds a person's mailbox: standards/retention.yaml needs an entry for the {CATEGORY} category "
            "before one is kept (decision 0034)")


def add_working_days(day: date, n: int) -> date:
    while n:
        day += timedelta(days=1)
        n -= day.weekday() < 5
    return day


def problems(doc: Any, today: date, root: Path = ROOT) -> list[str]:
    """Every problem with a request, in words the requester can act on; [] when it is good."""
    if not isinstance(doc, dict) or doc.get("schema") != FORM:
        return [f"not a programme request (schema must be {FORM})"]
    found = [f"{e.split(':', 1)[0]}: not a valid value" for e in validate(doc, "programme-request.schema.json", root)]
    if found:
        return found
    try:
        start, end = date.fromisoformat(doc["from"]), date.fromisoformat(doc["to"])
    except ValueError:
        return ["from and to must be real dates"]
    out = []
    try:
        units.load(doc["unit"], root)
    except units.UnitError:
        out.append(f"unit: {doc['unit']} is not a published unit")
    if end < start:
        out.append("to: the last day is before the first day")
    if start < today:
        out.append("from: the first day has passed")
    if doc["mode"] != REMOTE and not doc.get("region"):
        out.append(f"region: required for a {doc['mode']} programme, so travel is counted")
    return out


def request_id(doc: Mapping[str, Any], requester: str) -> str:
    """The same request from the same mailbox is one request, however often it is sent."""
    return "req-" + signoff.input_sha256({"request": dict(doc), "requester": requester.lower()})[:10]


def state(log: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per request id, what was asked and its latest stage, folded from the log in order."""
    found: dict[str, dict[str, Any]] = {}
    for e in log:
        if e["kind"] != "request":
            continue
        p = e["payload"]
        row = found.setdefault(p["request"], {"received_at": e["at"]})
        row.update(p)
        row[f"{p['stage']}_at"] = e["at"]
        if p["stage"] in ("received", "declined", "withdrawn"):
            row.pop("instructor", None)
    return found


def private_document(private: Path, request: str) -> dict[str, Any]:
    path = Path(private) / DIR / f"{request}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def new(private: Path | str, doc: Any, requester: str, now: datetime | None = None, root: Path = ROOT) -> Made:
    """Check a request, keep the private document, then append the event (the last write, so a refusal leaves no trace)."""
    now = now or datetime.now(timezone.utc)
    private = Path(private)
    if why := gate(setup.load_settings(private), root):
        raise RequestError(why)
    if not (isinstance(requester, str) and "@" in requester and " " not in requester):
        raise RequestError("requester: give the mailbox the status goes back to")
    if found := problems(doc, now.date(), root):
        raise RequestError("\n".join(found))
    rid = request_id(doc, requester)
    log = _log(private)
    if rid in state(log):
        return Made(rid, False)
    key = f"{DIR}/{rid}.json"
    target = private / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"request": rid, "requester": requester, "programme": doc.get("programme"),
                                  "received": iso_seconds(now)}, indent=1) + "\n", encoding="utf-8", newline="\n")
    _append(private, rid, "received", now,
            {"unit": doc["unit"], "mode": doc["mode"], "from": doc["from"], "to": doc["to"],
             "region": doc.get("region"), "partner": doc.get("partner"), "expected_learners": doc["expected_learners"],
             "reply_by": add_working_days(now.date(), REPLY_WORKING_DAYS).isoformat(), "requester_key": key})
    return Made(rid, True)


def _log(private: Path) -> list[dict[str, Any]]:
    path = Path(private) / app.EVENT_LOG
    return list(events.read(path)) if path.is_file() else []


def _append(private: Path, request: str, stage: str, now: datetime, extra: dict[str, Any]) -> None:
    payload = {"request": request, "stage": stage, **extra}
    events.append(Path(private) / app.EVENT_LOG, events.make_event(
        "request", subject(request), "tm:system/teachermodel", payload,
        id=signoff.input_sha256({"request_event": payload, "at": iso_seconds(now)})[:32], at=iso_seconds(now)))


def _row(private: Path, request: str) -> dict[str, Any]:
    row = state(_log(private)).get(request)
    if row is None:
        raise RequestError(f"no request {request}")
    return row


def query(row: Mapping[str, Any]) -> dict[str, Any]:
    """The request in the shape `matching.match` reads."""
    return {"unit": row["unit"], "mode": row["mode"], "start": date.fromisoformat(row["from"]),
            "end": date.fromisoformat(row["to"]), "region": row.get("region"), "partner": row.get("partner")}


def worst_verdict(st: app.State, row: Mapping[str, Any], instructor: str) -> dict[str, Any] | None:
    """The instructor's worst working day on this programme, as staffing sees it; None for someone not registered."""
    reg = {instructor: st.registrations[instructor]} if instructor in st.registrations else {}
    rows = matching.match(st.events, reg, [], query(row), st.standards["rules"], include_blocked=True)
    if not rows:
        return None
    return {"verdict": rows[0].verdict, "reasons": rows[0].reasons, "expires": rows[0].expires}


def outbound_words(verdict: Mapping[str, Any]) -> list[str]:
    """What the requester may read about the proposed person (decision 0005)."""
    return staffing.outbound({"verdict": verdict["verdict"], "reasons": verdict["reasons"]})["reasons"]


def propose(private: Path | str, request: str, instructor: str, now: datetime | None = None, root: Path = ROOT) -> str:
    """Name who is proposed. Refused when they are blocked on any working day; a warn goes through, and the requester
    sees its outbound words. An override of a block is the head of training's and shows here as ok."""
    now = now or datetime.now(timezone.utc)
    private = Path(private)
    row = _row(private, request)
    if row["stage"] not in OPEN:
        raise RequestError(f"{request} is {row['stage']}: nothing to propose")
    st = app.load_state(private, root)
    verdict = worst_verdict(st, row, instructor)
    if verdict is None:
        raise RequestError(f"{instructor} is not a registered, active instructor")
    if verdict["verdict"] == "block":
        raise RequestError(f"{instructor} may not teach this on every working day: " + "; ".join(verdict["reasons"]))
    _append(private, request, "proposed", now, {"instructor": instructor})
    return verdict["verdict"]


def confirm(private: Path | str, request: str, now: datetime | None = None, root: Path = ROOT) -> str:
    """Confirm the proposed instructor, checking every working day again: a clearance may have lapsed since."""
    now = now or datetime.now(timezone.utc)
    private = Path(private)
    row = _row(private, request)
    if row["stage"] != "proposed":
        raise RequestError(f"{request} is {row['stage']}: propose an instructor first")
    verdict = worst_verdict(app.load_state(private, root), row, row["instructor"])
    if verdict is None or verdict["verdict"] == "block":
        raise RequestError(f"{row['instructor']} may no longer teach this: "
                           + "; ".join(verdict["reasons"] if verdict else ["not registered"]))
    _append(private, request, "confirmed", now, {"instructor": row["instructor"]})
    return verdict["verdict"]


def decline(private: Path | str, request: str, reason: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    row = _row(Path(private), request)
    if reason not in REASONS:
        raise RequestError(f"reason must be one of {', '.join(REASONS)}")
    if row["stage"] not in OPEN:
        raise RequestError(f"{request} is {row['stage']}: nothing to decline")
    _append(Path(private), request, "declined", now, {"reason": reason})


def withdraw(private: Path | str, request: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    row = _row(Path(private), request)
    if row["stage"] in ("declined", "withdrawn"):
        raise RequestError(f"{request} is {row['stage']} already")
    _append(Path(private), request, "withdrawn", now, {})


def receive(private: Path | str, items: list[tuple[dict[str, Any], str]], now: datetime, root: Path = ROOT) -> list[str]:
    """Requests that came by mail: the connector vouches for the sender. One line each; a refusal is reported, not kept,
    so a problem in a request leaves nothing of the requester in the store."""
    lines = []
    for doc, sender in items:
        try:
            made = new(private, doc, sender, now, root)
        except RequestError as exc:
            lines.append(f"rejected: a programme request: {'; '.join(str(exc).splitlines())}")
            continue
        lines.append(f"request {made.request}: {'received' if made.created else 'already in'}")
    return lines
