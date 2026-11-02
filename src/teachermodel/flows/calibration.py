"""The W5 calibration workflow (standards/workflows/calibration.yaml): exercises, scoring pages and the result step.

An exercise is a child subject (`tm:exercise/<16 hex>`) opened by the head of training with `teachermodel open-exercise`:
a recording kept in the private store, the observers who score it, and the reference score per framework domain, which
is a private document (`calibration/<exercise>.reference.json`) and never enters an event or a page.

An exercise has two or more observers (spec v0.2 W5 step 1: they score the same pre-scored recording independently).
Each listed observer gets a scoring page (`calibration-score`, an `evidence_score` per domain). When every listed observer
has an accepted approving sign-off, the auto step `calibration-result` computes `rules.calibration_pass` for each against
the reference, and their agreement against each other (`rules.inter_observer_agreement`, W5 step 2: reported in the
optional `inter_observer` field, never part of pass or fail), writes one `calibration` event per observer and a `step`
event that closes both steps (the engine models one step per subject, so the second observer's page must stay open until
then; see the workflow file). The `step` event records the `renewal_months` of the rules the result was computed under.

The due rule `clearer_renewal` also lives here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from .. import events, rules, signoff, units, workflow
from .. import pages as pagegen
from ..due import due_rule
from ..records import calibrations as passed_calibrations
from ..records import lapses as referral_lapses
from ..standards import ROOT, domain_ids, load_standards, load_yaml
from ..util import iso_seconds, slug
from . import auto_step, content_check, on_signoff, register
from .common import (
    HEAD_ROLE, is_head,
    PageProblem, State, bench_block, calibrations, clearer_instructors, current_level, evidence_score_reasons, is_calibrated_on,
    lapses, people_with, signed_scores, spec, _SIGNOFF_ID,
)
from .pathway import subject_event_id

STEP_SCORE = "tm:step/calibration-score"
STEP_RESULT = "tm:step/calibration-result"
STEP_OPEN_RECAL = "tm:step/open-recalibrations"
STEP_RECAL = "tm:step/recalibration-exercise"
RENEW_AHEAD_DAYS = 30  # a calibration is renewed this long before it lapses (operational default, decision 0002)
OPENED_BY = "tm:cli/open-exercise"
EVENT_LOG = "events/events.jsonl"
REFERENCE_DIR = "calibration"  # under the private dir: <exercise hex>.reference.json
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
_KEY = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/]*\Z")  # a key into the private store: no scheme, drive, space or ..


MIN_OBSERVERS = 2  # spec v0.2 W5 step 1: two or more observers score the same recording
DETAIL_EXERCISES = 6  # how many recent results an observer's detail covers (operational default, decision 0002)


class ExerciseError(Exception):
    """`open-exercise` refused its input; the message says what to fix."""


@dataclass(frozen=True)
class Opened:
    exercise: str  # the exercise URI
    created: bool  # False when the same exercise was already open


# --- the command: open-exercise ---------------------------------------------------------------------------


def exercise_uri(unit: str, recording_ref: str, observers: list[str], opened_on: date) -> str:
    """Deterministic URI: the same unit, recording and observers opened on one day are one exercise (a replay opens
    nothing twice); a later day opens a new one, so the same recording can renew a calibration."""
    digest = signoff.input_sha256(
        {"exercise": [unit, recording_ref, sorted(observers), opened_on.isoformat()]})
    return f"tm:exercise/{digest[:16]}"


def _scores(doc: Any, domains: list[str]) -> dict[str, int]:
    """The reference scores of `doc` (domain id -> 1-4). Raises ExerciseError, naming domains and never the file text."""
    if not isinstance(doc, dict):
        raise ExerciseError("the reference must be a mapping of framework domain id to a score (1-4)")
    missing = [d for d in domains if d not in doc]
    unknown = sorted(str(k) for k in doc if k not in domains)
    problems: list[str] = []
    if missing:
        problems.append("the reference is missing domain(s) " + ", ".join(missing))
    if unknown:
        problems.append("the reference has unknown domain(s) " + ", ".join(unknown))
    for d in domains:
        v = doc.get(d)
        if d in doc and not (type(v) is int and 1 <= v <= 4):
            problems.append(f"{d}: the score must be a whole number 1-4")
    if problems:
        raise ExerciseError("; ".join(problems))
    return {d: doc[d] for d in domains}


def _read_reference(path: Path | str, domains: list[str]) -> dict[str, int]:
    p = Path(path)
    if not p.is_file():
        raise ExerciseError(f"{p}: no such file")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))  # YAML, so JSON too
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ExerciseError(f"{p.name}: not readable as YAML or JSON") from None
    return _scores(doc, domains)


def _observer_uri(raw: str) -> str:
    name = raw.strip().removeprefix("tm:instructor/")
    if not _SLUG.match(name):
        raise ExerciseError(f"{raw!r} is not an instructor (give tm:instructor/<slug> or the bare slug)")
    return f"tm:instructor/{name}"


def _write_json(target: Path, document: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _reference_key(exercise: str) -> str:
    return f"{REFERENCE_DIR}/{slug(exercise)}.reference.json"


def _exercise_event(uri: str, unit: str, rubric_version: str, recording_ref: str, observers: list[str], key: str,
                    opened_by: str, at: str) -> dict[str, Any]:
    """The `subject` event that opens an exercise."""
    return events.make_event(
        "subject", uri, workflow.SYSTEM_ACTOR,
        {"subject_kind": "exercise",
         "attrs": {"unit": unit, "rubric_version": rubric_version, "recording_ref": recording_ref,
                   "observers": observers, "reference_key": key},
         "opened_by": opened_by},
        id=subject_event_id(uri), at=at)


def open_exercise(
    private_dir: Path | str, *, unit: str, recording_ref: str, observers: list[str], reference: Path | str,
    now: datetime | None = None, root: Path = ROOT,
) -> Opened:
    """Open a calibration exercise: validate everything, store the reference scores privately, then append the
    `exercise` subject event (the last write, so a refusal leaves the log untouched). Raises ExerciseError.

    `observers` are `tm:instructor/<slug>` URIs or bare slugs, each a registered instructor. `reference` is a YAML or JSON
    file mapping every framework domain to a score 1-4. The scores go to `calibration/<exercise>.reference.json` under
    the private dir; the event holds only that key."""
    now = now or datetime.now(timezone.utc)
    private = Path(private_dir)
    try:
        units.load(unit, root)
    except units.UnitError as exc:
        raise ExerciseError(f"unit: {exc}") from None
    if not isinstance(recording_ref, str) or not _KEY.match(recording_ref) or ".." in recording_ref.split("/"):
        raise ExerciseError("recording: give a key into the private store (for example recordings/<id>.mp4), "
                            "not a link, a drive path or a name with spaces")
    uris = [_observer_uri(o) for o in observers]
    if len(set(uris)) != len(uris):
        raise ExerciseError("an observer is listed twice")
    if len(uris) < MIN_OBSERVERS:
        raise ExerciseError("give at least two observers: they score the same recording independently (spec W5)")
    log_path = private / EVENT_LOG
    log = list(events.read(log_path)) if log_path.is_file() else []
    registered = {e["subject_uri"] for e in log if e["kind"] == "registration"}
    unknown = [u for u in uris if u not in registered]
    if unknown:
        raise ExerciseError("not a registered instructor: " + ", ".join(unknown))
    scores = _read_reference(reference, domain_ids(root))
    rubric_version = load_standards(root)["rubric"]["framework_version"]

    uri = exercise_uri(unit, recording_ref, uris, now.astimezone(timezone.utc).date())
    key = _reference_key(uri)
    stored = private / key
    existing = next((e for e in log if e["kind"] == "subject" and e["subject_uri"] == uri), None)
    if stored.is_file():
        try:
            same = json.loads(stored.read_text(encoding="utf-8")).get("scores") == scores
        except (OSError, ValueError, AttributeError):
            same = False
        if not same:
            raise ExerciseError(f"{uri} is already open with a different reference; open a new exercise instead")
    else:
        _write_json(stored, {"schema": "tm:calibration-reference@1", "exercise": uri, "unit": unit, "scores": scores})
    if existing is not None:
        return Opened(uri, False)
    events.append(log_path, _exercise_event(uri, unit, rubric_version, recording_ref, sorted(uris), key, OPENED_BY,
                                            iso_seconds(now)))
    return Opened(uri, True)


# --- the scoring page --------------------------------------------------------------------------------------


@register(STEP_SCORE)
def _b_score(st: State, subject: str) -> list[dict[str, Any]]:
    """One page per listed observer, all with the same inputs (the engine needs one input hash per step). The
    reference scores and their key are not among them."""
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "exercise":
        raise PageProblem(f"{subject} is not an exercise")
    observers = info.get("observers")
    if not (isinstance(observers, list) and observers and all(isinstance(o, str) for o in observers)):
        raise PageProblem(f"{subject} lists no observers")
    inputs = {"exercise": subject, "unit": info["unit"], "rubric_version": info["rubric_version"],
              "rubric_sha256": signoff.input_sha256(st.standards["rubric"]), "recording_ref": info["recording_ref"]}
    return [
        spec(st, STEP_SCORE, subject, o, "approve", inputs, pagegen.evidence_score_fields(st.standards),
             intro="Watch the recording and score it against the rubric, one score and one evidence note per domain. "
                   "Score what you see, not what you expect the reference to be.")
        for o in sorted(observers)
    ]


@content_check(STEP_SCORE)
def _score_content(st: State, document: dict[str, Any]) -> list[str]:
    """Ingest refuses scores that `calibration_result` could not use: every domain needs a score of 1-4 and a note."""
    return evidence_score_reasons(document.get("fields"), domain_ids(st.root))


# --- the result step ---------------------------------------------------------------------------------------


def _reference_in(private: Path, info: dict[str, Any], domains: list[str]) -> dict[str, int] | str:
    """The reference scores from the private store, or the reason they cannot be used."""
    key = info.get("reference_key")
    path = (private / str(key)).resolve()
    if not isinstance(key, str) or not path.is_relative_to(private.resolve()) or not path.is_file():
        return "the reference scores are missing from the private store"
    try:
        return _scores(json.loads(path.read_text(encoding="utf-8")).get("scores"), domains)
    except (OSError, ValueError, AttributeError, ExerciseError):
        return "the reference scores in the private store do not cover the framework domains"


def _reference(st: State, info: dict[str, Any], domains: list[str]) -> dict[str, int] | str:
    return _reference_in(st.private, info, domains)


@auto_step(STEP_RESULT, per="exercise")
def calibration_result(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    """Nothing until every listed observer has submitted. Then one `calibration` event per observer (computed by
    `rules.calibration_pass` against the private reference) and a `step` event on the exercise that closes the
    scoring step. A reference that cannot be read gives a `check` event {result: blocked} instead, once."""
    info = st.subjects[subject]
    domains = domain_ids(st.root)
    observers = sorted(info["observers"])
    stamp = iso_seconds(now)
    submitted = {o: signed_scores(st, subject, STEP_SCORE, o, domains) for o in observers}
    if any(s is None for s in submitted.values()):
        return []
    reference = _reference(st, info, domains)
    if isinstance(reference, str):
        return [events.make_event(
            "check", subject, workflow.SYSTEM_ACTOR, {"step": STEP_RESULT, "result": "blocked", "reason": reference},
            id=signoff.input_sha256({"calibration_blocked": [subject, reference]})[:32], at=stamp)]
    out: list[dict[str, Any]] = []
    agreement = rules.inter_observer_agreement({o: submitted[o][1] for o in observers})  # type: ignore[index]
    for observer in observers:
        sid, scores = submitted[observer]  # type: ignore[misc] - checked above
        verdict = rules.calibration_pass(scores, reference, st.standards["rules"])
        payload = {"exercise": subject, "observer": observer, "unit": info["unit"],
                   "rubric_version": info["rubric_version"], "within_one_share": verdict.detail["within_one"],
                   "exact_share": verdict.detail["exact"], "passed": verdict.ok, "signoff_id": sid}
        if observer in agreement:
            payload["inter_observer"] = agreement[observer]
        out.append(events.make_event("calibration", observer, workflow.SYSTEM_ACTOR, payload,
                                     id=signoff.input_sha256({"calibration": [subject, observer]})[:32], at=stamp))
    out.append(events.make_event(
        "step", subject, workflow.SYSTEM_ACTOR,
        {"step": STEP_RESULT, "observers": observers,
         "renewal_months": st.standards["rules"]["calibration"]["renewal_months"]},
        id=signoff.input_sha256({"calibration_result": subject})[:32], at=stamp))
    return out


# --- the observer's detail: how they score against the reference (decision 0032) ------------------------------


def _signed_on(private: Path, signoff_id: Any, domains: list[str]) -> dict[str, int] | None:
    """The scores in one stored sign-off, never its notes; None when it is gone or incomplete."""
    if not (isinstance(signoff_id, str) and _SIGNOFF_ID.match(signoff_id)):
        return None
    try:
        fields = json.loads((private / "signoffs" / f"{signoff_id}.json").read_text(encoding="utf-8"))["fields"]
        return {d: fields[d]["score"] for d in domains}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def observer_detail(private: Path, log: list[dict[str, Any]], observer: str, domains: list[str],
                    today: date) -> dict[str, Any] | None:
    """An observer's last `DETAIL_EXERCISES` results: agreement per exercise from the events, and their own score minus
    the reference per domain, computed when asked from the two private documents that already exist, so the difference
    is kept nowhere. It is an average across exercises and names no exercise or recording. None if never scored."""
    results = [e for e in log if e["kind"] == "calibration" and e["payload"].get("observer") == observer]
    if not results:
        return None
    infos = {e["subject_uri"]: e["payload"].get("attrs") or {} for e in log
             if e["kind"] == "subject" and e["payload"].get("subject_kind") == "exercise"}
    recent = sorted(results, key=lambda e: e["at"])[-DETAIL_EXERCISES:]
    pairs = []
    for e in recent:
        scores = _signed_on(private, e["payload"].get("signoff_id"), domains)
        reference = _reference_in(private, infos.get(e["payload"].get("exercise")) or {}, domains)
        if scores is not None and not isinstance(reference, str):
            pairs.append((scores, reference))
    passed = [e["at"][:10] for e in results if e["payload"].get("passed") is True]
    renew = clearer_renewal({}, observer, {"kind": "instructor"}, log, today)
    return {"exercises": [{"at": e["at"][:10], "within_one_share": e["payload"].get("within_one_share"),
                           "exact_share": e["payload"].get("exact_share"), "passed": e["payload"].get("passed") is True}
                          for e in recent],
            "bias": rules.calibration_bias(pairs), "counted": len(pairs),
            "last_passed": max(passed, default=None), "renew_by": renew.isoformat() if renew else None}


# --- recalibration: the head's page when a clearer's calibration lapses or is about to -----------------------


def _exercises_listing(st: State, instructor: str) -> list[str]:
    return sorted(u for u, info in st.subjects.items()
                  if info.get("kind") == "exercise" and instructor in (info.get("observers") or []))


def _awaiting_result(st: State, exercise: str) -> bool:
    return not any(e["payload"].get("step") == STEP_RESULT for e in st.index.of("step", exercise))


def recalibration_uri(instructor: str, exercises: int) -> str:
    """One recalibration per instructor and number of exercises they were listed in: opening an exercise for them, or a
    failed one, makes the next need a new subject."""
    return "tm:recalibration/" + signoff.input_sha256({"recalibration": [instructor, exercises]})[:16]


def clearers_ever(st: State) -> list[str]:
    """Registered instructors who hold clearer now or held it once and are at cleared since (a calibration lapse moves a
    clearer back to cleared, `levels`). Sorted."""
    now = set(clearer_instructors(st.registrations, st.events, st.people))
    were = {e["subject_uri"] for e in st.events if e["kind"] == "level_change" and e["payload"].get("from") == "clearer"}
    return sorted(now | {i for i in were if i in st.registrations and current_level(st, i) == "cleared"})


def needs_recalibration(st: State, instructor: str, today: date) -> bool:
    """Not calibrated `RENEW_AHEAD_DAYS` from `today` (lapsed, referred by an audit, or never passed), no exercise of
    theirs still awaiting its result, and no blocking bench decision (they are cleared again before they observe)."""
    return (bench_block(st, instructor, today) is None
            and not is_calibrated_on(st, instructor, today + timedelta(days=RENEW_AHEAD_DAYS))
            and not any(_awaiting_result(st, x) for x in _exercises_listing(st, instructor)))


@auto_step(STEP_OPEN_RECAL, refresh=True)
def open_recalibrations(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    """A `recalibration` subject for each clearer, current or lapsed (`clearers_ever`), who `needs_recalibration`, and a
    system `check` {result: closed} on an open one once an exercise lists the instructor (from the head's page or from
    `open-exercise`), or the need has gone. A `step` event the first time and whenever something changed."""
    today, stamp = now.date(), iso_seconds(now)
    out: list[dict[str, Any]] = []
    for instructor in clearers_ever(st):
        if not needs_recalibration(st, instructor, today):
            continue
        n = len(_exercises_listing(st, instructor))
        uri = recalibration_uri(instructor, n)
        if uri in st.subjects:
            continue
        out.append(events.make_event(
            "subject", uri, workflow.SYSTEM_ACTOR,
            {"subject_kind": "recalibration", "attrs": {"instructor": instructor, "exercises": n},
             "opened_by": STEP_OPEN_RECAL},
            id=subject_event_id(uri), at=stamp))
    for uri, info in sorted(st.subjects.items()):
        if info.get("kind") != "recalibration" or workflow.is_closed(uri, st.subjects, st.index):
            continue
        instructor = info["instructor"]
        listed = len(_exercises_listing(st, instructor)) > info["exercises"]
        if listed or not needs_recalibration(st, instructor, today):
            reason = "an exercise lists the instructor" if listed else "no longer needed"
            out.append(events.make_event(
                "check", uri, workflow.SYSTEM_ACTOR, {"step": STEP_OPEN_RECAL, "result": "closed", "reason": reason},
                id=signoff.input_sha256({"recalibration_closed": uri})[:32], at=stamp))
    ran = any(e["payload"].get("step") == STEP_OPEN_RECAL for e in st.index.of("step", subject))
    if out or not ran:
        opened = sorted(e["subject_uri"] for e in out if e["kind"] == "subject")
        out.append(events.make_event("step", subject, workflow.SYSTEM_ACTOR, {"step": STEP_OPEN_RECAL, "opened": opened},
                                     id=signoff.input_sha256({"open_recalibrations": [opened, stamp]})[:32], at=stamp))
    return out


def _recordings(st: State, instructor: str) -> list[dict[str, Any]]:
    """The exercises whose recording and reference scores can be used again, those the instructor has not scored first."""
    found = []
    for uri in sorted(u for u, i in st.subjects.items() if i.get("kind") == "exercise"):
        info = st.subjects[uri]
        if isinstance(_reference(st, info, domain_ids(st.root)), str):
            continue
        found.append({"exercise": uri, "unit": info["unit"], "recording_ref": info["recording_ref"],
                      "scored_before": instructor in (info.get("observers") or [])})
    return sorted(found, key=lambda r: (r["scored_before"], r["exercise"]))


def _partners(st: State, subject: str) -> list[str]:
    """The clearers, current or lapsed, who may score with the instructor: none with a blocking bench decision on the day the
    recalibration opened (a page's inputs come from the log alone, never from the clock)."""
    info = st.subjects[subject]
    opened = date.fromisoformat(st.index.of("subject", subject)[0]["at"][:10])
    return [c for c in clearers_ever(st) if c != info["instructor"] and bench_block(st, c, opened) is None]


def _recalibration(st: State, subject: str) -> dict[str, Any]:
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "recalibration":
        raise PageProblem(f"{subject} is not a recalibration")
    return info


@register(STEP_RECAL)
def _b_recalibration(st: State, subject: str) -> list[dict[str, Any]]:
    info = _recalibration(st, subject)
    instructor = info["instructor"]
    recordings = _recordings(st, instructor)
    if not recordings:
        raise PageProblem(f"{subject}: no pre-scored recording on record yet; open the first exercise with "
                          "teachermodel open-exercise")
    partners = _partners(st, subject)
    if not partners:
        raise PageProblem(f"{subject}: no other clearer to score the recording with {instructor}")
    inputs = {"recalibration": subject, "instructor": instructor,
              "passes": [d.isoformat() for d in calibrations(st).get(instructor, [])],
              "audit_referrals": [d.isoformat() for d in lapses(st).get(instructor, [])],
              "recordings": recordings, "partners": partners}
    fields = [
        {"name": "recording", "label": "Recording", "kind": "enum", "options": [r["exercise"] for r in recordings],
         "required": True,
         "help": "The exercise whose recording and reference scores are used again. Those the instructor has not scored "
                 "come first."},
        {"name": "second_observer", "label": "Second observer", "kind": "enum", "options": partners, "required": True,
         "help": "Scores the same recording independently (spec W5)."},
    ]
    intro = (f"{instructor}'s observer calibration has lapsed or lapses within {RENEW_AHEAD_DAYS} days, so they cannot "
             "observe or decide clearances until they pass again. Approve to open a calibration exercise for them on the "
             "recording you choose; both observers then get a scoring page.")
    return [spec(st, STEP_RECAL, subject, r["person"], "approve", inputs, fields, intro)
            for r in people_with(st, HEAD_ROLE)]


@content_check(STEP_RECAL)
def _recalibration_content(st: State, document: dict[str, Any]) -> list[str]:
    info = st.subjects.get(document.get("subject_uri"))
    if info is None or info.get("kind") != "recalibration":
        return ["the subject is not a recalibration"]
    reasons = []
    if not is_head(st, document.get("signer")):
        reasons.append("the signer is not the head of training")
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return reasons + ["the sign-off carries no fields"]
    if fields.get("recording") not in {r["exercise"] for r in _recordings(st, info["instructor"])}:
        reasons.append("recording: one of the listed exercises is required")
    if fields.get("second_observer") not in _partners(st, document["subject_uri"]):
        reasons.append("second_observer: one of the listed clearers is required")
    return reasons


@on_signoff(STEP_RECAL)
def _open_recalibration_exercise(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """The exercise, as `open-exercise` would open it: the chosen recording and its reference scores, the instructor and
    the second observer. The next run of `open-recalibrations` closes the recalibration."""
    if _recalibration_content(st, document):
        return [], []
    instructor, fields = st.subjects[signed["subject_uri"]]["instructor"], document["fields"]
    source = st.subjects[fields["recording"]]
    scores = _reference(st, source, domain_ids(st.root))
    observers = sorted([instructor, fields["second_observer"]])
    uri = exercise_uri(source["unit"], source["recording_ref"], observers, now.date())
    if uri in st.subjects or isinstance(scores, str):
        return [], []
    key = _reference_key(uri)
    event = _exercise_event(uri, source["unit"], st.standards["rubric"]["framework_version"], source["recording_ref"],
                            observers, key, STEP_RECAL, iso_seconds(now))
    return [event], [(key, {"schema": "tm:calibration-reference@1", "exercise": uri, "unit": source["unit"],
                            "scores": scores})]


# --- the due rule ------------------------------------------------------------------------------------------


def _renewal_months(log: Any = ()) -> dict[str, int]:
    """Exercise URI -> the `calibration.renewal_months` its result was computed under, read from the calibration-result
    `step` events in the log: the rules of the State's root (a due rule is handed no State or rules document), so a store
    run against another root gets that root's renewal period. Key "" holds the repo's own value, for a calibration whose
    result event does not carry one."""
    months = {"": load_yaml(ROOT / "standards" / "rules.yaml")["calibration"]["renewal_months"]}
    for e in log:
        p = e["payload"]
        if e["kind"] == "step" and p.get("step") == STEP_RESULT and type(p.get("renewal_months")) is int:
            months[e["subject_uri"]] = p["renewal_months"]
    return months


@due_rule("clearer_renewal")
def clearer_renewal(step: dict[str, Any], subject: str, info: dict[str, Any], log: Any, today: date) -> date | None:
    """When a calibration lapses: `renewal_months` after the latest passed calibration, the months being those of the
    rules its result was computed under (`_renewal_months`).

    For an instructor, their own lapse date. For an exercise, the earliest lapse date among its observers who have ever
    passed, so a renewal exercise is due before the first of them lapses. None when there is nothing to renew (no
    observer has passed yet) or the subject is of another kind."""
    if info.get("kind") == "instructor":
        who = {subject}
    elif info.get("kind") == "exercise":
        who = {o for o in info.get("observers", []) if isinstance(o, str)}
    else:
        return None
    log = list(log)
    passed = passed_calibrations(log)
    if not any(passed.get(o) for o in who):
        return None
    months = _renewal_months(log)
    lapse: dict[str, date] = {}
    latest: dict[str, date] = {}
    for e in log:
        p = e["payload"]
        if e["kind"] == "calibration" and p.get("passed") is True and p.get("observer") in who:
            day = date.fromisoformat(e["at"][:10])
            until = rules.add_months(day, months.get(p.get("exercise"), months[""]))
            lapse[p["observer"]] = max(until, lapse.get(p["observer"], until))
            latest[p["observer"]] = max(day, latest.get(p["observer"], day))
    # An audit referral on or after the latest pass lapses the calibration on its own date (W6, decision 0015).
    for observer, days in referral_lapses(log).items():
        if observer in lapse:
            after = [d for d in days if d >= latest[observer]]
            if after:
                lapse[observer] = min(lapse[observer], min(after))
    return min(lapse.values()) if lapse else None
