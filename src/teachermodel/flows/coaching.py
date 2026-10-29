"""W7 coaching (standards/workflows/coaching.yaml): every instructor at lead-observed or above is always in a cycle.

    open-cycles (auto, programme, refresh)  ->  a `cycle` subject (subject@2) and a coaching_cycle `opened` event per
                                                instructor whose latest cycle is closed (or stalled); a coaching_cycle event
                                                of the cycle's phase when a trigger switches it to triggered
    coach-observe (the cycle's coach)       ->  hook: an `observation` event by the coach, notes private
    coach-feedback (the coach)              ->  hook: private feedback; coaching_cycle `feedback`; due 5 working days after
                                                the observation (due rule `feedback_window`)
    practice-task (the coach)               ->  hook: private task text; coaching_cycle `practice`
    coach-reobserve (the coach)             ->  hook: a second `observation` event
    cycle-close (auto, per cycle)           ->  coaching_cycle `closed` with `change` per focus domain (re-observation score
                                                minus first), and the review of the instructor's CPD plan (flows/cpd.py)

Cadence and intensity (integration review finding 10). An instructor is always in a cycle: the next one opens as soon as the
latest closes (there is no wait; with no cycle yet it opens at once), so a cycle's period (`rules.coaching`: 91 days standard,
30 triggered) is the time it is given to finish, from the day it opened. Its steps have due dates inside the period (the
`cycle_*_due` rules below, from `info["opened_on"]` and `info["period_days"]`, which `derive_cycles` puts on the cycle's
subject). A cycle that has not closed shows its steps as overdue in `next` once their dates pass; it holds the next cycle
back only until it has run past the standard period (a stalled cycle), after which the next opens beside it, at most one
a period, and the stalled one stays in the queue. A cycle is triggered when a `check` event of H's quality review
({step: tm:step/quality-review, result: "trigger", trigger: <id>, domain?}, decision 0014) came after the instructor's
previous cycle opened or switched (a trigger is used once: the cycle it opens or switches takes it). A trigger that arrives
while a standard cycle is open switches it: a coaching_cycle event of the cycle's current phase carries intensity triggered
and the focus recomputed, `derive_cycles` makes the latest such event the cycle's intensity and focus for every reader of
`st.subjects`, and its period becomes 30 days from the day it opened. The focus is the trigger domains (at most two, the
lowest averaged first), else the two lowest-averaged domains of the
instructor's observations in the last COACHING_WINDOW_DAYS days (`cpd.choose_focus`/`domain_averages`). The coach is the
first of `common.coaches_of(instructor)` by hash rank; no coach, no unit the instructor delivers (a cycle observes one),
or no observation to set a focus from is a blocked `check` on the instructor, and the step runs again next time.

The re-observation's session date is not before the first observation's, nor before the day the practice task was set
(finding 18).

How the coach observes. The plan's wording was "an assignment with the coach as observer through W2". The workflow engine
cannot do that: an `assignment` step applies to every assignment, W2's own (a candidate's, whose `observe` needs the
candidate's approved batch and a signer holding the clearer role), and a step on `assignment` cannot be limited to the
coach's. So the coach's observations are steps of the cycle itself (`coach-observe`, `coach-reobserve`, role coach), and the
W2 machinery is reused where it is pure: `observation.evidence` validates the page (scores, notes, session date, the signer
must be the assigned observer, here the coach), the `observation` event is the same observation@2 a W2 release writes, and
the private evidence is kept the same way. There is no second observer, so there is nothing to keep blind and no release step:
the sign-off hook writes the event. Both pages carry the optional `from_recording` answer W2's observe page has, copied to the
event, so a partner's coach observations can count for a recording-only clearance (W11). A coach's observation counts for clearance like any other, so the coach limit in W4
(`rules.effective_observers`, via `coaches_of`) applies, and only if the coach was calibrated on the day.

Identity: the pages go to the cycle's coach (a mapped person holding the coach role signs as their instructor URI); a
sign-off by another coach is refused by a content check, since the engine's `signer` attribute only names signers of
assignments and candidates.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from .. import events, records, signoff
from .. import pages as pagegen
from ..due import due_rule
from ..util import iso_seconds, slug
from ..workflow import PROGRAMME, SYSTEM_ACTOR
from . import auto_step, content_check, on_signoff, register
from .common import (
    TARGET_LEVEL, PageProblem, State, bench_block, blocked_check, cached, coaches_of, current_level, observations, spec,
)
from .cpd import domain_averages, domain_order, review_plan
from .dry_run import _signed_at
from .observation import LENGTHS, MODES, _positions, evidence, rank
from .pathway import subject_event_id

STEP_OPEN = "tm:step/open-cycles"
STEP_OBSERVE = "tm:step/coach-observe"
STEP_FEEDBACK = "tm:step/coach-feedback"
STEP_PRACTICE = "tm:step/practice-task"
STEP_REOBSERVE = "tm:step/coach-reobserve"
STEP_CLOSE = "tm:step/cycle-close"
STEP_QUALITY = "tm:step/quality-review"  # H's step; read here by id only

COACHING_WINDOW_DAYS = 180   # the observations that set a cycle's focus (operational default, decision 0002)
FOCUS_COUNT = 2              # a cycle has one or two focus domains (standards/coaching-protocol.md)
FEEDBACK_WORKING_DAYS = 5    # standards/coaching-protocol.md step 2
FIRST, SECOND = "observe", "reobserve"  # the two observations of a cycle: the suffix of their delivery_ref
# Where in its period each human step of a cycle falls due, as (numerator, denominator) of the period: operational defaults
# (decision 0002), chosen so that the feedback window (5 working days after the observation) and the close still fit in a
# triggered cycle's 30 days.
OBSERVE_BY, PRACTICE_BY, REOBSERVE_BY, CLOSE_BY = (1, 4), (3, 5), (9, 10), (1, 1)


# --- pure helpers ------------------------------------------------------------------------------------------------


def add_working_days(start: date, days: int) -> date:
    """`start` moved on by `days` working days (Monday to Friday); the day itself is not counted, and a weekend start moves
    to the following working days. No public holidays: the calendar of the programme is not modelled."""
    day, counted = start, 0
    while counted < days:
        day += timedelta(days=1)
        if day.weekday() < 5:
            counted += 1
    return day


def cycle_uri(instructor: str, number: int) -> str:
    """`tm:cycle/<instructor slug>--<n>` (the form `events.check_event` requires of a cycle)."""
    return f"tm:cycle/{slug(instructor)}--{number}"


def delivery_ref(cycle: str, which: str) -> str:
    """The `delivery_ref` of an observation of the cycle: `<cycle slug>-observe` or `<cycle slug>-reobserve`."""
    return f"{slug(cycle)}-{which}"


def pick_coach(instructor: str, coaches: Collection[str]) -> str | None:
    """The first of `coaches` by hash rank (the rotation key of W2 observers, so the same instructor always gets the same
    coach for the same set); None when there is none."""
    return min(coaches, key=lambda c: (rank(instructor, c), c), default=None)


def choose_focus(averages: dict[str, float], order: Sequence[str], trigger_domains: Sequence[str]) -> list[str]:
    """The focus of a cycle: the trigger domains when any are framework domains (the lowest `FOCUS_COUNT` of them by average,
    a domain without an average last), else the `FOCUS_COUNT` lowest-averaged domains; ties by framework order. Empty when
    nothing names a domain and there is no average."""

    def lowest(domains: Sequence[str]) -> list[str]:
        ranked = sorted(domains, key=lambda d: (averages.get(d, float("inf")), order.index(d)))
        return ranked[:FOCUS_COUNT]

    named = [d for d in order if d in set(trigger_domains)]
    if named:
        return lowest(named)
    return lowest([d for d in order if d in averages])


# --- helpers over the state --------------------------------------------------------------------------------------


def delivered_units(st: State, instructor: str) -> list[str]:
    """The units in the instructor's registration `delivers`, sorted: the units a coach may observe them on."""
    delivers = (st.registrations.get(instructor) or {}).get("delivers") or []
    return sorted({d["unit"] for d in delivers if isinstance(d, dict) and isinstance(d.get("unit"), str)})


def _cycles_of(st: State, instructor: str) -> list[str]:
    """The URIs of the instructor's cycles, once per state."""
    def build() -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for uri, info in st.subjects.items():
            if info.get("kind") == "cycle":
                found.setdefault(info.get("instructor"), []).append(uri)
        return found

    return cached(st, "cycles_by_instructor", build).get(instructor, [])


def _switch_event(st: State, cycle: str) -> dict[str, Any] | None:
    """The first `coaching_cycle` event of the cycle whose intensity differs from the one it was opened with."""
    opening = st.index.of("subject", cycle)
    if not opening:
        return None
    opened_as = (opening[0]["payload"].get("attrs") or {}).get("intensity")
    return next((e for e in st.index.of("coaching_cycle", cycle) if e["payload"].get("intensity") != opened_as), None)


def _unused_triggers(st: State, instructor: str) -> list[dict[str, Any]]:
    """H's trigger `check` events about the instructor that no cycle has used yet: those after (in log order) the latest
    opening of one of their cycles or the switch of one to triggered. A cycle takes the triggers up to its opening, or the
    ones that switched it, once."""
    pos = _positions(st)
    mark = -1
    for uri in _cycles_of(st, instructor):
        mark = max([mark, *(pos[e["id"]] for e in st.index.of("subject", uri))])
        switch = _switch_event(st, uri)
        if switch is not None:
            mark = max(mark, pos[switch["id"]])
    return [e for e in st.index.of("check", instructor)
            if e["payload"].get("step") == STEP_QUALITY and e["payload"].get("result") == "trigger" and pos[e["id"]] > mark]


def _trigger_domains(triggers: list[dict[str, Any]]) -> list[str]:
    return [e["payload"]["domain"] for e in triggers if isinstance(e["payload"].get("domain"), str)]


def switch_event_id(cycle: str, trigger_event: str) -> str:
    return signoff.input_sha256({"cycle_intensity": [cycle, trigger_event]})[:32]


def _switch_intensity(st: State, latest: dict[str, Any], triggers: list[dict[str, Any]], order: Sequence[str],
                      now: datetime) -> list[dict[str, Any]]:
    """A trigger that arrived while a standard cycle is open switches it: a coaching_cycle event of the phase the cycle is
    in, with intensity triggered and the focus recomputed (the trigger domains, else the two lowest averaged; the cycle's
    own focus when there is none to compute). Nothing for a cycle that is already triggered (the next cycle takes the
    trigger) or when no trigger is unused. The id derives from the cycle and the last trigger, so a replay appends nothing."""
    uri = latest["cycle"]
    info = st.subjects[uri]
    if not triggers or info.get("intensity") != "standard":
        return []
    averages = domain_averages(observations(st), info["instructor"], now.date(), COACHING_WINDOW_DAYS)
    focus = choose_focus(averages, order, _trigger_domains(triggers)) or list(info["focus"])
    payload = _phase_payload({**info, "intensity": "triggered", "focus": focus}, uri, latest["phase"])
    return [events.make_event("coaching_cycle", uri, SYSTEM_ACTOR, payload, id=switch_event_id(uri, triggers[-1]["id"]),
                              at=iso_seconds(now))]


def derive_cycles(subjects: dict[str, dict[str, Any]], log: Sequence[dict[str, Any]],
                  coaching_rules: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Add what the log says about each cycle subject to its engine info, in place: `intensity` and `focus` from the latest
    `coaching_cycle` event (a switch to triggered changes them; the subject event's attrs are the cycle's identity and stay
    as opened), `opened_on` (the day of its `subject` event, ISO) and `period_days` (91 or 30 by the intensity, from
    `rules.coaching`). The due rules `cycle_*_due` and every reader of `st.subjects[cycle]` (the bench's repeated-trigger
    check among them) see the cycle as it is now. `app.load_state` and `advance_state` call this on the subjects they build."""
    cycles = {uri for uri, info in subjects.items() if info.get("kind") == "cycle"}
    if not cycles:
        return subjects
    opened: dict[str, str] = {}
    for e in log:
        uri = e["subject_uri"]
        if uri not in cycles:
            continue
        if e["kind"] == "subject":
            opened.setdefault(uri, e["at"][:10])
        elif e["kind"] == "coaching_cycle":
            p = e["payload"]
            if p.get("intensity") in ("standard", "triggered"):
                subjects[uri]["intensity"] = p["intensity"]
            if isinstance(p.get("focus"), list) and p["focus"]:
                subjects[uri]["focus"] = list(p["focus"])
    for uri in cycles:
        info = subjects[uri]
        info["opened_on"] = opened.get(uri)
        info["period_days"] = coaching_rules["triggered_cycle_days" if info.get("intensity") == "triggered"
                                             else "standard_cycle_days"]
    return subjects


def phase_event_id(cycle: str, phase: str) -> str:
    return signoff.input_sha256({"cycle_phase": [cycle, phase]})[:32]


def _phase_payload(info: dict[str, Any], cycle: str, phase: str, **extra: Any) -> dict[str, Any]:
    """A coaching-cycle@1 payload for the cycle (its `trigger` attribute is not part of the contract)."""
    return {"cycle": cycle, "instructor": info["instructor"], "coach": info["coach"], "number": info["number"],
            "intensity": info["intensity"], "focus": list(info["focus"]), "phase": phase, **extra}


# --- open-cycles -------------------------------------------------------------------------------------------------


@auto_step(STEP_OPEN, refresh=True)
def open_cycles(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    """The next cycle of each instructor at lead-observed or above (latest level; engagement active), or returned to
    co-teaching by a bench decision (decision 0015: "one returned to co-teaching is still coached"): a `subject` event and
    a coaching_cycle `opened` event, plus a `step` event {step, opened} on the programme the first time and whenever a cycle
    opened. It opens when the instructor's latest cycle is closed or has run past the standard period (stalled), or they have
    none; while a cycle is open and within its period it is left alone, except that an unused trigger switches a standard
    cycle to triggered (`_switch_intensity`). One that cannot be given a coach, a unit or a focus gets a blocked `check` (not
    repeated while the reasons stay the same). Replaying changes nothing."""
    stalled_after = st.standards["rules"]["coaching"]["standard_cycle_days"]
    levels = st.standards["framework"]["levels"]
    floor = levels.index(TARGET_LEVEL)
    order = domain_order(st)
    today = now.date()
    stamp = iso_seconds(now)
    existing = cached(st, "cycle_records", lambda: records.cycles(st.events))
    out: list[dict[str, Any]] = []
    opened: list[str] = []
    for instructor in sorted(st.registrations):
        level = current_level(st, instructor)
        block = bench_block(st, instructor, today)
        if block == "exit":  # decision 0015, finding 3
            continue
        if level not in levels or (levels.index(level) < floor and block != "return-to-co-teaching"):
            continue
        if (st.registrations[instructor].get("engagement") or {}).get("status", "active") != "active":
            continue
        mine = [c for c in existing if c["instructor"] == instructor]
        triggers = _unused_triggers(st, instructor)
        latest = max(mine, key=lambda c: c["number"], default=None)
        if latest is not None and latest["closed"] is None and today <= latest["opened"] + timedelta(days=stalled_after):
            # a cycle is open and still has its period: one at a time. A trigger arriving now switches it.
            out += _switch_intensity(st, latest, triggers, order, now)
            continue
        coach = pick_coach(instructor, {c for c in coaches_of(st, instructor) if c in st.registrations})
        reasons: list[str] = []
        if coach is None:
            reasons.append("no coach assigned")
        if not delivered_units(st, instructor):
            reasons.append("no unit delivered by the instructor on record to observe")
        averages = domain_averages(observations(st), instructor, today, COACHING_WINDOW_DAYS)
        focus = choose_focus(averages, order, _trigger_domains(triggers))
        if not focus:
            reasons.append(f"no observation in the last {COACHING_WINDOW_DAYS} days to choose a focus from")
        if reasons:
            out += blocked_check(st, STEP_OPEN, instructor, reasons, now)
            continue
        number = max((c["number"] for c in mine), default=0) + 1
        attrs: dict[str, Any] = {"instructor": instructor, "coach": coach, "number": number,
                                 "intensity": "triggered" if triggers else "standard", "focus": focus}
        if triggers:
            attrs["trigger"] = triggers[-1]["payload"]["trigger"]
        uri = cycle_uri(instructor, number)
        out.append(events.make_event(
            "subject", uri, SYSTEM_ACTOR, {"subject_kind": "cycle", "attrs": attrs, "opened_by": STEP_OPEN},
            id=subject_event_id(uri), at=stamp))
        out.append(events.make_event(
            "coaching_cycle", uri, SYSTEM_ACTOR, _phase_payload(attrs, uri, "opened"),
            id=phase_event_id(uri, "opened"), at=stamp))
        opened.append(uri)
    ran = any(e["payload"].get("step") == STEP_OPEN for e in st.index.of("step", PROGRAMME))
    if opened or not ran:
        out.append(events.make_event(
            "step", PROGRAMME, SYSTEM_ACTOR, {"step": STEP_OPEN, "opened": sorted(opened)},
            id=signoff.input_sha256({"open_cycles": sorted(opened)})[:32], at=stamp))
    return out


# --- the coach's pages -------------------------------------------------------------------------------------------


def _cycle(st: State, subject: str) -> dict[str, Any]:
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "cycle":
        raise PageProblem(f"{subject} is not a coaching cycle")
    return info


def _observation_event(st: State, info: dict[str, Any], cycle: str, which: str) -> dict[str, Any] | None:
    """The cycle's `observation` event of `which` (observe or reobserve), the latest if several; None before it exists."""
    ref = delivery_ref(cycle, which)
    found = [e for e in st.index.of("observation", info["instructor"]) if e["payload"].get("delivery_ref") == ref]
    return found[-1] if found else None


def _observe_page(st: State, step: str, cycle: str, which: str) -> list[dict[str, Any]]:
    info = _cycle(st, cycle)
    units = delivered_units(st, info["instructor"])
    if not units:
        raise PageProblem(f"{info['instructor']} delivers no unit on record to observe")
    minutes = st.standards["rules"]["clearance"]["short_observation_minutes"]
    inputs = {"cycle": cycle, "instructor": info["instructor"], "coach": info["coach"], "intensity": info["intensity"],
              "focus": list(info["focus"]), "observation": which, "units": units,
              "framework_version": st.standards["framework"]["version"]}
    fields = [
        {"name": "date", "label": "Date of the session observed", "kind": "date", "required": True},
        {"name": "unit", "label": "Unit observed", "kind": "enum", "options": units, "required": True},
        {"name": "length", "label": "Length observed", "kind": "enum", "options": list(LENGTHS), "required": True,
         "value": "full", "help": f"A short observation is {minutes} minutes."},
        {"name": "lead", "label": "The instructor led this session", "kind": "bool", "required": False, "value": True},
        {"name": "mode", "label": "Delivery mode observed", "kind": "enum", "options": list(MODES), "required": True},
        {"name": "from_recording", "label": "Scored from a recording", "kind": "bool", "required": False,
         "help": "Tick when you scored from a recording of the session. A partner instructor's clearance counts only "
                 "observations scored from recordings (W11)."},
        *pagegen.evidence_score_fields(st.standards),
    ]
    focus = ", ".join(info["focus"])
    intro = (f"Coaching cycle {info['number']} ({info['intensity']}), focus: {focus}. Score every domain against the anchors "
             "and give the evidence for each score; note a recording timestamp where you scored from video. ")
    intro += ("This is the first observation of the cycle; feedback on the focus domains follows within "
              f"{FEEDBACK_WORKING_DAYS} working days." if which == FIRST else
              "This is the re-observation: the cycle closes with the change in the focus domains.")
    return [spec(st, step, cycle, info["coach"], "approve", inputs, fields, intro)]


@register(STEP_OBSERVE)
def _b_observe(st: State, cycle: str):
    return _observe_page(st, STEP_OBSERVE, cycle, FIRST)


@register(STEP_REOBSERVE)
def _b_reobserve(st: State, cycle: str):
    return _observe_page(st, STEP_REOBSERVE, cycle, SECOND)


def _first_scores(st: State, info: dict[str, Any], cycle: str) -> tuple[str, dict[str, int]]:
    first = _observation_event(st, info, cycle, FIRST)
    if first is None:
        raise PageProblem(f"{cycle} has no first observation yet")
    return first["id"], first["payload"]["scores"]


def _focus_fields(info: dict[str, Any], prefixes: Sequence[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Required textareas for each focus domain: `(name prefix, label, help)` for each prefix."""
    return [{"name": f"{prefix}-{d}", "label": f"{label}: {d}", "kind": "textarea", "required": True, "help": hint}
            for d in info["focus"] for prefix, label, hint in prefixes]


@register(STEP_FEEDBACK)
def _b_feedback(st: State, cycle: str):
    info = _cycle(st, cycle)
    obs_id, scores = _first_scores(st, info, cycle)
    inputs = {"cycle": cycle, "instructor": info["instructor"], "coach": info["coach"], "focus": list(info["focus"]),
              "observation": obs_id, "focus_scores": {d: scores[d] for d in info["focus"] if d in scores}}
    fields = _focus_fields(info, (
        ("note", "Evidence note", "A specific moment from the observation that supports the feedback. Private."),
        ("feedback", "Feedback", "What went well and what to change, specific to the domain. Private.")))
    intro = (f"Give specific feedback on the focus domains within {FEEDBACK_WORKING_DAYS} working days of the observation. "
             "Your words stay in the private store; the record holds the phase and the sign-off only.")
    return [spec(st, STEP_FEEDBACK, cycle, info["coach"], "approve", inputs, fields, intro)]


@register(STEP_PRACTICE)
def _b_practice(st: State, cycle: str):
    info = _cycle(st, cycle)
    inputs = {"cycle": cycle, "instructor": info["instructor"], "coach": info["coach"], "focus": list(info["focus"])}
    fields = _focus_fields(info, (("task", "Practice task",
                                   "One concrete task to do before the next delivery. Private."),))
    intro = "Set one concrete practice task for each focus domain, to be done before the next delivery."
    return [spec(st, STEP_PRACTICE, cycle, info["coach"], "approve", inputs, fields, intro)]


# --- what a sign-off must be ---------------------------------------------------------------------------------------


def _observation_evidence(st: State, document: dict[str, Any], which: str) -> tuple[dict[str, Any] | None, list[str]]:
    """The coach's scores and notes from a stored observe or re-observe sign-off, or the reasons it cannot be used: the
    reasons of `observation.evidence` (the signer must be the cycle's coach, as its assigned observer), and a unit the
    instructor delivers."""
    cycle = document.get("subject_uri")
    info = st.subjects.get(cycle)
    if info is None or info.get("kind") != "cycle":
        return None, ["the subject is not a coaching cycle"]
    fields = document.get("fields") if isinstance(document.get("fields"), dict) else {}
    unit = fields.get("unit")
    reasons = [] if unit in delivered_units(st, info["instructor"]) else ["unit: one of the units the instructor delivers is required"]
    as_assignment = {"observer": info["coach"], "instructor": info["instructor"], "unit": unit,
                     "delivery_ref": delivery_ref(cycle, which)}
    data, more = evidence(document, as_assignment, st)
    reasons += [r.replace("assigned observer", "cycle's coach") for r in more]
    if data is not None and which == SECOND:
        reasons += _reobserve_date_reasons(st, info, cycle, data["date"])
    return (None, reasons) if reasons else (data, [])


def _reobserve_date_reasons(st: State, info: dict[str, Any], cycle: str, day: str) -> list[str]:
    """The re-observation cannot have been held before the first observation of the cycle, nor before the day the practice
    task was set (the day of its sign-off): it observes the practice. `day` is a valid ISO date (`observation.evidence`)."""
    held = date.fromisoformat(day)
    reasons: list[str] = []
    first = _observation_event(st, info, cycle, FIRST)
    if first is not None and held < date.fromisoformat(first["at"][:10]):
        reasons.append("date: the re-observation cannot be before the first observation of the cycle")
    practice = [e for e in st.index.of("coaching_cycle", cycle) if e["payload"].get("phase") == "practice"]
    if practice and held < date.fromisoformat(practice[-1]["at"][:10]):
        reasons.append("date: the re-observation cannot be before the day the practice task was set")
    return reasons


def _text_reasons(fields: Any, info: dict[str, Any], prefixes: Sequence[str]) -> list[str]:
    if not isinstance(fields, dict):
        return ["the sign-off carries no fields"]
    reasons = []
    for d in info["focus"]:
        for prefix in prefixes:
            value = fields.get(f"{prefix}-{d}")
            if not isinstance(value, str) or not value.strip():
                reasons.append(f"{prefix}-{d}: an answer is required")
    return reasons


def _coach_reasons(info: dict[str, Any], document: dict[str, Any]) -> list[str]:
    return [] if document.get("signer") == info["coach"] else ["signed by someone other than the cycle's coach"]


def _observe_check(which: str):
    def check(st: State, document: dict[str, Any]) -> list[str]:
        return _observation_evidence(st, document, which)[1]
    return check


content_check(STEP_OBSERVE)(_observe_check(FIRST))
content_check(STEP_REOBSERVE)(_observe_check(SECOND))


def _text_check(prefixes: Sequence[str]):
    def check(st: State, document: dict[str, Any]) -> list[str]:
        info = st.subjects.get(document.get("subject_uri"))
        if info is None or info.get("kind") != "cycle":
            return ["the subject is not a coaching cycle"]
        return _coach_reasons(info, document) + _text_reasons(document.get("fields"), info, prefixes)
    return check


content_check(STEP_FEEDBACK)(_text_check(("note", "feedback")))
content_check(STEP_PRACTICE)(_text_check(("task",)))


# --- the sign-off hooks ------------------------------------------------------------------------------------------


def _record_observation(which: str):
    def hook(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
        """The coach's `observation` event (observation@2, delivery_ref `<cycle slug>-<which>`) and the private evidence. A
        sign-off that cannot be used writes nothing (ingest refuses it first)."""
        cycle = signed["subject_uri"]
        data, _ = _observation_evidence(st, document, which)
        if data is None:
            return [], []
        info = st.subjects[cycle]
        key = f"evidence/{slug(cycle)}-{which}.json"
        payload = {
            "instructor": info["instructor"], "unit": data["unit"], "observer": info["coach"], "length": data["length"],
            "lead": data["lead"], "mode": data["mode"], "rubric_version": st.standards["rubric"]["framework_version"],
            "scores": data["scores"], "evidence_ref": key, "delivery_ref": delivery_ref(cycle, which),
            "recorded_at": data["recorded_at"],
        }
        if "from_recording" in data:
            payload["from_recording"] = data["from_recording"]  # W11: copied as W2's release does
        event = events.make_event(
            "observation", info["instructor"], info["coach"], payload,
            id=signoff.input_sha256({"observation_for_signoff": signed["payload"]["signoff_id"]})[:32],
            at=f"{data['date']}T00:00:00+00:00")
        return [event], [(key, data)]
    return hook


on_signoff(STEP_OBSERVE)(_record_observation(FIRST))
on_signoff(STEP_REOBSERVE)(_record_observation(SECOND))


def _record_text(phase: str, prefixes: Sequence[str], filename: str):
    def hook(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
        """The coaching_cycle event of the phase and the coach's words in the private store (coaching/<cycle slug>/)."""
        cycle, p = signed["subject_uri"], signed["payload"]
        info = st.subjects.get(cycle)
        if info is None or info.get("kind") != "cycle":
            return [], []
        fields = document.get("fields")
        if _coach_reasons(info, document) or _text_reasons(fields, info, prefixes):
            return [], []
        private = {"cycle": cycle, "signoff_id": p["signoff_id"], "answers": {
            d: {prefix: fields[f"{prefix}-{d}"].strip() for prefix in prefixes} for d in info["focus"]}}
        event = events.make_event(
            "coaching_cycle", cycle, signed["actor"], _phase_payload(info, cycle, phase, signoff_id=p["signoff_id"]),
            id=phase_event_id(cycle, phase), at=_signed_at(p.get("signed_at"), now))
        return [event], [(f"coaching/{slug(cycle)}/{filename}", private)]
    return hook


on_signoff(STEP_FEEDBACK)(_record_text("feedback", ("note", "feedback"), "feedback.json"))
on_signoff(STEP_PRACTICE)(_record_text("practice", ("task",), "practice.json"))


# --- cycle-close -------------------------------------------------------------------------------------------------


@auto_step(STEP_CLOSE, per="cycle")
def close_cycle(st: State, cycle: str, now: datetime) -> list[dict[str, Any]]:
    """The cycle's `closed` event once both observations are on record: `change` is the re-observation's score minus the first
    observation's for each focus domain. Reviews the instructor's CPD plan (`cpd.review_plan`) and names the gaps closed and
    kept on the `step` event that completes the step. Before the second observation exists, nothing."""
    info = st.subjects.get(cycle)
    if info is None or info.get("kind") != "cycle":
        return []
    first, second = _observation_event(st, info, cycle, FIRST), _observation_event(st, info, cycle, SECOND)
    if first is None or second is None:
        return []
    a, b = first["payload"]["scores"], second["payload"]["scores"]
    change = {d: b[d] - a[d] for d in info["focus"] if d in a and d in b}
    review = review_plan(st, info["instructor"], cycle)
    stamp = iso_seconds(now)
    closed = events.make_event(
        "coaching_cycle", cycle, SYSTEM_ACTOR, _phase_payload(info, cycle, "closed", change=change),
        id=phase_event_id(cycle, "closed"), at=stamp)
    done: dict[str, Any] = {"step": STEP_CLOSE, "observation_first": first["id"], "observation_second": second["id"]}
    if review is not None:
        done["cpd_review"] = {"closed": review["closed"], "kept": review["kept"]}  # the log's record of the gap review (W9)
    step = events.make_event("step", cycle, SYSTEM_ACTOR, done,
                             id=signoff.input_sha256({"cycle_closed": cycle})[:32], at=stamp)
    return [closed, step]


# --- due rules ---------------------------------------------------------------------------------------------------


def _period_due(share: tuple[int, int]):
    """A due rule for a step of a cycle: the day it opened (`info["opened_on"]`) plus `share` of its period
    (`info["period_days"]`: 91 days, or 30 once triggered), rounded up to whole days; no date for a cycle that has neither."""
    num, den = share

    def rule(step: dict[str, Any], subject: str, info: dict[str, Any], log: Sequence[dict[str, Any]], today: date) -> date | None:
        opened, days = info.get("opened_on"), info.get("period_days")
        if not isinstance(opened, str) or not isinstance(days, int):
            return None
        return date.fromisoformat(opened) + timedelta(days=-(-days * num // den))

    return rule


due_rule("cycle_observe_due")(_period_due(OBSERVE_BY))
due_rule("cycle_practice_due")(_period_due(PRACTICE_BY))
due_rule("cycle_reobserve_due")(_period_due(REOBSERVE_BY))
due_rule("cycle_end_due")(_period_due(CLOSE_BY))


@due_rule("feedback_window")
def feedback_window(step: dict[str, Any], subject: str, info: dict[str, Any], log: Sequence[dict[str, Any]],
                    today: date) -> date | None:
    """Feedback falls due FEEDBACK_WORKING_DAYS working days after the session of the cycle's first observation (standards/
    coaching-protocol.md step 2); no date before the observation exists."""
    ref = delivery_ref(subject, FIRST)
    held: date | None = None
    for e in log:
        if e["kind"] == "observation" and e["subject_uri"] == info.get("instructor") and e["payload"].get("delivery_ref") == ref:
            held = date.fromisoformat(e["at"][:10])
    return None if held is None else add_working_days(held, FEEDBACK_WORKING_DAYS)
