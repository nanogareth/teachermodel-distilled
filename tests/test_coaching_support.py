"""Shared world builder and drivers for the W7 coaching and W9 CPD tests (no tests of its own). Fictional people only.

A world is the example roster imported (p3x9d cleared and delivering the example unit, c5w1t lead-observed delivering
nothing, k7m2q co-deliver, r8n4h shadow), plus `ops` applied in order before the first run:

    ("coach", slug, [coached instructor URIs])   a people-list coach mapped to the instructor of that slug
    ("obs", instructor, day, {domain: score})     an `observation` event by r8n4h, released that day
    ("trigger", instructor, trigger id, domain|None)   H's quality-review trigger `check` event
    ("cycle", instructor, number, opened, closed|None, coach, focus tuple, intensity)   a cycle on record

then, unless `run` is False, one `app.do_run` at T0 (a Monday).
"""

import hashlib
from datetime import datetime, timedelta, timezone

import yaml
from conftest import make_fictional_store
from privacy_helpers import import_roster_ungated
from test_observation import observe_fields, of_kind, sign
from world_cache import copy_world

from teachermodel import app, events
from teachermodel.standards import load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)  # a Monday
SYSTEM = "tm:system/teachermodel"
UNIT = "sl:unit/example-agent-loop@1"
P3, K7, C5, R8 = (f"tm:instructor/{s}" for s in ("p3x9d", "k7m2q", "c5w1t", "r8n4h"))
DOMAINS = [d["id"] for d in load_standards()["framework"]["domains"]]
TD, PK, CQ, LF, RI = DOMAINS
LOW = {TD: 4, PK: 2, CQ: 3, LF: 1, RI: 3}  # the two lowest are lab-facilitation (1) then prior-knowledge (2)
STEP_OPEN = "tm:step/open-cycles"
STEP_OBSERVE, STEP_FEEDBACK, STEP_PRACTICE, STEP_REOBSERVE, STEP_CLOSE = (
    f"tm:step/{s}" for s in ("coach-observe", "coach-feedback", "practice-task", "coach-reobserve", "cycle-close"))
STEP_QUALITY = "tm:step/quality-review"
TASK = "OMEGA-TASK rehearse the retry lab twice with a timer"
FEEDBACK = "SIGMA-FEEDBACK the pre-check was skipped at the start of the lab"


def log(private):
    return app.read_events(private)


def slug(uri):
    """The slug of a URI (`tm:instructor/k7m2q` -> `k7m2q`); a bare slug is returned as it is."""
    return uri.split("/", 1)[-1]


def cycle_uri(instructor, number=1):
    return f"tm:cycle/{slug(instructor)}--{number}"


def add_coach(private, who, of):
    """A people-list coach mapped to the instructor `who` (a slug or URI), who coaches the instructors `of`."""
    s = slug(who)
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": f"tm:person/coach-{s}", "name": f"Coach {s}", "email": f"coach.{s}@example.com",
                          "roles": ["coach"], "instructor": f"tm:instructor/{s}", "coaches": list(of)})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def add_observation(private, instructor, day, scores, observer=R8, unit=UNIT):
    key = f"{instructor}|{day}|{sorted(scores.items())}|{observer}"
    events.append(private / app.EVENT_LOG, events.make_event(
        "observation", instructor, observer,
        {"instructor": instructor, "unit": unit, "observer": observer, "length": "full", "lead": True, "mode": "remote",
         "rubric_version": "0.2.0", "scores": dict(scores)},
        id=hashlib.sha256(key.encode()).hexdigest()[:32], at=f"{day}T09:00:00+00:00"))


def add_trigger(private, instructor, trigger, domain=None, at="2026-10-20T07:00:00+00:00"):
    payload = {"step": STEP_QUALITY, "instructor": instructor, "result": "trigger", "trigger": trigger}
    if domain:
        payload["domain"] = domain
    events.append(private / app.EVENT_LOG, events.make_event("check", instructor, SYSTEM, payload, at=at))


def add_cycle(private, instructor, number, opened, closed, coach=K7, focus=(LF,), intensity="standard"):
    """A cycle on record: its `subject` event (opened) and phase events, the last of them `closed` when `closed` is given."""
    uri = cycle_uri(instructor, number)
    attrs = {"instructor": instructor, "coach": coach, "number": number, "intensity": intensity, "focus": list(focus)}
    path = private / app.EVENT_LOG
    events.append(path, events.make_event(
        "subject", uri, SYSTEM, {"subject_kind": "cycle", "attrs": attrs, "opened_by": "tm:cli/seed-cycle"},
        id=hashlib.sha256(f"open {uri}".encode()).hexdigest()[:32], at=f"{opened}T07:00:00+00:00"))
    phases = [("opened", opened, None)] + ([("closed", closed, {d: 1 for d in focus})] if closed else [])
    for phase, day, change in phases:
        payload = {**attrs, "cycle": uri, "phase": phase}
        if change:
            payload["change"] = change
        events.append(path, events.make_event(
            "coaching_cycle", uri, SYSTEM, payload,
            id=hashlib.sha256(f"{phase} {uri}".encode()).hexdigest()[:32], at=f"{day}T07:00:00+00:00"))


def _apply(private, op):
    kind, args = op[0], op[1:]
    if kind == "coach":
        add_coach(private, *args)
    elif kind == "obs":
        add_observation(private, *args)
    elif kind == "trigger":
        add_trigger(private, *args)
    elif kind == "cycle":
        add_cycle(private, *args)
    else:
        raise ValueError(kind)


def _build(base, roster_bytes, ops, run):
    private = make_fictional_store(base)
    roster = base / "roster-in.yaml"
    roster.write_bytes(roster_bytes)
    import_roster_ungated(private, roster, T0)
    for op in ops:
        _apply(private, op)
    if run:
        app.do_run(private, now=T0)


def world(fictional_store, example_roster, ops=(), run=True):
    """The roster imported and `ops` applied, then one run: built once per session per `ops` (conftest.copy_world) and
    copied into the test's tmp_path, beside `fictional_store`. Returns the private store."""
    data = example_roster.read_bytes()
    key = ("coaching_world", hashlib.sha256(data).hexdigest(), repr(ops), run)
    copy_world(key, lambda base: _build(base, data, ops, run), fictional_store.parent)
    return fictional_store


# the usual world: k7m2q coaches p3x9d; p3x9d has observations whose lowest domains are lab-facilitation, prior-knowledge
BASIC = (("coach", "k7m2q", [P3]), ("obs", P3, "2026-09-15", LOW))


def due_ids(private, now=T0):
    return {(d.step, d.subject) for d in app.due_steps(app.load_state(private), now.date())}


def cycles_opened(private):
    return [e for e in of_kind(private, "subject") if e["payload"]["subject_kind"] == "cycle"]


def phase_events(private, phase=None, cycle=None):
    return [e for e in of_kind(private, "coaching_cycle")
            if (phase is None or e["payload"]["phase"] == phase) and (cycle is None or e["payload"]["cycle"] == cycle)]


def observe_cycle_fields(score=3, day="2026-10-27", marks=None):
    """The coach's observe page answers: every domain `score`, except the ones in `marks` (domain -> score); the example unit."""
    fields = observe_fields(score, day=day)
    fields["unit"] = UNIT
    for d, s in (marks or {}).items():
        fields[d] = {"score": s, "note": f"note for {d}"}
    return fields


def _later(at, days):
    return (datetime.fromisoformat(at) + timedelta(days=days)).isoformat(timespec="seconds")


def feedback_fields(focus, text=FEEDBACK):
    return {k: v for d in focus for k, v in ((f"note-{d}", f"evidence for {d}"), (f"feedback-{d}", text))}


def practice_fields(focus, text=TASK):
    return {f"task-{d}": text for d in focus}


def drive_cycle(private, cycle, *, first, second, session_day="2026-10-27", reobserve_day="2026-11-20",
                at="2026-10-28T09:00:00+00:00"):
    """Take the cycle from its open observe step to its close: the coach observes (`first`, a domain -> score dict over the
    domains named; the rest score 3), gives feedback, sets a practice task, re-observes (`second`), and a run closes it.
    Sign-offs are applied as ingest applies them (tests/test_observation.sign). Returns the cycle's coach."""
    info = app.load_state(private).subjects[cycle]
    coach, focus = info["coach"], info["focus"]
    sign(private, STEP_OBSERVE, cycle, coach, observe_cycle_fields(3, session_day, first), at=at)
    sign(private, STEP_FEEDBACK, cycle, coach, feedback_fields(focus), at=_later(at, 1))
    sign(private, STEP_PRACTICE, cycle, coach, practice_fields(focus), at=_later(at, 2))
    sign(private, STEP_REOBSERVE, cycle, coach, observe_cycle_fields(3, reobserve_day, second), at=_later(at, 25))
    app.do_run(private, now=datetime.fromisoformat(_later(at, 26)))
    return coach
