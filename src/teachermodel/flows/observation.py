"""W2 observation (standards/workflows/observation.yaml): proposals, assignments, the observer's and the instructor's
pages, and the blind release of the `observation` events.

    propose-observations (auto, per candidate)  ->  generated/observations/<candidate-slug>.json
    assignments-approved (coordinator, batch)   ->  hook opens one `assignment` subject per approved row
    observe (the assigned observer)             ->  hook keeps the scores and notes in the private store
    assign-observer (coordinator, ad hoc)       ->  hook opens one `assignment` subject through the same opener; separate from
                                                    the proposals, and open again after each approval (bind: input)
    self-assessment (the instructor)            ->  nothing to do: the sign-off document is the record
    release (auto, per assignment)              ->  one `observation` event per assignment, once the whole delivery
                                                    has its observe sign-offs

Blindness: until every assignment that shares a `delivery_ref` has an accepted observe sign-off, the log holds only those
sign-offs (hashes, no scores) and `release` writes nothing. The scores and notes sit in `evidence/<assignment>.json` in
the private store, which no page shows; the `observation` event carries the scores and `evidence_ref`, never the notes.

Identity assumptions, until the model carries them:
- An observer is an instructor (`tm:instructor/...`, observation@2) at level `clearer` (a level_change or the registration)
  who is calibrated on the day of the proposal (records.calibrations, rules.is_calibrated). A people-list `clearer` role does
  not make anyone a clearer (decision 0012, amended: integration review finding 5); a mapped person (people.yaml
  `instructor`) signs as the instructor they are mapped to.
- An instructor's coaches are the instructors that people-list persons holding the `coach` role (mapped to an instructor)
  coach, by their `coaches` list (`common.coaches_of`, decision 0014). The coach limit on the observers of a candidate is
  about the candidate's own coaches; a coach of someone else is an ordinary observer for them.
- The delivery date is not known when observers are proposed, so the proposal names a placeholder `delivery_ref`
  (`<candidate-slug>-<n>`, n the round) that the assignments of one round share; the observer enters the date of the
  session on the page, and it may not precede the day the assignment was opened.

Ad-hoc assignments (`assign-observer`, increment 3 plan J). The coordinator may add an observer outside the proposals: a page on
the candidate with the observer (the options are the proposals' pool, `observer_pool`, less the instructor), the length, lead
and mode, and an optional delivery reference (else `<candidate-slug>-adhoc-<8 hex of the sign-off id>`, so a replay opens the
same assignment). The step has its own id, no step needs it and it needs only `open-candidates`, so it neither blocks nor waits
for the proposals; its inputs carry the number of ad-hoc assignments opened, so the step reopens after each one (as log-activity
does) and never falls due. An ad-hoc assignment is an ordinary assignment from then on, except that its observe and
self-assessment steps do not wait for the candidate's batch to be approved: its own approval stands in for it (the steps'
`needs_except_opened_by`, which the engine reads from the assignment's `opened_by`). The content check, on the day of signing:
the observer is in the pool of that day and is not the instructor; the delivery reference is not in use for another candidate
and its assignments are not yet released (an observer joining a released delivery would score knowing the others' scores);
the observer is not already on that delivery; and at most `rules.clearance.max_coach_observers` of the instructor's coaches
(`coaches_of`) observe one delivery, counting the assignments already on it.

Rounds: the first proposal is round 1. `propose-observations` refreshes (it is re-run while its needs are met) and proposes
round n+1 only when round n has SETTLED (approved, and every assignment of it released as an `observation`) and either the
candidate's evidence still lacks observations (rules.clearance_check with the dry run set aside) or a not_yet clearance or a
recheck round was recorded after round n was proposed. A round that is pending (unapproved, or approved and unobserved) is
never proposed again, so an observer pair is never doubled up.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Iterable
from datetime import date, datetime, timedelta
from typing import Any

from .. import events, rules, signoff
from .. import pages as pagegen
from ..due import due_rule
from ..workflow import APPROVING, SYSTEM_ACTOR
from . import auto_step, content_check, on_signoff, register
from .common import (
    PageProblem,
    State,
    blocked_check,
    cached,
    calibrations,
    clearer_instructors,
    coaches_of,
    evidence_score_reasons,
    lapses,
    generated,
    latest_day,
    observations,
    observer_pool,  # noqa: F401 - re-exported: who may observe on a day
    opened_day,
    per_signer,
    spec,
)
from .common import bench_block  # decision 0015, finding 3: an exited instructor gets no new proposals
from .clearance import evidence_since  # decision 0015, finding 4: only observations after a blocking decision count
from .dry_run import _signed_day
from .pathway import subject_event_id
from ..util import slug as _slug, write_if_changed as _write

STEP_PROPOSE = "tm:step/propose-observations"
STEP_APPROVED = "tm:step/assignments-approved"
STEP_OBSERVE = "tm:step/observe"
STEP_SELF = "tm:step/self-assessment"
STEP_RELEASE = "tm:step/release"
STEP_ASSIGN = "tm:step/assign-observer"
# Decision 0022 (paper fallback): how far back a session held on paper may be entered through an ad-hoc assignment. An
# operational default (decision 0002), not an evidence-based threshold.
PAPER_BACKDATE_DAYS = 14

OBSERVATION_WINDOW_DAYS = 14  # operational default (decision 0002): days from the day an assignment is opened
LENGTHS = ("full", "short")
MODES = ("in-person", "remote", "hybrid")
EVIDENCE_DIR = "evidence"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")  # a delivery reference: an id, not a sentence or a name


# --- who observes ----------------------------------------------------------------------------------------------


def clearers(st: State) -> list[str]:
    """Registered instructors at level `clearer` (the latest level_change, else the registration). Sorted. Not yet the pool
    that may observe: that also needs a calibration on the day (`observer_pool`)."""
    return clearer_instructors(st.registrations, st.events, st.people)


def coaches(st: State, instructor: str) -> set[str]:
    """The instructors who coach `instructor` (`flows.common.coaches_of`, decision 0014): the coach limit on a candidate's
    observers is about their own coaches, so a coach of someone else is an ordinary observer for this instructor."""
    return coaches_of(st, instructor)


def rank(candidate: str, observer: str) -> str:
    """The rotation key: the same candidate and observer always rank the same, different candidates rotate the pool."""
    return hashlib.sha256(f"{candidate}:{observer}".encode("utf-8")).hexdigest()


def choose_observers(
    candidate: str, instructor: str, pool: Iterable[str], coach_set: Collection[str], count: int, max_coaches: int
) -> list[str]:
    """Up to `count` observers by hash rank, never the instructor, and no more than `max_coaches` of them coaches. Fewer
    than `count` when the pool cannot supply them (the caller treats that as blocked). Independent of the pool's order."""
    chosen: list[str] = []
    used_coaches = 0
    for observer in sorted(set(pool) - {instructor}, key=lambda o: (rank(candidate, o), o)):
        if len(chosen) == count:
            break
        if observer in coach_set:
            if used_coaches >= max_coaches:
                continue
            used_coaches += 1
        chosen.append(observer)
    return chosen


def assignment_uri(candidate: str, observer: str, delivery_ref: str) -> str:
    """`tm:assignment/<16 hex>`, derived from what makes the assignment: replaying an approval cannot open it twice."""
    return "tm:assignment/" + signoff.input_sha256({"assignment": [candidate, observer, delivery_ref]})[:16]


def delivery_ref(candidate: str, round_: int = 1) -> str:
    """The placeholder delivery of round `round_` of a candidate: `<candidate-slug>-<n>`."""
    return f"{_slug(candidate)}-{round_}"


def evidence_key(assignment: str) -> str:
    """Where the observer's scores and notes are kept in the private store (the observation's `evidence_ref`)."""
    return f"{EVIDENCE_DIR}/{_slug(assignment)}.json"


# --- private files and events ------------------------------------------------------------------------------------


def _json_bytes(doc: Any) -> bytes:
    return (json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _subject_of_kind(st: State, subject: Any, kind: str) -> dict[str, Any] | None:
    info = st.subjects.get(subject)
    return info if info is not None and info.get("kind") == kind else None


def _session_reasons(fields: dict[str, Any]) -> list[str]:
    """Why the length, lead flag or mode of an observation's answers cannot be used."""
    reasons = []
    if fields.get("length") not in LENGTHS:
        reasons.append("length: full or short is required")
    if type(fields.get("lead")) is not bool:
        reasons.append("lead: yes or no is required")
    if fields.get("mode") not in MODES:
        reasons.append("mode: one of the delivery modes is required")
    return reasons


# --- propose-observations ----------------------------------------------------------------------------------------


STEP_EVIDENCE_READY = "tm:step/evidence-ready"  # the clearance workflow's round step; read here by id only


def _deliveries(st: State) -> dict[str, list[str]]:
    """delivery_ref -> the URIs of the assignments that share it, once per state."""

    def build():
        by_delivery: dict[str, list[str]] = {}
        for uri, info in st.subjects.items():
            if info.get("kind") == "assignment":
                by_delivery.setdefault(info.get("delivery_ref"), []).append(uri)
        return by_delivery

    return cached(st, "assignment_index", build)


def _positions(st: State) -> dict[str, int]:
    """Event id -> place in the log, once per state: "after" in the log's order, not by the clock an event carries."""
    return cached(st, "positions", lambda: {e["id"]: n for n, e in enumerate(st.events)})


def _rounds(st: State, candidate: str) -> list[dict[str, Any]]:
    """The candidate's proposals (`step` events of propose-observations), in log order: round n is the n-th."""
    return [e for e in st.index.of("step", candidate) if e["payload"].get("step") == STEP_PROPOSE]


def _round_settled(st: State, candidate: str, round_: int) -> bool:
    """Round `round_` was approved (its assignments exist) and every one of them has been released as an `observation`."""
    assigned = [u for u in _deliveries(st).get(delivery_ref(candidate, round_), [])
                if st.subjects[u].get("candidate") == candidate]
    if not assigned:
        return False  # awaiting approval
    instructor = st.subjects[candidate]["instructor"]
    released = {e["payload"].get("assignment") for e in st.index.of("observation", instructor)}
    return all(u in released for u in assigned)


def _short_of_observations(st: State, info: dict[str, Any]) -> bool:
    """The candidate's evidence lacks observations: rules.clearance_check fails with the dry run set aside (it is W3's, not an
    observation's), over the observations on record and the calibrations."""
    domains = [d["id"] for d in st.standards["framework"]["domains"]]
    aside = [rules.DryRun(info["instructor"], info["unit"], info["mode"], True, date.min)]
    verdict = rules.clearance_check(
        info["instructor"], info["unit"], info["mode"], observations(st), aside, calibrations(st),
        coaches(st, info["instructor"]), domains, st.standards["rules"], since=evidence_since(st, info["instructor"], None),
        lapses=lapses(st))
    return not verdict.ok


def _asked_again(st: State, candidate: str, last: dict[str, Any]) -> bool:
    """A not_yet clearance, or a recheck round of the clearance workflow, was recorded after the proposal `last`. Read by kind
    and step id only."""
    pos = _positions(st)
    after = pos[last["id"]]
    asks = [
        *(e for e in st.index.of("clearance", candidate) if e["payload"].get("outcome") == "not_yet"),
        *(e for e in st.index.of("step", candidate)
          if e["payload"].get("step") == STEP_EVIDENCE_READY and e["payload"].get("reason") == "recheck"),
    ]
    return any(pos[e["id"]] > after for e in asks)


def _wants_another_round(st: State, candidate: str, info: dict[str, Any], rounds: list[dict[str, Any]]) -> bool:
    """True once the latest round has settled and the candidate still needs observations."""
    return _round_settled(st, candidate, len(rounds)) and (
        _asked_again(st, candidate, rounds[-1]) or _short_of_observations(st, info))


@auto_step(STEP_PROPOSE, per="candidate", refresh=True)
def propose_observations(st: State, candidate: str, now: datetime) -> list[dict[str, Any]]:
    """The batch of assignments for a candidate: as many observers as rules.clearance needs (at least its minimum number
    of observations and of distinct observers), all of one delivery so they observe the same session, each a full lead
    observation (the minimum needs at least one). Written to generated/observations/<candidate-slug>.json (round 1; round n
    is <candidate-slug>.<n>.json) as the rows of the batch page, with a `step` event naming it. The observers come from the
    `observer_pool` of the day. A pool that cannot supply them appends nothing (the reason goes to
    <candidate-slug>.blocked.json beside the outputs) and the step runs again on the next run.

    The step refreshes: once a round has settled it proposes the next only if the candidate's evidence still lacks
    observations or a not_yet clearance / recheck round came after it (see the module docstring). While a round is pending
    nothing is proposed, so an observer pair is never proposed twice."""
    info = _subject_of_kind(st, candidate, "candidate")
    if info is None:
        return []
    if bench_block(st, info["instructor"], now.date()) == "exit":  # decision 0015, finding 3
        return []
    rounds = _rounds(st, candidate)
    if rounds and not _wants_another_round(st, candidate, info, rounds):
        return []
    n = len(rounds) + 1
    c = st.standards["rules"]["clearance"]
    count = max(c["min_observations"], c["min_distinct_observers"])
    instructor = info["instructor"]
    chosen = choose_observers(candidate, instructor, observer_pool(st, now.date()), coaches(st, instructor), count,
                              c["max_coach_observers"])
    base = f"generated/observations/{_slug(candidate)}"
    if len(chosen) < count:
        # Waiting for clearers is not an event: a note beside the outputs says why, and the step stays open.
        _write(st.private / f"{base}.blocked.json", _json_bytes({"candidate": candidate, "step": STEP_PROPOSE, "reasons": [
            f"{len(chosen)} eligible observers; need {count} (clearers calibrated today, other than the instructor, at "
            f"most {c['max_coach_observers']} of them a coach)"]}))
        return []
    (st.private / f"{base}.blocked.json").unlink(missing_ok=True)
    ref = delivery_ref(candidate, n)
    rows = []
    for observer in chosen:
        attrs = {"candidate": candidate, "instructor": instructor, "unit": info["unit"], "mode": info["mode"],
                 "observer": observer, "length": "full", "lead": True, "delivery_ref": ref}
        rows.append({
            "key": assignment_uri(candidate, observer, ref),
            "summary": f"{observer} observes {instructor} on {info['unit']} ({info['mode']}): full lead observation of "
                       f"delivery {ref}",
            "changed": True,
            "attrs": attrs,
        })
    data = _json_bytes({"candidate": candidate, "delivery_ref": ref, "rows": rows})
    rel = f"{base}.json" if n == 1 else f"{base}.{n}.json"
    _write(st.private / rel, data)
    digest = hashlib.sha256(data).hexdigest()
    return [events.make_event(
        "step", candidate, SYSTEM_ACTOR,
        {"step": STEP_PROPOSE, "output": rel, "output_sha256": digest, "round": n, "delivery_ref": ref},
        id=signoff.input_sha256({"proposal": [candidate, digest]})[:32], at=now.isoformat(timespec="seconds"))]


# --- assignments-approved ----------------------------------------------------------------------------------------


def _proposal(st: State, candidate: str) -> dict[str, Any]:
    text, _ = generated(st, STEP_PROPOSE, candidate)
    try:
        doc = json.loads(text)
        rows, ref = doc["rows"], doc["delivery_ref"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PageProblem(f"the observation proposal for {candidate} is unreadable") from exc
    if not isinstance(rows, list) or not isinstance(ref, str):
        raise PageProblem(f"the observation proposal for {candidate} is unreadable")
    return doc


@register(STEP_APPROVED)
def _b_assignments(st: State, candidate: str):
    doc = _proposal(st, candidate)
    inputs = {"candidate": candidate, "delivery_ref": doc["delivery_ref"], "rows": doc["rows"]}
    return per_signer(st, STEP_APPROVED, candidate, "batch_approve", inputs,
                      intro="Approve the observers proposed for this candidate. Each approved row opens one "
                            "observation assignment; the observers of one delivery score blind to each other.")


@on_signoff(STEP_APPROVED)
def _open_assignments(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """A `subject` event for each row of the proposal the sign-off approved. The rows come from the proposal as the page
    showed it (the sign-off was accepted against its hash). Ingest accepts a batch approval only when it decides every row of
    the page and approves each (`signoff.content_reasons`), so every row here is approved: there is no row to skip. A row
    whose observer is the instructor, or whose event would not validate, is never opened."""
    candidate = signed["subject_uri"]
    info = _subject_of_kind(st, candidate, "candidate")
    if info is None:
        return [], []
    try:
        rows = _proposal(st, candidate)["rows"]
    except PageProblem:
        return [], []
    return _open_rows(candidate, info, rows, signed, now, STEP_APPROVED), []


def _open_rows(candidate: str, info: dict[str, Any], rows: list[Any], signed: dict[str, Any], now: datetime,
               opened_by: str) -> list[dict[str, Any]]:
    """The `subject` events that open the assignments of `rows` ({key, attrs}): the one opener of W2, used by the batch approval
    and by the ad-hoc assignment. A row whose key is not the URI its attrs derive, that is for another candidate or instructor,
    whose observer is the instructor, or whose event would not validate, is never opened."""
    out: list[dict[str, Any]] = []
    for row in rows:
        attrs = row.get("attrs") if isinstance(row, dict) else None
        if not isinstance(attrs, dict):
            continue
        try:
            uri = assignment_uri(attrs["candidate"], attrs["observer"], attrs["delivery_ref"])
            sound = (row["key"] == uri and attrs["candidate"] == candidate and attrs["instructor"] == info["instructor"]
                     and attrs["observer"] != attrs["instructor"])
        except (KeyError, TypeError):
            continue
        if not sound:
            continue
        event = events.make_event(
            "subject", uri, signed["actor"], {"subject_kind": "assignment", "attrs": attrs, "opened_by": opened_by},
            id=subject_event_id(uri), at=now.isoformat(timespec="seconds"))
        if not events.check_event(event):
            out.append(event)
    return out


# --- assign-observer (ad hoc) ------------------------------------------------------------------------------------


def _released(st: State, assignment: str) -> bool:
    """The assignment's observation has been released (`release` ran for it)."""
    return any(e["payload"].get("step") == STEP_RELEASE for e in st.index.of("step", assignment))


def adhoc_count(st: State, candidate: str) -> int:
    """How many assignments of the candidate the coordinator opened through `assign-observer`."""
    return sum(1 for uri, a in st.subjects.items() if a.get("kind") == "assignment" and a.get("candidate") == candidate
               and (st.index.of("subject", uri) or [{"payload": {}}])[0]["payload"].get("opened_by") == STEP_ASSIGN)


def adhoc_ref(candidate: str, signoff_id: str) -> str:
    """The delivery reference given to an ad-hoc assignment when the coordinator named none: derived from the sign-off."""
    return f"{_slug(candidate)}-adhoc-{signoff_id[:8]}"


@register(STEP_ASSIGN)
def _b_assign(st: State, candidate: str):
    info = _subject_of_kind(st, candidate, "candidate")
    if info is None:
        raise PageProblem(f"{candidate} is not a candidate")
    day = latest_day(st)
    options = sorted(set(observer_pool(st, day)) - {info["instructor"]}) if day else []
    if not options:
        raise PageProblem(f"no calibrated clearer other than {info['instructor']} can observe {candidate}")
    inputs = {"candidate": candidate, "instructor": info["instructor"], "unit": info["unit"], "mode": info["mode"],
              "ad_hoc_assignments_so_far": adhoc_count(st, candidate)}
    minutes = st.standards["rules"]["clearance"]["short_observation_minutes"]
    fields = [
        {"name": "observer", "label": "Observer", "kind": "enum", "options": options, "required": True,
         "help": "A clearer who is calibrated today, other than the instructor observed."},
        {"name": "length", "label": "Length", "kind": "enum", "options": list(LENGTHS), "required": True, "value": "full",
         "help": f"A short observation is {minutes} minutes."},
        {"name": "lead", "label": "The instructor leads this session", "kind": "bool", "required": False, "value": True},
        {"name": "mode", "label": "Delivery mode", "kind": "enum", "options": list(MODES), "required": True,
         "value": info["mode"]},
        {"name": "delivery_ref", "label": "Delivery reference (optional)", "kind": "text", "required": False,
         "help": "The delivery or session id, never a person's name. Observers given the same reference score the same "
                 "session blind to each other. Leave it empty for a delivery of its own."},
        {"name": "held_on", "label": "Session already held on (paper record, optional)", "kind": "date", "required": False,
         "help": f"Only when the session was observed on paper while the system was down: its date, at most "
                 f"{PAPER_BACKDATE_DAYS} days back. The observer then enters the paper record with that date."},
    ]
    intro = ("Assign one more observer to this candidate outside the proposed batch. The assignment is an ordinary one: the "
             "observer is asked to score the session and the instructor to self-assess. Nothing is needed here unless you "
             "want an extra observation: if you do not, simply do not send this page. After each assignment the page comes "
             "back for another one.")
    # The `assign` template offers one decision, "Assign this observer" (value approve): changes or reject mean nothing
    # on an optional page that is simply not sent when no assignment is wanted.
    return per_signer(st, STEP_ASSIGN, candidate, "assign", inputs, fields, intro)


def _adhoc_row(st: State, info: dict[str, Any], candidate: str, fields: dict[str, Any], sid: str) -> dict[str, Any]:
    """The row ({key, attrs}) an ad-hoc answer stands for."""
    ref = fields.get("delivery_ref")
    ref = ref.strip() if isinstance(ref, str) and ref.strip() else adhoc_ref(candidate, sid)
    attrs = {"candidate": candidate, "instructor": info["instructor"], "unit": info["unit"], "mode": fields["mode"],
             "observer": fields["observer"], "length": fields["length"], "lead": fields["lead"], "delivery_ref": ref}
    if isinstance(fields.get("held_on"), str) and fields["held_on"].strip():
        attrs["held_on"] = fields["held_on"].strip()
    return {"key": assignment_uri(candidate, fields["observer"], ref), "attrs": attrs}


@content_check(STEP_ASSIGN)
def _check_assign(st: State, document: dict[str, Any]) -> list[str]:
    """The answers of the ad-hoc page must be ones the page could give, on the day of signing: an observer in that day's pool
    other than the instructor and not already on the delivery, a length, a lead flag, a mode, a delivery reference that is an id
    and belongs to no other candidate, and no more of the instructor's coaches on one delivery than the clearance rules allow."""
    candidate = document.get("subject_uri")
    info = _subject_of_kind(st, candidate, "candidate")
    if info is None:
        return ["the subject is not a candidate"]
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return ["the sign-off carries no fields"]
    reasons: list[str] = []
    if not any(r["person"] == document.get("signer") and "coordinator" in r["roles"] for r in st.people):
        reasons.append("the signer is not a coordinator")
    observer = fields.get("observer")
    day = _signed_day(document.get("signed_at"), datetime.max)
    if not isinstance(observer, str) or observer not in observer_pool(st, day):
        reasons.append("observer: a clearer who is calibrated on the day of signing is required")
    elif observer == info["instructor"]:
        reasons.append("observer: the instructor observed cannot observe their own session")
    reasons += _session_reasons(fields)
    held = fields.get("held_on")
    if held not in (None, ""):
        try:
            if not (isinstance(held, str) and _DAY.match(held.strip())):
                raise ValueError(held)
            held_day = date.fromisoformat(held.strip())
            if held_day > day:
                reasons.append("held_on: the paper session cannot be after the day of signing")
            elif (day - held_day).days > PAPER_BACKDATE_DAYS:
                reasons.append(f"held_on: a paper session is entered within {PAPER_BACKDATE_DAYS} days (decision 0022)")
        except ValueError:
            reasons.append("held_on: a date (YYYY-MM-DD) is required when given")
    ref = fields.get("delivery_ref")
    if ref is not None and not isinstance(ref, str):
        reasons.append("delivery_ref: text is required when given")
    else:
        ref = (ref or "").strip() or None
        if ref is not None:
            if not _REF.match(ref):
                reasons.append("delivery_ref: an id of letters, digits, dots, dashes and underscores (at most 64) is required")
            elif any(st.subjects[u].get("candidate") != candidate for u in _deliveries(st).get(ref, [])):
                reasons.append("delivery_ref: this reference is in use for another candidate")
    if reasons:
        return reasons
    if ref is not None:
        members = _deliveries(st).get(ref, [])
        same = [st.subjects[u] for u in members]
        if any(_released(st, u) for u in members):
            # blind scoring ended when the delivery was released: a later observer would see the others' scores on record
            reasons.append("delivery_ref: the observations of this delivery have been released; use another reference")
        if any(a.get("observer") == observer for a in same):
            reasons.append("observer: already assigned to this delivery")
        coach_set = coaches(st, info["instructor"])
        on_delivery = {a.get("observer") for a in same} | {observer}
        if len(on_delivery & coach_set) > st.standards["rules"]["clearance"]["max_coach_observers"]:
            reasons.append("observer: too many of the instructor's coaches would observe this delivery "
                           f"(at most {st.standards['rules']['clearance']['max_coach_observers']})")
    return reasons


@on_signoff(STEP_ASSIGN)
def _open_adhoc(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """The `subject` event that opens the assignment the coordinator's answers describe, through the same opener as the batch
    approval. A sign-off the content check would have refused opens nothing. Replaying it opens the same assignment."""
    candidate = signed["subject_uri"]
    info = _subject_of_kind(st, candidate, "candidate")
    if info is None or _check_assign(st, document):
        return [], []
    row = _adhoc_row(st, info, candidate, document["fields"], signed["payload"]["signoff_id"])
    return _open_rows(candidate, info, [row], signed, now, STEP_ASSIGN), []


# --- observe and self-assessment ---------------------------------------------------------------------------------


def _assignment(st: State, subject: str) -> dict[str, Any]:
    info = _subject_of_kind(st, subject, "assignment")
    if info is None:
        raise PageProblem(f"{subject} is not an assignment")
    return info


def _inputs(subject: str, a: dict[str, Any], st: State) -> dict[str, Any]:
    out = {"assignment": subject, "candidate": a["candidate"], "instructor": a["instructor"], "unit": a["unit"],
           "mode": a["mode"], "length": a["length"], "lead": a["lead"], "delivery_ref": a["delivery_ref"],
           "framework_version": st.standards["framework"]["version"]}
    if "recording_ref" in a:
        out["recording_ref"] = a["recording_ref"]
    return out


@register(STEP_OBSERVE)
def _b_observe(st: State, subject: str):
    a = _assignment(st, subject)
    if a["observer"] == a["instructor"]:
        raise PageProblem(f"the observer of {subject} is the instructor observed")
    if a["observer"] not in clearer_instructors(st.registrations, st.events, st.people):
        # Ingest refuses an observation from someone who is not a clearer (their calibration lapsed and the level moved
        # back): a page every sign-off would be refused on helps nobody (found by the simulation, 2026-10-27).
        raise PageProblem(f"the observer of {subject}, {a['observer']}, is not a clearer today; the page comes back once "
                          "they are")
    minutes = st.standards["rules"]["clearance"]["short_observation_minutes"]
    fields = [
        {"name": "date", "label": "Date of the session observed", "kind": "date", "required": True},
        {"name": "length", "label": "Length observed", "kind": "enum", "options": list(LENGTHS), "required": True,
         "value": a["length"], "help": f"A short observation is {minutes} minutes."},
        {"name": "lead", "label": "The instructor led this session", "kind": "bool", "required": False,
         "value": a["lead"], "help": "Untick for a co-delivered or shadowed session."},
        {"name": "mode", "label": "Delivery mode observed", "kind": "enum", "options": list(MODES), "required": True,
         "value": a["mode"]},
        {"name": "from_recording", "label": "Scored from a recording", "kind": "bool", "required": False,
         "help": "Tick when you scored from a recording of the session. A partner instructor's clearance counts only "
                 "observations scored from recordings (W11)."},
        *pagegen.evidence_score_fields(st.standards),
    ]
    return [spec(st, STEP_OBSERVE, subject, a["observer"], "approve", _inputs(subject, a, st), fields,
                 intro="Score each domain against the anchors and give the evidence for the score. Note a recording "
                       "timestamp where you scored from video.\n\nYou score blind: you cannot see the other observer's "
                       "scores, and they cannot see yours, until both of you have submitted.")]


@register(STEP_SELF)
def _b_self_assessment(st: State, subject: str):
    a = _assignment(st, subject)
    return [spec(st, STEP_SELF, subject, a["instructor"], "self_assessment", _inputs(subject, a, st),
                 pagegen.self_assessment_fields(st.standards),
                 intro="Score yourself against each domain for the session you were observed on. Your scores go to the "
                       "record of this observation, not to your manager.")]


def evidence(document: dict[str, Any], info: dict[str, Any], st: State) -> tuple[dict[str, Any] | None, list[str]]:
    """The observer's scores and notes from a stored observe sign-off, or the reasons it cannot be used. A reason names
    the field, never its value. `info` is the assignment's attributes."""
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return None, ["the sign-off carries no fields"]
    domains = [d["id"] for d in st.standards["framework"]["domains"]]
    reasons: list[str] = []
    if document.get("signer") != info.get("observer"):
        reasons.append("signed by someone other than the assigned observer")
    reasons += evidence_score_reasons(fields, domains)
    reasons += _session_reasons(fields)
    if "from_recording" in fields and type(fields["from_recording"]) is not bool:
        reasons.append("from_recording: yes or no is required when given")
    day = fields.get("date")
    signed_at = document.get("signed_at")
    try:
        if not (isinstance(day, str) and _DAY.match(day)):
            raise ValueError("date")
        held = date.fromisoformat(day)
        if held > datetime.fromisoformat(str(signed_at).replace("Z", "+00:00")).date():
            reasons.append("date: the session is after the sign-off")
        opened = opened_day(st, document.get("subject_uri"))
        paper = (st.subjects.get(document.get("subject_uri")) or {}).get("held_on")
        if isinstance(paper, str) and opened is not None:  # decision 0022: a session held on paper, entered afterwards
            opened = min(opened, date.fromisoformat(paper))
        if opened is not None and held < opened:
            # The session date is the observation's date, and the observer chooses it: it may not reach back before the
            # assignment existed (backdating it into a calibration that has since lapsed, say).
            reasons.append("date: the session is before the assignment was opened")
    except ValueError:
        reasons.append("date: a date (YYYY-MM-DD) is required")
    if reasons:
        return None, reasons
    scores = {d: fields[d]["score"] for d in domains}
    notes: dict[str, Any] = {}
    for d in domains:
        notes[d] = {"note": fields[d]["note"]}
        if isinstance(fields[d].get("timestamp"), str) and fields[d]["timestamp"].strip():
            notes[d]["timestamp"] = fields[d]["timestamp"].strip()
    data = {
        "assignment": document["subject_uri"], "observer": info["observer"], "instructor": info["instructor"],
        "unit": info["unit"], "delivery_ref": info["delivery_ref"], "date": day, "length": fields["length"],
        "lead": fields["lead"], "mode": fields["mode"], "scores": scores, "notes": notes,
        "signoff_id": document["id"], "recorded_at": signed_at,
    }
    if "from_recording" in fields:
        data["from_recording"] = fields["from_recording"]
    return data, []


@content_check(STEP_OBSERVE)
def _observe_content(st: State, document: dict[str, Any]) -> list[str]:
    """Ingest refuses an observe sign-off whose scores or session facts `evidence` cannot use (a domain missing, a score
    outside 1-4, a missing evidence note, an unknown length or mode, a date after the sign-off): it would only block the
    release later. A signer other than the assigned observer is refused here too."""
    info = _subject_of_kind(st, document.get("subject_uri"), "assignment")
    if info is None:
        return ["the subject is not an assignment"]
    return evidence(document, info, st)[1]


@on_signoff(STEP_OBSERVE)
def _keep_evidence(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """Keep the scores and notes in the private store under evidence/. Nothing enters the log: the observation is
    released only when the whole delivery has been observed. A sign-off that cannot be used stores nothing; `release`
    reports why."""
    info = _subject_of_kind(st, signed["subject_uri"], "assignment")
    if info is None:
        return [], []
    data, _ = evidence(document, info, st)
    if data is None:
        return [], []
    return [], [(evidence_key(signed["subject_uri"]), data)]


# --- release -----------------------------------------------------------------------------------------------------


def _observe_signoff(st: State, assignment: str) -> dict[str, Any] | None:
    found = None
    for e in st.index.of("signoff", assignment):
        if e["payload"].get("step") == STEP_OBSERVE and e["payload"].get("decision") in APPROVING:
            found = e
    return found


@auto_step(STEP_RELEASE, per="assignment")
def release(st: State, assignment: str, now: datetime) -> list[dict[str, Any]]:
    """The `observation` event of an assignment (observation@2) and a `step` event, once every assignment that shares its
    `delivery_ref` has an accepted observe sign-off; before that, nothing. The scores come from the stored sign-off, the
    event's `at` is the observer's session date and `evidence_ref` the private key of the notes. A sign-off that cannot be
    used gives a blocked `check` that names the fields. The ids are derived from the assignment, so a replay appends
    nothing."""
    info = _subject_of_kind(st, assignment, "assignment")
    if info is None:
        return []
    group = _deliveries(st).get(info["delivery_ref"], [])
    if any(_observe_signoff(st, u) is None for u in group):
        return []  # blind: someone has not submitted yet
    sid = _observe_signoff(st, assignment)["payload"]["signoff_id"]
    path = st.private / "signoffs" / f"{sid}.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return blocked_check(st, STEP_RELEASE, assignment, ["the stored sign-off is missing or unreadable"], now)
    if not isinstance(document, dict) or document.get("id") != sid:
        return blocked_check(st, STEP_RELEASE, assignment, ["the stored sign-off is not the one that was accepted"], now)
    data, reasons = evidence(document, info, st)
    if data is None:
        return blocked_check(st, STEP_RELEASE, assignment, reasons, now)
    key = evidence_key(assignment)
    _write(st.private / key, _json_bytes(data))
    payload = {
        "instructor": info["instructor"], "unit": info["unit"], "observer": info["observer"], "length": data["length"],
        "lead": data["lead"], "mode": data["mode"], "rubric_version": st.standards["rubric"]["framework_version"],
        "scores": data["scores"], "evidence_ref": key, "assignment": assignment, "delivery_ref": info["delivery_ref"],
        "recorded_at": data["recorded_at"],
    }
    if "from_recording" in data:
        payload["from_recording"] = data["from_recording"]  # W11: a partner's clearance counts only recorded observations
    obs_id = signoff.input_sha256({"observation_for": assignment})[:32]
    observed = events.make_event("observation", info["instructor"], info["observer"], payload, id=obs_id,
                                 at=f"{data['date']}T00:00:00+00:00")
    done = events.make_event(
        "step", assignment, SYSTEM_ACTOR, {"step": STEP_RELEASE, "observation": obs_id},
        id=signoff.input_sha256({"released": assignment})[:32], at=now.isoformat(timespec="seconds"))
    return [observed, done]


# --- due rule ----------------------------------------------------------------------------------------------------


@due_rule("observation_window")
def observation_window(step: dict[str, Any], subject: str, info: dict[str, Any],
                       log: Iterable[dict[str, Any]], today: date) -> date | None:
    """Observe and self-assessment fall due OBSERVATION_WINDOW_DAYS (an operational default, decision 0002) after the day the
    assignment was opened by its `subject` event; no date for a subject the log never opened."""
    for e in log:
        if e["kind"] == "subject" and e["subject_uri"] == subject:
            return date.fromisoformat(e["at"][:10]) + timedelta(days=OBSERVATION_WINDOW_DAYS)
    return None
