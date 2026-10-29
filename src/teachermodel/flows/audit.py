"""W6 observation audit (standards/workflows/audit.yaml): the quarterly sample, the second scoring and the result.

    draw-sample (auto, programme, refresh)  ->  one `sample` subject per observation `rules.audit_sample` picks for the quarter
    second-score (the second observer)      ->  nothing to do: the sign-off document is the record
    audit-result (auto, per sample)         ->  an `audit` event (audit@1) and, on low agreement, a referral to W5

Samples (integration review findings 6 and 20). A quarter's sample is drawn once, after the quarter has closed, over all its
live observations: the first run in the following quarter draws the quarter that just closed (`previous_quarter`, `2026Q4`),
reading the observations by the date of the observation, so one dated in the quarter but released after it ended is in the
population if it was released by that run. A quarter older than that is not drawn late, and a quarter is never drawn while it is
still open. W6 audits live observations: one whose event carries `from_recording: true` (observation@2, W11) was already scored
from a recording and is left out before `rules.audit_sample` runs, so the per-observer minimum and share are over the live ones
only. The draw is recorded by a `step` event {step, quarter, drawn: true, opened}, the first for the quarter; observations
released after it (later in the log) are not part of the quarter's population, so the sample is not topped up as they arrive.
The step is done after its first run and refreshes (like open-candidates). A refresh only completes a drawn quarter: for each
observer, the picks of `rules.audit_sample` over the population as it was at the draw (less the voided observations) that are
not yet open, at most as many as the picks exceed the samples already open: a pick that had no eligible second observer at
the draw, and the replacement of a voided sample. A re-run on the same log appends nothing and a sample once drawn is never
withdrawn.

The second observer of a sample is a calibrated clearer of the day (`observer_pool`), not the first observer, any other
observer of the sampled observation's delivery (every `observation` event with the same `delivery_ref`), the instructor or one of
the instructor's coaches (`coaches_of`), chosen by hash rank of (sample, candidate), so the choice does not depend on the pool's
order. A pick with no eligible second observer is not opened; a `check` {result: blocked} on the programme says how many, and
the next run tries again.

Eligibility is re-checked (decision 0015, amended). A second observer chosen on the day of the draw may stop being eligible
before they sign: they may become the instructor's coach (`coaches_of`) or lapse as a calibrated clearer (`observer_pool` on
the day). `second_observer_reasons` says so, and the content check of the second scoring refuses their sign-off on the
signing day (the sample stays open). On its next run `draw-sample` voids such a sample that has no second scoring yet: a
`check` {step: draw-sample, result: void, reasons} on the sample, the system's `step` event marked skipped that closes
second-score for its inputs (workflow `skippable`) and a `step` event {step: audit-result, void: true} that closes
audit-result, so nothing stays due for it. The sample URI and its attrs are immutable (a sample is identified by its quarter and
its observation), so a voided sample is not replaced by a new second observer: its observation is withdrawn from the quarter's
quota, and the same run draws the next-ranked observation of that observer in its place, if one exists in the quarter's
population at the draw. A voided observation is never drawn again; a sample that already has a second scoring is not voided.

Blindness. The second observer's page and its inputs hold the sample, the instructor, the unit, the mode and the delivery and
recording references, never the first observer's scores, notes or identity. The page builder reads only those fields of the
observation event. The step has no `signer` attribute (the enum has no `attrs.second_observer`), so `_score_content` refuses
any signer but the sample's second observer at ingest.

Result. `rules.calibration_pass(second, first)` gives the within-one and exact shares, with the first observer's scores as the
reference: the definitions and the thresholds of W5. `agreed` is its verdict. The `audit` event carries the shares and flags,
never a score. When not agreed, `referred_to_calibration` is true and a `check` {step, result: refer-to-calibration, observer}
is written on the sample; `records.lapses` then holds the audit date, and `rules.is_calibrated` treats the observer as not
calibrated from it until a pass dated after it (prospective, decision 0015).
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime
from typing import Any

from .. import events, rules, signoff, workflow
from .. import pages as pagegen
from ..standards import domain_ids
from ..util import iso_seconds
from . import auto_step, content_check, register
from .common import (
    PageProblem, State, cached, coaches_of, evidence_score_reasons, latest_day, observations, observer_pool, signed_scores, spec,
)
from .observation import _positions, rank  # rank: the same rotation key as W2's observers (a sample for a candidate)
from .pathway import subject_event_id

STEP_DRAW = "tm:step/draw-sample"
STEP_SCORE = "tm:step/second-score"
STEP_RESULT = "tm:step/audit-result"
REFER = "refer-to-calibration"
VOID = "void"


# --- naming ------------------------------------------------------------------------------------------------------


def quarter_id(day: date) -> str:
    """`2026Q4`: the calendar quarter of `day`, in the format of the `quarter` attribute of a sample (subject@2)."""
    return f"{day.year}Q{(day.month - 1) // 3 + 1}"


def sample_uri(quarter: str, observation: str) -> str:
    return f"tm:sample/{quarter}--{observation}"


def previous_quarter(day: date) -> str:
    """The quarter that closed most recently before `day`: `2026Q4` for any day of 2027Q1 (the quarter `day` is in is still
    open, or only just begun)."""
    q = (day.month - 1) // 3 + 1
    return f"{day.year - 1}Q4" if q == 1 else f"{day.year}Q{q - 1}"


def choose_second_observer(
    sample: str, instructor: str, first_observer: str, pool: Collection[str], coach_set: Collection[str],
    co_observers: Collection[str] = (),
) -> str | None:
    """The best-ranked of `pool` other than the instructor, the first observer, any other observer of the same delivery
    (`co_observers`) and the instructor's coaches; None when nobody is left. Independent of the pool's order."""
    eligible = set(pool) - {instructor, first_observer} - set(coach_set) - set(co_observers)
    return min(eligible, key=lambda o: (rank(sample, o), o), default=None)


def _observation_events(st: State) -> dict[str, dict[str, Any]]:
    """Event id -> the `observation` event, once per state."""
    return cached(st, "audit_observation_events",
                  lambda: {e["id"]: e for e in st.events if e["kind"] == "observation"})


def delivery_observers(st: State, observation: str) -> set[str]:
    """Everyone who observed the delivery of the `observation` event: its observer, and the observer of every `observation`
    event with the same `delivery_ref` (a delivery without a reference has only its own observer)."""
    def build() -> dict[str, set[str]]:
        found: dict[str, set[str]] = {}
        for e in _observation_events(st).values():
            if isinstance(e["payload"].get("delivery_ref"), str):
                found.setdefault(e["payload"]["delivery_ref"], set()).add(e["payload"]["observer"])
        return found

    event = _observation_events(st).get(observation)
    if event is None:
        return set()
    ref = event["payload"].get("delivery_ref")
    return {event["payload"]["observer"]} | (cached(st, "audit_delivery_observers", build).get(ref, set())
                                             if isinstance(ref, str) else set())


def _samples(st: State) -> dict[str, dict[str, Any]]:
    return {uri: info for uri, info in st.subjects.items() if info.get("kind") == "sample"}


def second_observer_reasons(st: State, info: dict[str, Any], on: date) -> list[str]:
    """Why the sample's second observer may not second-score it on the day `on`: not a calibrated clearer that day
    (`observer_pool`), one of the instructor's coaches now (`coaches_of`), or an observer of the sampled delivery
    (`delivery_observers`). Empty when they are still eligible."""
    second = info.get("second_observer")
    reasons: list[str] = []
    if second not in observer_pool(st, on):
        reasons.append(f"the second observer is no longer a calibrated clearer on {on.isoformat()}")
    if second in coaches_of(st, info["instructor"]):
        reasons.append("the second observer now coaches the instructor")
    if second in delivery_observers(st, info.get("observation")):
        reasons.append("the second observer observed the delivery that was sampled")
    return reasons


def _voided(st: State) -> set[str]:
    """The samples a `draw-sample` run voided."""
    return {uri for uri in _samples(st)
            if any(e["payload"].get("step") == STEP_DRAW and e["payload"].get("result") == VOID for e in st.index.of("check", uri))}


def _second_scored(st: State, sample: str) -> bool:
    """The sample has an accepted approving second-score sign-off."""
    return any(e["payload"].get("step") == STEP_SCORE and e["payload"].get("decision") in workflow.APPROVING
               for e in st.index.of("signoff", sample))


def _void_events(st: State, sample: str, reasons: list[str], stamp: str) -> list[dict[str, Any]]:
    """The events that void `sample`: the `check`, the skip of second-score for the inputs its page would show (when the page
    can be built), and the close of audit-result."""
    out = [events.make_event("check", sample, workflow.SYSTEM_ACTOR, {"step": STEP_DRAW, "result": VOID, "reasons": reasons},
                             id=signoff.input_sha256({"sample_void": sample})[:32], at=stamp)]
    try:
        inputs = _b_score(st, sample)[0]["inputs"]
    except (PageProblem, KeyError):
        inputs = None
    if inputs is not None:
        sha = signoff.input_sha256(inputs)
        out.append(events.make_event(
            "step", sample, workflow.SYSTEM_ACTOR,
            {"step": STEP_SCORE, "skipped": True, "reason": "the sample was voided", "input_sha256": sha},
            id=signoff.input_sha256({"sample_skipped": [sample, sha]})[:32], at=stamp))
    out.append(events.make_event(
        "step", sample, workflow.SYSTEM_ACTOR, {"step": STEP_RESULT, "void": True},
        id=signoff.input_sha256({"sample_void_closed": sample})[:32], at=stamp))
    return out


def _sample(st: State, subject: str) -> dict[str, Any]:
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "sample":
        raise PageProblem(f"{subject} is not a sample")
    return info


# --- draw-sample -------------------------------------------------------------------------------------------------


@auto_step(STEP_DRAW, refresh=True)
def draw_sample(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    """The events that draw the sample of the quarter that just closed, if it is not drawn yet (the `subject` events of the
    samples and a `step` event {step, quarter, drawn: true, opened}); the samples a drawn quarter still lacks (a `step`
    event {step, quarter, opened} for them); a `step` event {step, quarter, opened: []} the first time the step runs with
    nothing to draw; a `check` {result: blocked} when a pick has no eligible second observer; and the events that void an open
    sample whose second observer is no longer eligible. See the module docstring."""
    day = now.date()
    stamp = iso_seconds(now)
    out: list[dict[str, Any]] = []
    voided = _voided(st)
    for uri, info in sorted(_samples(st).items()):
        if uri in voided or st.index.of("audit", uri) or _second_scored(st, uri):
            continue
        why = second_observer_reasons(st, info, day)
        if why:
            out += _void_events(st, uri, why, stamp)
            voided.add(uri)
    voided_observations = {info.get("observation") for uri, info in _samples(st).items() if uri in voided}
    recorded = {i for i, e in _observation_events(st).items() if e["payload"].get("from_recording") is True}
    marks = _draws(st)
    closed = previous_quarter(day)
    where = _positions(st)
    pool = observer_pool(st, day)
    wrote = False
    for quarter in sorted({*marks, closed}):
        mark = marks.get(quarter)
        # The population is the quarter's live observations dated in it (not the date they were released), as the log stood
        # when the quarter was drawn: a later release neither tops up the sample nor shifts its picks.
        live = [o for o in observations(st) if quarter_id(o.at) == quarter and o.id not in recorded
                and o.id not in voided_observations and (mark is None or where[o.id] < where[mark["id"]])]
        if mark is None and not live:
            continue
        by_id = {o.id: o for o in live}
        open_now = [info for uri, info in _samples(st).items() if info.get("quarter") == quarter and uri not in voided]
        opened_ids = {info.get("observation") for info in open_now}
        picks_by_observer: dict[str, list[str]] = {}
        for oid in rules.audit_sample(live, quarter, st.standards["rules"]):
            picks_by_observer.setdefault(by_id[oid].observer, []).append(oid)
        lacking = 0
        opened: list[str] = []
        for observer, picks in sorted(picks_by_observer.items()):
            room = len(picks) - sum(1 for info in open_now if info.get("observer") == observer)
            for oid in [p for p in picks if p not in opened_ids][:max(room, 0)]:
                o = by_id[oid]
                uri = sample_uri(quarter, oid)
                second = choose_second_observer(uri, o.instructor, o.observer, pool, coaches_of(st, o.instructor),
                                                delivery_observers(st, oid))
                event = None if second is None else events.make_event(
                    "subject", uri, workflow.SYSTEM_ACTOR,
                    {"subject_kind": "sample", "opened_by": STEP_DRAW,
                     "attrs": {"observation": oid, "instructor": o.instructor, "observer": o.observer, "quarter": quarter,
                               "second_observer": second}},
                    id=subject_event_id(uri), at=stamp)
                if event is None or events.check_event(event):
                    lacking += 1
                    continue
                out.append(event)
                opened.append(uri)
        if mark is None:
            payload = {"step": STEP_DRAW, "quarter": quarter, "drawn": True, "opened": sorted(opened)}
            step_id = signoff.input_sha256({"draw_sample": [quarter, "drawn"]})[:32]
        else:
            payload = {"step": STEP_DRAW, "quarter": quarter, "opened": sorted(opened)}
            step_id = signoff.input_sha256({"draw_sample": [quarter, sorted(opened)]})[:32]
        if mark is None or opened:
            out.append(events.make_event("step", workflow.PROGRAMME, workflow.SYSTEM_ACTOR, payload, id=step_id, at=stamp))
            wrote = True
        if lacking:
            reasons = [f"{lacking} sampled observation(s) of {quarter} have no eligible second observer (a clearer calibrated "
                       "today other than the first observer, any other observer of the delivery, the instructor and the "
                       "instructor's coaches)"]
            out.append(events.make_event(
                "check", workflow.PROGRAMME, workflow.SYSTEM_ACTOR,
                {"step": STEP_DRAW, "result": "blocked", "reasons": reasons},
                id=signoff.input_sha256({"draw_blocked": [quarter, reasons]})[:32], at=stamp))
    ran = any(e["payload"].get("step") == STEP_DRAW for e in st.index.of("step", workflow.PROGRAMME))
    if not ran and not wrote:
        out.append(events.make_event(
            "step", workflow.PROGRAMME, workflow.SYSTEM_ACTOR, {"step": STEP_DRAW, "quarter": closed, "opened": []},
            id=signoff.input_sha256({"draw_sample": [closed, []]})[:32], at=stamp))
    return out


def _draws(st: State) -> dict[str, dict[str, Any]]:
    """Quarter -> the first `step` event that recorded its draw (`drawn: true`)."""
    found: dict[str, dict[str, Any]] = {}
    for e in st.index.of("step", workflow.PROGRAMME):
        p = e["payload"]
        if p.get("step") == STEP_DRAW and p.get("drawn") is True and isinstance(p.get("quarter"), str):
            found.setdefault(p["quarter"], e)
    return found


# --- second-score ------------------------------------------------------------------------------------------------


@register(STEP_SCORE)
def _b_score(st: State, subject: str) -> list[dict[str, Any]]:
    """The second observer's page: an `evidence_score` per domain. It names the recording of the delivery and nothing the
    first observer entered; of the observation event it reads the unit, mode, delivery and assignment references only."""
    info = _sample(st, subject)
    second = info.get("second_observer")
    if not isinstance(second, str) or second in (info.get("observer"), info.get("instructor")):
        raise PageProblem(f"{subject} has no usable second observer")
    event = _observation_events(st).get(info.get("observation"))
    if event is None:
        raise PageProblem(f"the observation drawn for {subject} is not on record")
    p = event["payload"]
    inputs: dict[str, Any] = {"sample": subject, "instructor": info["instructor"], "unit": p["unit"],
                              "rubric_version": st.standards["rubric"]["framework_version"],
                              "rubric_sha256": signoff.input_sha256(st.standards["rubric"])}
    if isinstance(p.get("mode"), str):
        inputs["mode"] = p["mode"]
    if isinstance(p.get("delivery_ref"), str):
        inputs["delivery_ref"] = p["delivery_ref"]
    recording = st.subjects.get(p.get("assignment"), {}).get("recording_ref") if isinstance(p.get("assignment"), str) else None
    if isinstance(recording, str) and recording:
        inputs["recording_ref"] = recording
    return [spec(st, STEP_SCORE, subject, second, "approve", inputs, pagegen.evidence_score_fields(st.standards),
                 intro="This observation was drawn for the quarterly audit. Watch the recording of the delivery and score it "
                       "against the rubric, one score and one evidence note per domain; note a recording timestamp for each. "
                       "You cannot see the first observer's scores, and should not look for them: the audit is only worth "
                       "something if you score independently.")]


def _signing_day(st: State, document: dict[str, Any]) -> date:
    """The day the sign-off says it was signed; if it cannot be read, the ingest clock, else the newest event of the log."""
    try:
        return datetime.fromisoformat(str(document.get("signed_at")).replace("Z", "+00:00")).date()
    except ValueError:
        now = st.cache.get("now")
        return now.date() if isinstance(now, datetime) else (latest_day(st) or date.min)


@content_check(STEP_SCORE)
def _score_content(st: State, document: dict[str, Any]) -> list[str]:
    """Ingest refuses a second scoring signed by anyone but the sample's second observer, and one whose scores the result
    could not use (a score of 1-4 and a note for every domain)."""
    info = st.subjects.get(document.get("subject_uri"))
    if info is None or info.get("kind") != "sample":
        return ["the subject is not a sample"]
    reasons = [] if document.get("signer") == info.get("second_observer") else [
        "signer: signed by someone other than the second observer of this sample"]
    if document.get("subject_uri") in _voided(st):
        reasons.append("the sample was voided: its second observer was no longer eligible")
    reasons += second_observer_reasons(st, info, _signing_day(st, document))
    return reasons + evidence_score_reasons(document.get("fields"), domain_ids(st.root))


# --- audit-result ------------------------------------------------------------------------------------------------


def _blocked(sample: str, reason: str, stamp: str) -> list[dict[str, Any]]:
    return [events.make_event(
        "check", sample, workflow.SYSTEM_ACTOR, {"step": STEP_RESULT, "result": "blocked", "reasons": [reason]},
        id=signoff.input_sha256({"audit_blocked": [sample, reason]})[:32], at=stamp)]


@auto_step(STEP_RESULT, per="sample")
def audit_result(st: State, sample: str, now: datetime) -> list[dict[str, Any]]:
    """Nothing until the second observer has submitted. Then the `audit` event (agreement between the two scorings, by
    `rules.calibration_pass` with the first observer's scores as the reference), a `check` {result: refer-to-calibration}
    when it did not agree, and a `step` event that closes the step. A scoring that cannot be compared gives a `check`
    {result: blocked}, once. Ids derive from the sample, so a replay appends nothing."""
    info = st.subjects.get(sample)
    if info is None or info.get("kind") != "sample" or st.index.of("audit", sample):
        return []
    domains = domain_ids(st.root)
    second = signed_scores(st, sample, STEP_SCORE, info["second_observer"], domains)
    if second is None:
        return []
    sid, scores = second
    stamp = iso_seconds(now)
    first = _observation_events(st).get(info["observation"])
    if first is None:
        return _blocked(sample, "the observation drawn is not on record", stamp)
    verdict = rules.calibration_pass(scores, first["payload"]["scores"], st.standards["rules"])
    if "within_one" not in verdict.detail:
        return _blocked(sample, "the two scorings do not cover the same domains", stamp)
    payload = {"sample": sample, "observation": info["observation"], "observer": info["observer"],
               "second_observer": info["second_observer"], "within_one_share": verdict.detail["within_one"],
               "exact_share": verdict.detail["exact"], "agreed": verdict.ok, "referred_to_calibration": not verdict.ok,
               "signoff_id": sid}
    out = [events.make_event("audit", sample, workflow.SYSTEM_ACTOR, payload,
                             id=signoff.input_sha256({"audit": sample})[:32], at=stamp)]
    if not verdict.ok:
        out.append(events.make_event(
            "check", sample, workflow.SYSTEM_ACTOR, {"step": STEP_RESULT, "result": REFER, "observer": info["observer"]},
            id=signoff.input_sha256({"audit_referral": sample})[:32], at=stamp))
    out.append(events.make_event(
        "step", sample, workflow.SYSTEM_ACTOR, {"step": STEP_RESULT, "agreed": verdict.ok},
        id=signoff.input_sha256({"audit_result": sample})[:32], at=stamp))
    return out
