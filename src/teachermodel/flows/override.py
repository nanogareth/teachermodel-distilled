"""The staffing override (standards/workflows/override.yaml; spec v0.2 Rules: "Only the head of training can override a
block, and every override records a reason"; increment 3 plan section J; decision 0015).

    teachermodel request-override        ->  an `override` subject (subject@2) with attrs {instructor, unit, mode, date,
                                             request_ref, partner?, region?}; request_ref is the private-store key of the
                                             requester's note; partner and region name the occasion (decision 0018)
    override-decision (head of training) ->  approve or reject, with a reason. The hook writes a `check` event
                                             {step: tm:step/override-decision, result: granted | declined, override, decided_by,
                                             signoff_id, reason_key} on the override and keeps the reason in the private store
                                             (overrides/<hex>.decision.json); the reason never enters the log

`staffing.check` reads the approved overrides (`records.overrides`): one approved override turns a block into ok for exactly its
instructor, unit, mode and date, and nothing else. A rejected or undecided one changes nothing. An override is bound to the
block it overrode (integration review finding 5): the page shows the check's detailed block reasons (`block`), the decision
records them, and the override lifts the block only while the check gives exactly those reasons and only if no bench decision
came after it. An approval of a request the check does not block is refused, and a date before today is refused at the
request (finding 21).

One override per occasion. The URI is `tm:override/<16 hex>`, derived from (instructor, unit, mode, date, n), n counting the earlier
overrides of the same four. A request that is still open, or already approved, is not opened again (`Opened.created` is False); one
that was rejected may be asked again, as a new override. The head of training who is the instructor concerned gets no page and
cannot decide (their sign-off is refused by the content check), as for a bench review.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import events, records, staffing
from ..signoff import short_sha as _hex
from ..standards import ROOT
from ..util import slug as _slug
from ..workflow import SYSTEM_ACTOR
from . import content_check, on_signoff, register
from .common import HEAD_ROLE, is_head, PageProblem, State, people_with, spec
from .dry_run import is_candidates_instructor
from .pathway import subject_event_id

STEP_DECISION = "tm:step/override-decision"
OPENED_BY_CLI = "tm:cli/request-override"
EVENT_LOG = "events/events.jsonl"
REQUEST_DIR = "overrides"  # under the private dir: <hex>.request.json (the note) and <hex>.decision.json (the reason)
DECISIONS = ("approve", "reject")
RESULT = {"approve": "granted", "reject": "declined"}  # not "rejected": the bridge uses that for a refused sign-off
MODES = ("in-person", "remote", "hybrid")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
_UNIT = re.compile(r"^sl:unit/[a-z0-9-]+@[0-9]+\Z")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}\Z")
_PARTNER = re.compile(r"^tm:org/[a-z0-9][a-z0-9-]*\Z")  # as staffing-check@2's request
_REGION = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?\Z")


class OverrideError(Exception):
    """A command refused its input; the message says what to fix."""


@dataclass(frozen=True)
class Opened:
    override: str  # the override subject URI
    created: bool  # False when the same request was already open or approved and nothing was written


def override_uri(instructor: str, unit: str, mode: str, day: str, n: int, partner: str | None = None,
                 region: str | None = None) -> str:
    """`tm:override/<16 hex>` of the n-th override of this instructor, unit, mode, date, partner and region. A request that
    names neither partner nor region keeps the URI it had before they existed (decision 0018)."""
    occasion = [instructor, unit, mode, day, n] if partner is None and region is None \
        else [instructor, unit, mode, day, partner, region, n]
    return "tm:override/" + _hex({"override": occasion}, 16)


def request_key(override: str) -> str:
    """Where the requester's note is kept, relative to the private dir."""
    return f"{REQUEST_DIR}/{_slug(override)}.request.json"


def decision_key(override: str) -> str:
    """Where the head's reason is kept, relative to the private dir."""
    return f"{REQUEST_DIR}/{_slug(override)}.decision.json"


def _instructor_uri(raw: str) -> str:
    text = raw.strip() if isinstance(raw, str) else ""
    slug = text.split("/", 1)[1] if text.startswith("tm:instructor/") else text
    if not _SLUG.match(slug):
        raise OverrideError(f"{raw!r} is not a registered instructor (give tm:instructor/<slug> or the bare slug)")
    return f"tm:instructor/{slug}"


def request_override(
    private_dir: Path | str, *, instructor: str, unit: str, mode: str, date: str, note: str | None = None,
    partner: str | None = None, region: str | None = None, now: datetime | None = None, root: Path = ROOT,
) -> Opened:
    """Open a staffing override for a registered instructor, unit, mode and delivery date (the command `request-override`),
    for the partner and region the delivery names, if any (decision 0018: the override covers only a request that names the
    same ones). The note, if given, goes to the private store; the event holds its key. A request already open or approved
    keeps its override and nothing is written. Raises OverrideError."""
    now = now or datetime.now(timezone.utc)
    uri = _instructor_uri(instructor)
    if mode not in MODES:
        raise OverrideError(f"mode: {mode!r} is not one of {', '.join(MODES)}")
    if not isinstance(unit, str) or not _UNIT.match(unit):
        raise OverrideError(f"unit: {unit!r} is not a unit reference (sl:unit/<slug>@<version>)")
    try:
        if not (isinstance(date, str) and _DAY.match(date)):
            raise ValueError(date)
        day = _date.fromisoformat(date)
    except ValueError:
        raise OverrideError(f"date: {date!r} is not a date (YYYY-MM-DD)") from None
    if partner is not None and not (isinstance(partner, str) and _PARTNER.match(partner)):
        raise OverrideError(f"partner: {partner!r} is not a partner organisation (tm:org/<slug>)")
    if region is not None and not (isinstance(region, str) and _REGION.match(region)):
        raise OverrideError(f"region: {region!r} is not a region (ISO 3166 code such as IE or US-CA)")
    if day < now.date():  # integration review finding 21: an override is for a delivery to come
        raise OverrideError(f"date: {date} is in the past; an override is asked for a delivery today or later")
    log_path = Path(private_dir) / EVENT_LOG
    log = list(events.read(log_path)) if log_path.is_file() else []
    if uri not in {e["subject_uri"] for e in log if e["kind"] == "registration"}:
        raise OverrideError(f"{uri} is not a registered instructor")
    mine = [o for o in records.overrides(log)
            if (o["instructor"], o["unit"], o["mode"], o["date"].isoformat(), o["partner"], o["region"])
            == (uri, unit, mode, date, partner, region)]
    standing = [o for o in mine if o["decision"] in (None, "approved")]
    if standing:
        return Opened(standing[-1]["override"], False)
    new = override_uri(uri, unit, mode, date, len(mine) + 1, partner, region)
    key = request_key(new)
    target = Path(private_dir) / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps({"override": new, "note": note, "requested_on": now.date().isoformat()},
                                   indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    event = events.make_event(
        "subject", new, SYSTEM_ACTOR,
        {"subject_kind": "override", "opened_by": OPENED_BY_CLI,
         "attrs": {"instructor": uri, "unit": unit, "mode": mode, "date": date, "request_ref": key,
                   **{k: v for k, v in (("partner", partner), ("region", region)) if v is not None}}},
        id=subject_event_id(new), at=now.isoformat(timespec="seconds"))
    problems = events.check_event(event)
    if problems:
        raise OverrideError("the request does not fit subject@2: " + "; ".join(problems))
    events.append(log_path, event)
    return Opened(new, True)


# --- override-decision -------------------------------------------------------------------------------------------


def _override(st: State, subject: str) -> dict[str, Any]:
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "override":
        raise PageProblem(f"{subject} is not a staffing override")
    return info


def block(st: State, info: dict[str, Any]) -> list[str]:
    """The detailed reasons the staffing check blocks the override's request with now, overrides set aside (empty when it
    does not block). The page shows them and the decision records them: an approved override lifts that block only while
    the check gives exactly these reasons (decision 0015, integration review finding 5)."""
    try:
        on = _date.fromisoformat(info["date"])
    except (TypeError, ValueError):
        raise PageProblem(f"the override's date {info.get('date')!r} cannot be read") from None
    return staffing.block_reasons(st.events, info["instructor"], info["unit"], info["mode"], on, st.standards["rules"],
                                  partner=info.get("partner"), region=info.get("region"))


def _occasion(info: dict[str, Any]) -> dict[str, str]:
    """The partner and region the request names, in that order; empty when it names neither (its page inputs then stay as
    they were before decision 0018)."""
    return {k: info[k] for k in ("partner", "region") if info.get(k) is not None}


def _inputs(st: State, override: str, info: dict[str, Any]) -> dict[str, Any]:
    return {"override": override, "instructor": info["instructor"], "unit": info["unit"], "mode": info["mode"],
            "date": info["date"], "request_ref": info["request_ref"], **_occasion(info), "block": block(st, info)}


@register(STEP_DECISION)
def _b_decision(st: State, override: str):
    info = _override(st, override)
    heads = [r["person"] for r in people_with(st, HEAD_ROLE) if not is_candidates_instructor(st, r["person"], info["instructor"])]
    if not heads:
        raise PageProblem(f"{override}: no head of training other than the instructor can decide it")
    inputs = _inputs(st, override, info)
    fields = [
        {"name": "decision", "label": "Decision", "kind": "enum", "options": list(DECISIONS), "required": True,
         "help": "Approve to let this instructor deliver this unit in this mode on this date although the staffing check "
                 "blocks it. Reject to leave the block as it is. Nothing else changes either way."},
        {"name": "reason", "label": "Reason (private)", "kind": "textarea", "required": True,
         "help": "Why you decided this. It stays in the private store; the log holds a key."},
    ]
    where = "".join(f", {k} {v}" for k, v in _occasion(info).items())
    intro = (f"Decide this staffing override for {info['instructor']}: {info['unit']}, {info['mode']}, {info['date']}{where}. The "
             f"requester's note, if any, is in the private store at {info['request_ref']}. Only you can override a block, and "
             "every override records a reason (spec, Rules). The override covers exactly this instructor, unit, mode and date "
             "(and the partner and region named here; a delivery that names other ones, or none, is not covered), "
             "and only the block shown below: if the reasons for the block change, or a bench decision follows, it lifts "
             "nothing.")
    return [spec(st, STEP_DECISION, override, h, "approve", inputs, fields, intro) for h in heads]


@content_check(STEP_DECISION)
def _check_decision(st: State, document: dict[str, Any]) -> list[str]:
    """The head of training (a people-list person holding the role), never the instructor the override is for, with a
    decision of `approve` or `reject` and a written reason."""
    info = st.subjects.get(document.get("subject_uri"))
    if info is None or info.get("kind") != "override":
        return ["the subject is not an override"]
    signer = document.get("signer")
    reasons: list[str] = []
    if not is_head(st, signer):
        reasons.append("the signer is not the head of training")
    if is_candidates_instructor(st, signer, info["instructor"]):
        reasons.append("the signer is the instructor the override is for")
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return reasons + ["the sign-off carries no fields"]
    if fields.get("decision") not in DECISIONS:
        reasons.append(f"decision: one of {', '.join(DECISIONS)} is required")
    if not isinstance(fields.get("reason"), str) or not fields["reason"].strip():
        reasons.append("reason: a written reason is required")
    if fields.get("decision") == "approve":
        try:
            if not block(st, info):
                reasons.append("the staffing check does not block this request; there is nothing to override")
        except PageProblem as exc:
            reasons.append(str(exc))
    return reasons


@on_signoff(STEP_DECISION)
def _record_decision(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """The `check` event of the decision and the private document that holds the reason. Nothing for a sign-off the content
    check would have refused."""
    override = signed["subject_uri"]
    if _check_decision(st, document):
        return [], []
    fields, sid = document["fields"], signed["payload"]["signoff_id"]
    key = decision_key(override)
    event = events.make_event(
        "check", override, signed["actor"],
        {"step": STEP_DECISION, "result": RESULT[fields["decision"]], "override": override, "decided_by": signed["actor"],
         "signoff_id": sid, "reason_key": key, "block": block(st, st.subjects[override])},
        id=_hex({"override_decision": [override, sid]}), at=now.isoformat(timespec="seconds"))
    private = {"override": override, "decision": fields["decision"], "reason": fields["reason"].strip(), "signoff_id": sid,
               "decided_by": signed["actor"]}
    return [event], [(key, private)]
