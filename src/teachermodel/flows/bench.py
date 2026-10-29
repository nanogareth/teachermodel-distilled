"""W10 bench decision (standards/workflows/bench.yaml): when a review opens, the evidence pack, whether the evidence is
enough, and the head of training's decision.

    open-bench (auto, programme)          ->  a `bench` subject per occasion (subject@2): engagement end within
                                              ENGAGEMENT_DAYS, quality triggers on two deliveries on a triggered cycle
                                              resting on teaching evidence (`_repeated_trigger`), or the command
                                              `teachermodel request-bench [--concern]`; an exited instructor gets none
    evidence-pack (auto, per bench)       ->  generated/bench/<slug>.html in the private store, and a `step` event with its
                                              sha256 (`evidence_pack_sha256`)
    bench-ready (auto, per bench)         ->  rules.bench_ready: an evidence pack and two current observers
    bench-decision (head of training)     ->  bound to the pack (`bind: input`); the hook writes the `bench_decision` event and
                                              the effects of the decision

Decision 0005: the pack and the decision are training-function records, kept in the private store, used to coach and to
decide clearances and bench reviews. Nothing here exports them to anyone who runs a performance review; the pack says so.

One review per occasion. A bench subject is `tm:bench/<instructor slug>--<n>`; n counts the instructor's reviews. An instructor
with a review that has no decision yet gets no second one. A new occasion needs new reason: a contract-end review is not opened
again for the same engagement (it was opened on or after ENGAGEMENT_DAYS before the engagement's end), and the quality triggers
that opened or preceded an earlier review do not count again (only triggers later in the log than the latest review count).

The pack is made from records.* only: clearances, observations of the bench window (rules.bench.current_window_days) with
their domain scores, outcome summaries (hidden below rules.quality.min_learners_for_metric learners), coaching cycles, CPD and
the audits of those observations.
Notes are referenced by their private-store key, never shown. The pack is regenerated while the review is undecided and its
evidence changes; once decided, the pack the decision rested on stays as it is.

The effects of a decision (the hook):
- return-to-co-teaching: a `level_change` to co-deliver from a higher level (none for an instructor already at co-deliver or
  below);
- exit: the spec has no 'exited' level, so no level changes. The instructor's candidates and open coaching cycles are closed by
  a `check` event each ({step: bench-decision, result: closed}); the workflow engine reads it (`workflow.is_closed`), so
  nothing of theirs stays due (integration review finding 3);
- renew and convert: the decision only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .. import events, records, rules
from ..records import bench_blocks
from ..signoff import short_sha as _hex
from ..standards import ROOT
from ..util import esc as _e
from ..util import parse_day as _day
from ..util import slug as _slug
from ..util import write_if_changed as _write
from ..workflow import SYSTEM_ACTOR
from . import auto_step, content_check, on_signoff, quality, register
from .common import HEAD_ROLE, is_head, PageProblem, State, blocked_check, cached, current_level, opened_day, people_with, spec
from .dry_run import is_candidates_instructor
from .observation import _positions
from .pathway import subject_event_id

STEP_OPEN = "tm:step/open-bench"
STEP_PACK = "tm:step/evidence-pack"
STEP_READY = "tm:step/bench-ready"
STEP_DECISION = "tm:step/bench-decision"
QUALITY_REVIEW = "tm:step/quality-review"  # the step whose `trigger` checks H writes (decision 0014)
OPENED_BY_CLI = "tm:cli/request-bench"
EVENT_LOG = "events/events.jsonl"

ENGAGEMENT_DAYS = 30  # operational default (decision 0002): a review opens this many days before an engagement ends
REPEATED_TRIGGERS = 2  # the plan's "two quality triggers while the latest cycle is triggered"
DECISIONS = ("renew", "convert", "return-to-co-teaching", "exit")
DEFAULT_DECISION = "return-to-co-teaching"  # spec W10: the default for a teaching-quality concern
TEACHING_QUALITY_REASONS = ("repeated-trigger",)
CONCERNS = ("teaching-quality", "other")  # request-bench --concern (finding 19); teaching-quality defaults the decision
TEACHING_QUALITY = "teaching-quality"
REASON_TEXT = {
    "contract-end": "the engagement ends within 30 days",
    "repeated-trigger": "repeated quality triggers on two deliveries, with an observation or a coaching cycle that did not help",
    "requested": "requested by the head of training",
}
CO_TEACHING_LEVEL = "co-deliver"
PACK_DIR = "generated/bench"
DECISION_DIR = "bench"  # under the private dir: <bench slug>.json, the rationale in words
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")


class BenchError(Exception):
    """A command refused its input; the message says what to fix."""


@dataclass(frozen=True)
class Opened:
    bench: str  # the bench subject URI
    created: bool  # False when the instructor already had an open review and nothing was written


def bench_uri(instructor: str, n: int) -> str:
    return f"tm:bench/{_slug(instructor)}--{n}"


def pack_path(bench: str) -> str:
    """Where the pack of a bench is kept, relative to the private dir."""
    return f"{PACK_DIR}/{_slug(bench)}.html"


def _find_bench(st: State, bench: Any) -> dict[str, Any] | None:
    info = st.subjects.get(bench)
    return info if info is not None and info.get("kind") == "bench" else None


def _bench_info(st: State, bench: str) -> dict[str, Any]:
    info = _find_bench(st, bench)
    if info is None:
        raise PageProblem(f"{bench} is not a bench review")
    return info


# --- open-bench --------------------------------------------------------------------------------------------------


def _contract_end(st: State, instructor: str, today: date, mine: list[dict[str, Any]]) -> bool:
    """The engagement ends within ENGAGEMENT_DAYS (or has passed, still active) and no earlier contract-end review covers
    it: one opened on or after ENGAGEMENT_DAYS before the end, which is when this reason first applies."""
    engagement = (st.registrations.get(instructor) or {}).get("engagement")
    end = _day(engagement.get("end")) if isinstance(engagement, dict) else None
    if end is None or engagement.get("status") == "ended" or (end - today).days > ENGAGEMENT_DAYS:
        return False
    first = end - timedelta(days=ENGAGEMENT_DAYS)
    return not any(b["reason"] == "contract-end" and b["opened"] >= first for b in mine)


def trigger_deliveries(st: State, instructor: str) -> dict[str, str]:
    """Trigger check id -> the delivery it was raised on, for the instructor's quality-review triggers whose delivery can be
    traced. quality-review derives a trigger's id from (instructor, reason, what completed it): the delivery of an outcome
    trigger, `<observation id>|<domain>` for a domain at 1 (`quality.trigger_id`), so the delivery is recovered by matching
    that id against the instructor's outcomes and observations. An observation's delivery is its `delivery_ref`, else the
    observation itself. A trigger that matches neither is left out: it is not counted (fail closed)."""
    keys: dict[str, str] = {}
    for o in records.outcomes(st.events):
        if o.instructor == instructor:
            for reason in (quality.SCORE_DROP, quality.FEEDBACK):
                keys[quality.trigger_id(instructor, reason, o.delivery)] = o.delivery
    domains = [d["id"] for d in st.standards["framework"]["domains"]]
    for e in cached(st, "bench observation events", lambda: [e for e in st.events if e["kind"] == "observation"]):
        if e["payload"].get("instructor") != instructor:
            continue
        delivery = e["payload"].get("delivery_ref") if isinstance(e["payload"].get("delivery_ref"), str) else e["id"]
        for d in domains:
            keys[quality.trigger_id(instructor, quality.DOMAIN_ONE, f"{e['id']}|{d}")] = delivery
    return {e["id"]: keys[e["id"]] for e in st.index.of("check", instructor)
            if e["payload"].get("step") == QUALITY_REVIEW and e["payload"].get("result") == "trigger" and e["id"] in keys}


def _unimproved(st: State, instructor: str, floor: int) -> bool:
    """A triggered coaching cycle of the instructor that closed (later in the log than `floor`) with no gain in any of its focus
    domains: every focus domain's change is recorded and is 0 or less. A cycle with no recorded change is not evidence."""
    pos = _positions(st)
    for c in records.cycles(st.events):
        if c.get("instructor") != instructor or c.get("intensity") != "triggered" or c.get("phase") != "closed":
            continue
        change, focus = c.get("change") or {}, list(c.get("focus") or [])
        if not focus or not all(isinstance(change.get(d), (int, float)) and change[d] <= 0 for d in focus):
            continue
        if any(e["payload"].get("phase") == "closed" and pos[e["id"]] > floor
               for e in st.index.of("coaching_cycle", c["cycle"])):
            return True
    return False


def _repeated_trigger(st: State, instructor: str, mine: list[dict[str, Any]]) -> bool:
    """Repeated quality triggers that rest on teaching evidence (integration review finding 1; spec W8: an outcome alone never
    causes a bench decision). All of:
    - the instructor's latest cycle is triggered;
    - the quality-review triggers later in the log than both that cycle's opening and their latest review's opening were
      raised on at least REPEATED_TRIGGERS distinct deliveries (`trigger_deliveries`; two triggers of one delivery count
      once, an untraceable one not at all);
    - and the teaching itself is in question: one of those triggers is observation-based (`domain-one-confirmed`, a domain
      scored 1 and confirmed by a second observer), or a triggered cycle closed after their latest review without a gain in
      its focus domains (`_unimproved`)."""
    cycles = [(info.get("number"), uri) for uri, info in st.subjects.items()
              if info.get("kind") == "cycle" and info.get("instructor") == instructor and isinstance(info.get("number"), int)]
    if not cycles:
        return False
    uri = max(cycles)[1]
    if st.subjects[uri].get("intensity") != "triggered":
        return False
    pos = _positions(st)
    reviewed = max((pos[e["id"]] for b in mine for e in st.index.of("subject", b["bench"])), default=-1)
    floor = max([reviewed, *(pos[e["id"]] for e in st.index.of("subject", uri))])
    traced = trigger_deliveries(st, instructor)
    found = [e for e in st.index.of("check", instructor) if e["id"] in traced and pos[e["id"]] > floor]
    if len({traced[e["id"]] for e in found}) < REPEATED_TRIGGERS:
        return False
    return (any(e["payload"].get("trigger") == quality.DOMAIN_ONE for e in found)
            or _unimproved(st, instructor, reviewed))


@auto_step(STEP_OPEN, refresh=True)
def open_bench(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    """A `bench` subject event for each registered instructor with no open review who has a reason for one (engagement end
    within ENGAGEMENT_DAYS; else two triggers on a triggered cycle), plus a `step` event {step, opened} when something was
    opened or the step has never run. Runs again whenever its needs are met."""
    reviews = records.bench(st.events)
    today, stamp = now.date(), now.isoformat(timespec="seconds")
    out: list[dict[str, Any]] = []
    for instructor in sorted(st.registrations):
        mine = [b for b in reviews if b["instructor"] == instructor]
        if any(b["decision"] is None for b in mine):
            continue
        if bench_blocks.is_exited(st.events, instructor, today):  # finding 2: their teaching ended by a decision
            continue
        reason = ("contract-end" if _contract_end(st, instructor, today, mine)
                  else "repeated-trigger" if _repeated_trigger(st, instructor, mine) else None)
        if reason is None:
            continue
        uri = bench_uri(instructor, len(mine) + 1)
        opened = events.make_event(
            "subject", uri, SYSTEM_ACTOR,
            {"subject_kind": "bench", "attrs": {"instructor": instructor, "reason": reason}, "opened_by": STEP_OPEN},
            id=subject_event_id(uri), at=stamp)
        if not events.check_event(opened):
            out.append(opened)
    ran = any(e["payload"].get("step") == STEP_OPEN for e in st.index.of("step", subject))
    if out or not ran:
        uris = sorted(e["subject_uri"] for e in out)
        out.append(events.make_event("step", subject, SYSTEM_ACTOR, {"step": STEP_OPEN, "opened": uris},
                                     id=_hex({"open_bench": uris}), at=stamp))
    return out


def _instructor_uri(raw: str) -> str:
    text = raw.strip() if isinstance(raw, str) else ""
    slug = text.split("/", 1)[1] if text.startswith("tm:instructor/") else text
    if not _SLUG.match(slug):
        raise BenchError(f"{raw!r} is not a registered instructor (give tm:instructor/<slug> or the bare slug)")
    return f"tm:instructor/{slug}"


def request_bench(
    private_dir: Path | str, *, instructor: str, concern: str | None = None, now: datetime | None = None,
    root: Path = ROOT,
) -> Opened:
    """Open a bench review for a registered instructor, reason `requested` (the command `request-bench`, run by the head of
    training), with an optional `concern` (CONCERNS; integration review finding 19): a teaching-quality concern
    makes return to co-teaching the decision page's default (spec W10). An instructor with an open review keeps it and
    nothing is written. Raises BenchError."""
    now = now or datetime.now(timezone.utc)
    if concern is not None and concern not in CONCERNS:
        raise BenchError(f"concern: {concern!r} is not one of {', '.join(CONCERNS)}")
    uri = _instructor_uri(instructor)
    log_path = Path(private_dir) / EVENT_LOG
    log = list(events.read(log_path)) if log_path.is_file() else []
    if uri not in {e["subject_uri"] for e in log if e["kind"] == "registration"}:
        raise BenchError(f"{uri} is not a registered instructor")
    mine = [b for b in records.bench(log) if b["instructor"] == uri]
    open_ones = [b for b in mine if b["decision"] is None]
    if open_ones:
        return Opened(open_ones[-1]["bench"], False)
    new = bench_uri(uri, len(mine) + 1)
    attrs = {"instructor": uri, "reason": "requested", **({"concern": concern} if concern else {})}
    events.append(log_path, events.make_event(
        "subject", new, SYSTEM_ACTOR, {"subject_kind": "bench", "attrs": attrs, "opened_by": OPENED_BY_CLI},
        id=subject_event_id(new), at=now.isoformat(timespec="seconds")))
    return Opened(new, True)


# --- evidence-pack -----------------------------------------------------------------------------------------------


def _packs(st: State, bench: str) -> list[dict[str, Any]]:
    """The bench's `evidence-pack` step events, in log order."""
    return [e for e in st.index.of("step", bench) if e["payload"].get("step") == STEP_PACK]


def _decided(st: State, bench: str) -> bool:
    return any(b["bench"] == bench and b["decision"] is not None for b in records.bench(st.events))


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def pack_data(st: State, bench: str, today: date) -> dict[str, Any]:
    """What the pack shows, as plain JSON-able data: nothing in it depends on the day of the run except which observations
    fall in the window, so the same evidence gives the same data (and its hash) on any day."""
    info = _bench_info(st, bench)
    instructor = info["instructor"]
    rules_doc = st.standards["rules"]
    window = rules_doc["bench"]["current_window_days"]
    since = today - timedelta(days=window)
    domains = [d["id"] for d in st.standards["framework"]["domains"]]
    opened = opened_day(st, bench)
    payloads = {e["id"]: e["payload"] for e in st.events if e["kind"] == "observation"}

    clearances = [
        {"clearance": c.id, "unit": c.unit, "modes": list(c.modes), "outcome": c.outcome, "issued": c.issued.isoformat(),
         "expires": c.expires.isoformat(),
         "scope": ({"partner": c.scope.partner, "regions": list(c.scope.regions) if c.scope.regions is not None else None}
                   if c.scope else None)}
        for c in records.clearances(st.events) if c.instructor == instructor]

    inside = [o for o in records.observations(st.events) if o.instructor == instructor and since <= o.at <= today]
    observations = [
        {"observation": o.id, "observer": o.observer, "date": o.at.isoformat(), "unit": o.unit, "length": o.length,
         "lead": o.lead, "mode": o.mode, "scores": {d: o.scores.get(d) for d in domains},
         "evidence_ref": payloads.get(o.id, {}).get("evidence_ref"), "from_recording": payloads.get(o.id, {}).get("from_recording")}
        for o in inside]
    averages = {d: round(mean(o.scores[d] for o in inside if d in o.scores), 2) for d in domains
                if any(d in o.scores for o in inside)}

    minimum = rules_doc["quality"]["min_learners_for_metric"]
    mine = [o for o in records.outcomes(st.events) if o.instructor == instructor]
    outcomes = {
        "minimum_learners": minimum,
        "hidden": sum(1 for o in mine if o.learners_assessed < minimum),
        "deliveries": [{"delivery": o.delivery, "date": o.at.isoformat(), "learners": o.learners_assessed,
                        "score": o.score, "baseline": o.baseline, "feedback": o.feedback,
                        "feedback_median": o.feedback_median}
                       for o in mine if o.learners_assessed >= minimum]}
    cycles = [{"cycle": c.get("cycle"), "coach": c.get("coach"), "number": c.get("number"),
               "intensity": c.get("intensity"), "focus": list(c.get("focus") or []), "trigger": c.get("trigger"),
               "phase": c.get("phase"), "opened": _iso(c.get("opened")), "closed": _iso(c.get("closed")),
               "change": c.get("change")} for c in records.cycles(st.events) if c.get("instructor") == instructor]
    cpd = [{"id": c.get("id"), "activity_key": c.get("activity_key"), "domains": list(c.get("domains") or []),
            "hours": c.get("hours"), "logged_on": _iso(c.get("logged_on"))}
           for c in records.cpd(st.events) if c.get("instructor") == instructor]
    seen = {o.id for o in inside}
    audits = [{"id": a.get("id"), "observation": a.get("observation"), "observer": a.get("observer"),
               "second_observer": a.get("second_observer"), "within_one_share": a.get("within_one_share"),
               "exact_share": a.get("exact_share"), "agreed": a.get("agreed"),
               "referred_to_calibration": a.get("referred_to_calibration"), "at": _iso(a.get("at"))}
              for a in records.audits(st.events) if a.get("observation") in seen]
    return {
        "bench": bench, "instructor": instructor, "reason": info["reason"],
        "opened": opened.isoformat() if opened else None,
        "window_days": window, "domains": domains, "clearances": clearances, "observations": observations,
        "observers": sorted({o.observer for o in inside}), "averages": averages, "outcomes": outcomes,
        "coaching": cycles, "cpd": cpd, "audits": audits,
    }


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _section(title: str, body: str) -> str:
    return f"<section><h2>{_e(title)}</h2>{body}</section>"


STYLE = (
    "body{font-family:Arial,Helvetica,sans-serif;margin:2rem auto;max-width:60rem;color:#262838;line-height:1.4}"
    "h1{color:#12193E}h2{color:#434D9E;border-bottom:1px solid #ccc;padding-bottom:.2rem;margin-top:2rem}"
    "table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}"
    "th{background:#f0f1f8}footer{margin-top:3rem;font-size:.85rem;color:#555}"
)


def render_pack(data: dict[str, Any], as_of: date) -> str:
    """The pack as one HTML file with no external reference. Every value is escaped; notes are shown as their keys."""
    domains = data["domains"]
    parts = [
        f"<h1>Bench evidence pack</h1><p>{_e(data['bench'])} &middot; instructor {_e(data['instructor'])} &middot; reason: "
        f"{_e(data['reason'])} &middot; review opened {_e(data['opened'])} &middot; evidence as of {_e(as_of.isoformat())}</p>"]

    clearances = data["clearances"]
    parts.append(_section("Clearances", _table(
        ["Clearance", "Unit", "Modes", "Outcome", "Issued", "Expires", "Scope"],
        [[c["clearance"], c["unit"], ", ".join(c["modes"]), c["outcome"], c["issued"], c["expires"],
          json.dumps(c["scope"], sort_keys=True) if c["scope"] else "none"] for c in clearances])
        if clearances else "<p>No clearances on record.</p>"))

    n = len(data["observers"])
    obs = data["observations"]
    body = (f"<p>{n} distinct observers in the last {data['window_days']} days: "
            f"{_e(', '.join(data['observers']) or 'none')}.</p>")
    if obs:
        body += _table(["Observation", "Date", "Observer", "Unit", "Length", "Lead", "From recording", *domains, "Notes (key)"],
                       [[o["observation"], o["date"], o["observer"], o["unit"], o["length"], o["lead"], o["from_recording"],
                         *[o["scores"][d] for d in domains], o["evidence_ref"] or ""] for o in obs])
        body += "<p>Average per domain: " + _e(", ".join(f"{d} {v}" for d, v in data["averages"].items())) + ".</p>"
        body += "<p>Notes stay in the private store; this pack holds only their keys.</p>"
    parts.append(_section("Observations in the window", body))

    out = data["outcomes"]
    body = _table(["Delivery", "Date", "Learners", "Score", "Baseline", "Feedback", "Feedback median"],
                  [[d["delivery"], d["date"], d["learners"], d["score"], d["baseline"], d["feedback"],
                    d["feedback_median"]] for d in out["deliveries"]]) if out["deliveries"] else "<p>None to show.</p>"
    h, m = out["hidden"], out["minimum_learners"]
    if h:
        body += (f"<p>{h} delivery below the minimum of {m} learners is not shown.</p>" if h == 1 else
                 f"<p>{h} deliveries below the minimum of {m} learners are not shown.</p>")
    body += "<p>Outcomes are read against the cohort baseline and never decide a bench review alone.</p>"
    parts.append(_section("Outcome summaries", body))

    cycles = data["coaching"]
    parts.append(_section("Coaching history", (_table(
        ["Cycle", "Coach", "Intensity", "Focus", "Phase", "Opened", "Closed", "Change"],
        [[c["cycle"], c["coach"], c["intensity"], ", ".join(c["focus"]), c["phase"], c["opened"], c["closed"],
          json.dumps(c["change"], sort_keys=True) if c["change"] else ""] for c in cycles])
        if cycles else "<p>No coaching cycles on record.</p>")))

    cpd = data["cpd"]
    parts.append(_section("CPD", (_table(
        ["Logged on", "Activity (key)", "Domains", "Hours"],
        [[c["logged_on"], c["activity_key"], ", ".join(c["domains"]), c["hours"]] for c in cpd])
        if cpd else "<p>No CPD logged.</p>")))

    audits = data["audits"]
    parts.append(_section("Audits of these observations", (_table(
        ["Audit", "Observation", "Observer", "Second observer", "Within one", "Exact", "Agreed", "Referred"],
        [[a["id"], a["observation"], a["observer"], a["second_observer"], a["within_one_share"], a["exact_share"],
          a["agreed"], a["referred_to_calibration"]] for a in audits])
        if audits else "<p>None of these observations was audited.</p>")))

    parts.append("<footer>A record of the technical training function, kept in the private store (decision 0005). It is used "
                 "only to coach and to decide clearances and bench reviews. It is not for performance review and is not "
                 "exported to anyone who runs one.</footer>")
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>Bench evidence pack "
            f"{_e(data['bench'])}</title><style>{STYLE}</style></head><body>" + "".join(parts) + "</body></html>\n")


def _pack_events(st: State, bench: str, now: datetime) -> list[dict[str, Any]]:
    """Write the pack when the evidence it shows changed (or the file is missing or altered), and the `step` event naming
    it. Nothing once the bench is decided, and nothing when the pack on record is current."""
    if _decided(st, bench):
        return []
    data = pack_data(st, bench, now.date())
    content = hashlib.sha256(events.canonical(data).encode("utf-8")).hexdigest()
    earlier = _packs(st, bench)
    path = st.private / pack_path(bench)
    if (earlier and earlier[-1]["payload"].get("content_sha256") == content and path.is_file()
            and hashlib.sha256(path.read_bytes()).hexdigest() == earlier[-1]["payload"].get("evidence_pack_sha256")):
        return []
    raw = render_pack(data, now.date()).encode("utf-8")
    _write(path, raw)
    sha = hashlib.sha256(raw).hexdigest()
    if earlier and earlier[-1]["payload"].get("evidence_pack_sha256") == sha:
        return []
    return [events.make_event(
        "step", bench, SYSTEM_ACTOR,
        {"step": STEP_PACK, "output": pack_path(bench), "evidence_pack_sha256": sha, "content_sha256": content,
         "observers": data["observers"]},
        id=_hex({"evidence_pack": [bench, sha, len(earlier)]}), at=now.isoformat(timespec="seconds"))]


@auto_step(STEP_PACK, refresh=True, per="bench")
def evidence_pack(st: State, bench: str, now: datetime) -> list[dict[str, Any]]:
    """generated/bench/<slug>.html and a `step` event with its sha256 (and the hash of the evidence it shows, so an unchanged
    run writes nothing). Runs again, refreshing the pack, while the review is undecided and its evidence changes."""
    if _find_bench(st, bench) is None:
        return []
    return _pack_events(st, bench, now)


# --- bench-ready -------------------------------------------------------------------------------------------------


@auto_step(STEP_READY, per="bench")
def bench_ready(st: State, bench: str, now: datetime) -> list[dict[str, Any]]:
    """rules.bench_ready over the observations on record, with the evidence pack as it stands: a `step` event when the
    review has an evidence pack and observations from two distinct observers in the window, else a blocked `check` with the
    rule's reasons (said once) and the step stays open. The pack is brought up to date first, so the verdict and the pack
    rest on the same evidence."""
    info = _find_bench(st, bench)
    if info is None:
        return []
    fresh = _pack_events(st, bench, now)
    latest = (fresh or _packs(st, bench) or [None])[-1]
    v = rules.bench_ready(info["instructor"], records.observations(st.events), latest is not None, now.date(),
                          st.standards["rules"])
    if not v.ok or latest is None:
        return fresh + blocked_check(st, STEP_READY, bench, v.reasons or ["no evidence pack"], now, seed="bench_blocked")
    return fresh + [events.make_event(
        "step", bench, SYSTEM_ACTOR,
        {"step": STEP_READY, "evidence_pack_sha256": latest["payload"]["evidence_pack_sha256"]},
        id=_hex({"bench_ready": bench}), at=now.isoformat(timespec="seconds"))]


# --- bench-decision ----------------------------------------------------------------------------------------------


def _inputs(st: State, bench: str) -> dict[str, Any]:
    info = _bench_info(st, bench)
    packs = _packs(st, bench)
    if not packs:
        raise PageProblem(f"{bench} has no evidence pack yet")
    p = packs[-1]["payload"]
    opened = opened_day(st, bench)
    out = {"bench": bench, "instructor": info["instructor"], "reason": info["reason"],
           "opened": opened.isoformat() if opened else None, "evidence_pack": p["output"],
           "evidence_pack_sha256": p["evidence_pack_sha256"], "observers": list(p.get("observers", []))}
    if isinstance(info.get("concern"), str):  # only when the request named one, so earlier reviews keep their inputs
        out["concern"] = info["concern"]
    return out


def _teaching_quality(info: dict[str, Any]) -> bool:
    """A review for a teaching-quality concern: opened for repeated triggers, or requested with that concern (finding 19)."""
    return info.get("reason") in TEACHING_QUALITY_REASONS or info.get("concern") == TEACHING_QUALITY


def _fields(info: dict[str, Any]) -> list[dict[str, Any]]:
    decision: dict[str, Any] = {
        "name": "decision", "label": "Decision", "kind": "enum", "options": list(DECISIONS), "required": True,
        "help": "renew or convert the engagement, return the instructor to co-teaching (the default for a teaching-quality "
                "concern; it lowers their level to co-deliver), or exit (no level changes; their candidates are closed)."}
    if _teaching_quality(info):
        decision["value"] = DEFAULT_DECISION
    return [decision,
            {"name": "rationale", "label": "Rationale (private)", "kind": "textarea", "required": True,
             "help": "Why this decision, on the evidence in the pack. It stays in the private store; the log holds a key."}]


@register(STEP_DECISION)
def _b_decision(st: State, bench: str):
    info = _bench_info(st, bench)
    inputs = _inputs(st, bench)
    heads = [r["person"] for r in people_with(st, HEAD_ROLE) if not is_candidates_instructor(st, r["person"], info["instructor"])]
    if not heads:
        raise PageProblem(f"{bench}: no head of training other than the instructor can decide it")
    why = REASON_TEXT.get(info["reason"], str(info["reason"]))
    if isinstance(info.get("concern"), str):
        why += f" (concern: {info['concern'].replace('-', ' ')})"
    intro = (f"This review opened because {why}. Decide it from the evidence pack named below (open it from the private "
             f"store, {inputs['evidence_pack']}; its hash is in this page's inputs). A bench decision rests on observations "
             "from at least two observers and the pack. The pack and your decision are training-function records, not for "
             "performance review (decision 0005).")
    return [spec(st, STEP_DECISION, bench, h, "approve", inputs, _fields(info), intro) for h in heads]


def _signed_day(document: dict[str, Any]) -> date | None:
    try:
        return datetime.fromisoformat(str(document.get("signed_at")).replace("Z", "+00:00")).date()
    except ValueError:
        return None


@content_check(STEP_DECISION)
def _check_decision(st: State, document: dict[str, Any]) -> list[str]:
    """The head of training (a people-list person holding the role), never the instructor under review, with a
    decision from DECISIONS and a written rationale, on a day when the evidence is still enough (rules.bench_ready over the
    window ending on the day of signing)."""
    bench = document.get("subject_uri")
    info = _find_bench(st, bench)
    if info is None:
        return ["the subject is not a bench review"]
    signer = document.get("signer")
    reasons: list[str] = []
    if not is_head(st, signer):
        reasons.append("the signer is not the head of training")
    if is_candidates_instructor(st, signer, info["instructor"]):
        reasons.append("the signer is the instructor under review")
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return reasons + ["the sign-off carries no fields"]
    if fields.get("decision") not in DECISIONS:
        reasons.append(f"decision: one of {', '.join(DECISIONS)} is required")
    if not isinstance(fields.get("rationale"), str) or not fields["rationale"].strip():
        reasons.append("rationale: a written rationale is required")
    signed_on = _signed_day(document)
    if signed_on is None:
        reasons.append("signed_at: a date-time is required")
    else:
        reasons += rules.bench_ready(info["instructor"], records.observations(st.events), bool(_packs(st, bench)), signed_on,
                                     st.standards["rules"]).reasons
    return reasons


@on_signoff(STEP_DECISION)
def _record_decision(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """The `bench_decision` event (bench-decision@1) with the pack hash the decision rested on, the private document that
    holds the rationale, and the effects of the decision (see the module docstring). Nothing for a sign-off the content check
    would have refused (no review, no pack, no usable fields)."""
    bench = signed["subject_uri"]
    info = _find_bench(st, bench)
    fields = document.get("fields")
    packs = _packs(st, bench) if info is not None else []
    if not packs or not isinstance(fields, dict) or fields.get("decision") not in DECISIONS:
        return [], []
    rationale = fields.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        return [], []
    instructor, decision, sid = info["instructor"], fields["decision"], signed["payload"]["signoff_id"]
    stamp = now.isoformat(timespec="seconds")
    sha = packs[-1]["payload"]["evidence_pack_sha256"]
    key = f"{DECISION_DIR}/{_slug(bench)}.json"
    decided = events.make_event(
        "bench_decision", bench, signed["actor"],
        {"bench": bench, "instructor": instructor, "decision": decision, "rationale_key": key,
         "evidence_pack_sha256": sha, "decided_by": signed["actor"], "signoff_id": sid},
        id=_hex({"bench_decision": [bench, sid]}), at=stamp)
    problems = events.check_event(decided)
    if problems:
        return [events.make_event("check", bench, SYSTEM_ACTOR, {"step": STEP_DECISION, "result": "blocked", "reasons": problems},
                                  id=_hex({"bench_decision_blocked": [bench, sid, problems]}), at=stamp)], []
    out = [decided]

    def closed(subject: str, seed: str) -> dict[str, Any]:
        return events.make_event(
            "check", subject, SYSTEM_ACTOR,
            {"step": STEP_DECISION, "result": "closed", "bench": bench, "decision": "exit",
             "reason": "the instructor left the programme by a bench decision"},
            id=_hex({seed: [bench, sid, subject]}), at=stamp)

    if decision == "return-to-co-teaching":
        levels = st.standards["framework"]["levels"]
        level = current_level(st, instructor)
        if level in levels and levels.index(level) > levels.index(CO_TEACHING_LEVEL):
            out.append(events.make_event(
                "level_change", instructor, signed["actor"],
                {"from": level, "to": CO_TEACHING_LEVEL, "basis": f"signoff {sid}; bench {bench}: return to co-teaching"},
                id=_hex({"bench_level_change": [bench, sid]}), at=stamp))
    elif decision == "exit":
        for candidate in sorted(u for u, i in st.subjects.items() if i.get("kind") == "candidate"
                                and i.get("instructor") == instructor):
            out.append(closed(candidate, "bench_candidate_closed"))
        for c in records.cycles(st.events):  # an open coaching cycle ends too (finding 3); a closed one is history
            if c.get("instructor") == instructor and c.get("phase") != "closed":
                out.append(closed(c["cycle"], "bench_cycle_closed"))
    private = {"bench": bench, "decision": decision, "rationale": rationale.strip(), "signoff_id": sid,
               "evidence_pack_sha256": sha, "decided_by": signed["actor"]}
    return out, [(key, private)]
