"""W9 CPD (standards/workflows/cpd.yaml): the plan, the activity log, and the review of each gap at a coaching cycle's close.

    cpd-plan (auto, per instructor)   ->  generated/cpd/<slug>.json, seeded from the lowest-scoring domains of the last
                                          WINDOW_DAYS days of observations (at most GAP_COUNT, only those below TARGET)
    log-activity (the instructor)     ->  a `cpd` event per activity (cpd@1); the activity text is private (cpd/<sid>.json)
    cycle-close (flows/coaching.py)   ->  `review_plan`: each open gap is closed when its domain's latest average has reached
                                          TARGET, else kept; the review is recorded on the close's `step` event as `cpd_review: {closed, kept}`

The log is the record of a gap and its status (integration review finding 17): the `cpd-plan` `step` event carries the seeded
gaps and each cycle-close `step` event the review, and `plan_document` rebuilds the plan from them. The plan file is a copy,
rewritten by the review and never read for a decision; the hours against a gap are counted from the `cpd` events
(`records.cpd`), never stored in it. `log-activity` is `bind: input` and its inputs carry the number of activities logged, so it
opens again after each one: an instructor has an open item for as long as they are developing.

Operational defaults (decision 0002), not evidence-based thresholds: the 180-day window follows the spec's "recent observations";
TARGET is the bar a gap closes at (the lead's brief: a domain average of 3); the two-gap plan follows the two-domain focus of a
coaching cycle; a logged activity is due again LOG_WINDOW_DAYS (the standard cycle) after the last.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any

from .. import events, records, rules, signoff
from ..due import due_rule
from ..util import iso_seconds, slug
from ..workflow import SYSTEM_ACTOR
from . import auto_step, content_check, on_signoff, register
from .common import PageProblem, State, cached, observations, spec
from .dry_run import _signed_at, _signed_day
from .observation import _json_bytes, _positions, _write

STEP_PLAN = "tm:step/cpd-plan"
STEP_LOG = "tm:step/log-activity"
STEP_CLOSE = "tm:step/cycle-close"  # W7's step; its `step` event carries the review (read here by id only)

TARGET = 3                # a gap closes when the domain's latest average reaches this
WINDOW_DAYS = 180         # the observations that seed a plan
GAP_COUNT = 2             # a plan has at most this many gaps
LOG_WINDOW_DAYS = 91      # a logged activity is due again this long after the last (or the plan)
MAX_HOURS = 100           # one activity cannot claim more than this many hours
PLAN_DIR = "generated/cpd"
ACTIVITY_DIR = "cpd"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def plan_path(instructor: str) -> str:
    """Where the plan of `instructor` is kept in the private store."""
    return f"{PLAN_DIR}/{slug(instructor)}.json"


def activity_key(signoff_id: str) -> str:
    """Where the text of the activity a sign-off logged is kept in the private store."""
    return f"{ACTIVITY_DIR}/{signoff_id}.json"


def domain_order(st: State) -> list[str]:
    return [d["id"] for d in st.standards["framework"]["domains"]]


# --- pure: averages and gaps -------------------------------------------------------------------------------------


def _mean_scores(observations: Iterable[rules.Observation]) -> dict[str, float]:
    """Per domain, the mean score over `observations`."""
    scores: dict[str, list[int]] = {}
    for o in observations:
        for d, s in o.scores.items():
            scores.setdefault(d, []).append(s)
    return {d: mean(v) for d, v in scores.items()}


def domain_averages(observations: Iterable[rules.Observation], instructor: str, today: date,
                    days: int = WINDOW_DAYS) -> dict[str, float]:
    """Per domain, the mean score over the instructor's observations dated within the last `days` days up to `today`
    (both ends inclusive). Empty when there is none."""
    since = today - timedelta(days=days)
    return _mean_scores(o for o in observations if o.instructor == instructor and since <= o.at <= today)


def latest_averages(observations: Iterable[rules.Observation], instructor: str) -> dict[str, float]:
    """Per domain, the mean score over the instructor's observations of their latest observation day (the observers of
    one delivery are averaged); empty when the instructor has none."""
    mine = [o for o in observations if o.instructor == instructor]
    latest = max((o.at for o in mine), default=None)
    return _mean_scores(o for o in mine if o.at == latest)


def lowest_domains(averages: dict[str, float], order: Sequence[str], count: int = GAP_COUNT) -> list[str]:
    """Up to `count` domains of `averages`, lowest average first, a tie going to the earlier framework domain."""
    known = [d for d in order if d in averages]
    return sorted(known, key=lambda d: (averages[d], order.index(d)))[:count]


def seed_gaps(averages: dict[str, float], order: Sequence[str]) -> list[tuple[str, float]]:
    """The gaps a plan is seeded with: the GAP_COUNT lowest domains whose average is below TARGET, as (domain, average
    rounded to two places)."""
    return [(d, round(averages[d], 2)) for d in lowest_domains(averages, order) if averages[d] < TARGET]


# --- the plan ----------------------------------------------------------------------------------------------------


def read_plan(st: State, instructor: str) -> dict[str, Any] | None:
    """The instructor's plan file from the private store; None when there is none or it is unreadable. The file is derived
    from the log (`plan_document`); only a plan made before the log carried its gaps is read from here."""
    path = st.private / plan_path(instructor)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and isinstance(doc.get("gaps"), list) else None


def plan_document(st: State, instructor: str) -> dict[str, Any] | None:
    """The instructor's plan, rebuilt from the log (integration review finding 17): the gaps of the latest `cpd-plan` `step`
    event ({domain, seed_average}), each closed by the first `cycle-close` `step` event of one of the instructor's cycles whose
    `cpd_review.closed` names its domain, and the reviews in the log's order. The plan file is a copy of this and is never read
    for it. A plan made before the event carried its gaps falls back to the file; None when the instructor has no plan."""
    seeded = None
    for e in st.index.of("step", instructor):
        if e["payload"].get("step") == STEP_PLAN:
            seeded = e
    if seeded is None:
        return None
    seeds = seeded["payload"].get("gaps")
    if not isinstance(seeds, list):
        return read_plan(st, instructor)
    doc: dict[str, Any] = {
        "instructor": instructor, "target": TARGET, "window_days": WINDOW_DAYS,
        "gaps": [{"domain": g["domain"], "seed_average": g["seed_average"], "status": "open"} for g in seeds], "reviews": []}
    pos = _positions(st)
    closes = sorted(((pos[e["id"]], uri, e) for uri, info in st.subjects.items()
                     if info.get("kind") == "cycle" and info.get("instructor") == instructor
                     for e in st.index.of("step", uri)
                     if e["payload"].get("step") == STEP_CLOSE and isinstance(e["payload"].get("cpd_review"), dict)),
                    key=lambda t: t[0])
    for _, cycle, e in closes:
        review = e["payload"]["cpd_review"]
        doc["reviews"].append({"cycle": cycle, "closed": list(review["closed"]), "kept": list(review["kept"])})
        for gap in doc["gaps"]:
            if gap["status"] == "open" and gap["domain"] in review["closed"]:
                gap["status"], gap["closed_by"] = "closed", cycle
    return doc


@auto_step(STEP_PLAN, per="instructor")
def make_plan(st: State, instructor: str, now: datetime) -> list[dict[str, Any]]:
    """The plan of an instructor, once they have an observation in the last WINDOW_DAYS days: their GAP_COUNT lowest-scoring
    domains below TARGET are the gaps, each open. Written to generated/cpd/<slug>.json with a `step` event naming it.
    Nothing is written for an instructor with no recent observation (the step stays open and runs again). The plan is
    seeded once: afterwards only a cycle's close changes it (`review_plan`)."""
    info = st.subjects.get(instructor)
    if info is None or info.get("kind") != "instructor":
        return []
    averages = domain_averages(observations(st), instructor, now.date())
    if not averages:
        return []
    gaps = [{"domain": d, "seed_average": a, "status": "open"} for d, a in seed_gaps(averages, domain_order(st))]
    doc = {"instructor": instructor, "target": TARGET, "window_days": WINDOW_DAYS, "gaps": gaps, "reviews": []}
    data = _json_bytes(doc)
    rel = plan_path(instructor)
    _write(st.private / rel, data)
    digest = hashlib.sha256(data).hexdigest()
    return [events.make_event(
        "step", instructor, SYSTEM_ACTOR,
        {"step": STEP_PLAN, "output": rel, "output_sha256": digest,
         "gaps": [{"domain": g["domain"], "seed_average": g["seed_average"]} for g in gaps]},
        id=signoff.input_sha256({"cpd_plan": [instructor, digest]})[:32], at=iso_seconds(now))]


def review_plan(st: State, instructor: str, cycle: str) -> dict[str, list[str]] | None:
    """The review of the instructor's plan at the close of `cycle`: each open gap whose domain's latest average
    (`latest_averages` over the observations in the log, the cycle's re-observation among them) has reached TARGET is closed
    (`closed_by` the cycle), the rest are kept. The plan is read from the log (`plan_document`); the review is returned for
    the caller to record as `cpd_review` on the cycle's close event (that event, not the file, is its record) and the plan file
    is rewritten as a copy of the result. Returns {"closed": [...], "kept": [...]}; None when the instructor has no plan.
    Reviewing the same cycle twice changes nothing and returns the review already recorded."""
    doc = plan_document(st, instructor)
    if doc is None:
        return None
    for review in doc.get("reviews", []):
        if review.get("cycle") == cycle:
            return {"closed": list(review["closed"]), "kept": list(review["kept"])}
    latest = latest_averages(observations(st), instructor)
    closed: list[str] = []
    kept: list[str] = []
    for gap in doc["gaps"]:
        if gap.get("status") != "open":
            continue
        if latest.get(gap["domain"], 0) >= TARGET:
            gap["status"], gap["closed_by"] = "closed", cycle
            closed.append(gap["domain"])
        else:
            kept.append(gap["domain"])
    doc.setdefault("reviews", []).append({"cycle": cycle, "closed": closed, "kept": kept})
    _write(st.private / plan_path(instructor), _json_bytes(doc))
    return {"closed": closed, "kept": kept}


# --- log-activity ------------------------------------------------------------------------------------------------


def _activities(st: State, instructor: str) -> list[dict]:
    mine = cached(st, "cpd_records", lambda: records.cpd(st.events))
    return [a for a in mine if a["instructor"] == instructor]


def _gap_rows(st: State, instructor: str, plan: dict[str, Any]) -> list[dict[str, Any]]:
    hours: dict[str, float] = {}
    for a in _activities(st, instructor):
        for d in a["domains"]:
            hours[d] = hours.get(d, 0) + a["hours"]
    return [{"domain": g["domain"], "status": g["status"], "hours": round(hours.get(g["domain"], 0), 2)}
            for g in plan["gaps"]]


@register(STEP_LOG)
def _b_log_activity(st: State, instructor: str) -> list[dict[str, Any]]:
    info = st.subjects.get(instructor)
    if info is None or info.get("kind") != "instructor":
        raise PageProblem(f"{instructor} is not an instructor")
    plan = plan_document(st, instructor)
    if plan is None:
        raise PageProblem(f"{instructor} has no CPD plan yet")
    inputs = {"instructor": instructor, "logged": len(_activities(st, instructor)), "gaps": _gap_rows(st, instructor, plan)}
    fields = [
        {"name": "activity", "label": "What you did (private)", "kind": "textarea", "required": True,
         "help": "Reading, practice, a course, a talk, time with a peer. Your words stay in the private store; the record "
                 "holds the domains, the hours and the date only."},
        {"name": "hours", "label": "Hours", "kind": "number", "required": True, "min": 0.25, "max": MAX_HOURS},
        {"name": "date", "label": "Date of the activity", "kind": "date", "required": True},
        *({"name": f"domain-{d['id']}", "label": f"Addresses: {d['name']}", "kind": "bool", "required": False,
           "help": d["covers"]} for d in st.standards["framework"]["domains"]),
    ]
    intro = ("Log a development activity against the framework domains it addresses (tick at least one). Activities on a "
             "domain with an open gap count towards it; your next coaching cycle's close keeps the gap open or closes it, "
             f"closing a gap once the domain's latest average reaches {TARGET}.")
    return [spec(st, STEP_LOG, instructor, instructor, "approve", inputs, fields, intro)]


def _activity(fields: Any, domains: Sequence[str], signed_at: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """The activity a sign-off's fields describe, or the reasons it cannot count. A reason names the field, never its value."""
    if not isinstance(fields, dict):
        return None, ["the sign-off carries no fields"]
    reasons: list[str] = []
    text = fields.get("activity")
    if not isinstance(text, str) or not text.strip():
        reasons.append("activity: a description is required")
    hours = fields.get("hours")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 < hours <= MAX_HOURS:
        reasons.append(f"hours: a number above 0 and at most {MAX_HOURS} is required")
    day = fields.get("date")
    try:
        if not (isinstance(day, str) and _DAY.match(day)):
            raise ValueError("date")
        held = date.fromisoformat(day)
        if held > _signed_day(signed_at, datetime.max):  # a stamp that cannot be read bounds nothing (ingest checks it)
            reasons.append("date: the activity is after the sign-off")
    except ValueError:
        reasons.append("date: a date (YYYY-MM-DD) is required")
    ticked = sorted(k[len("domain-"):] for k, v in fields.items() if k.startswith("domain-") and v is True)
    unknown = [d for d in ticked if d not in domains]
    if unknown:
        reasons.append("domain: only framework domains can be ticked")
    if not [d for d in ticked if d in domains]:
        reasons.append("domain: tick at least one framework domain")
    if reasons:
        return None, reasons
    return {"activity": text.strip(), "hours": hours, "logged_on": day, "domains": [d for d in domains if d in ticked]}, []


@content_check(STEP_LOG)
def _check_activity(st: State, document: dict[str, Any]) -> list[str]:
    return _activity(document.get("fields"), domain_order(st), document.get("signed_at"))[1]


@on_signoff(STEP_LOG)
def _record_activity(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """The `cpd` event of an approving sign-off (cpd@1) and the private document with the activity text. A sign-off that
    cannot count writes nothing (ingest refuses it first)."""
    instructor, p = signed["subject_uri"], signed["payload"]
    info = st.subjects.get(instructor)
    if info is None or info.get("kind") != "instructor":
        return [], []
    data, _ = _activity(document.get("fields"), domain_order(st), p.get("signed_at"))
    if data is None:
        return [], []
    sid = p["signoff_id"]
    key = activity_key(sid)
    event = events.make_event(
        "cpd", instructor, signed["actor"],
        {"instructor": instructor, "activity_key": key, "domains": data["domains"], "hours": data["hours"],
         "logged_on": data["logged_on"], "signoff_id": sid},
        id=signoff.input_sha256({"cpd_for_signoff": sid})[:32], at=_signed_at(p.get("signed_at"), now))
    private = {"signoff_id": sid, "instructor": instructor, "activity": data["activity"], "domains": data["domains"],
               "hours": data["hours"], "logged_on": data["logged_on"]}
    return [event], [(key, private)]


@due_rule("cpd_activity_window")
def cpd_activity_window(step: dict[str, Any], subject: str, info: dict[str, Any],
                        log: Sequence[dict[str, Any]], today: date) -> date | None:
    """An activity is due LOG_WINDOW_DAYS (an operational default) after the instructor's latest logged activity, or after
    their plan was made when they have logged none; no date before the plan exists."""
    last: date | None = None
    planned: date | None = None
    for e in log:
        if e["subject_uri"] != subject:
            continue
        if e["kind"] == "cpd" and isinstance(e["payload"].get("logged_on"), str):
            try:
                logged = date.fromisoformat(e["payload"]["logged_on"])
            except ValueError:
                continue
            last = logged if last is None else max(last, logged)
        elif e["kind"] == "step" and e["payload"].get("step") == STEP_PLAN and planned is None:
            planned = date.fromisoformat(e["at"][:10])
    base = last or planned
    return None if base is None else base + timedelta(days=LOG_WINDOW_DAYS)
