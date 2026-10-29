"""What the page builders share: the loaded state, the builder error, and the signer lookups.

Kept apart from `app` (which imports the flows) so the flow modules never import `app` back.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .. import events, records, rules, signoff
from ..util import iso_seconds
from ..workflow import APPROVING, PROGRAMME, SYSTEM_ACTOR, EventIndex

PEOPLE = "identities/people.yaml"
TARGET_LEVEL = "lead-observed"
_SIGNOFF_ID = re.compile(r"^[0-9a-f]{16,}\Z")


class PageProblem(Exception):
    """A page builder cannot build a page for this subject; the message goes in the report."""


@dataclass
class State:
    private: Path
    root: Path
    events: list[dict[str, Any]]
    standards: dict[str, dict[str, Any]]
    workflows: dict[str, Any]
    step_defs: dict[str, dict[str, Any]]
    subjects: dict[str, dict[str, Any]]
    registrations: dict[str, dict[str, Any]]
    people: list[dict[str, Any]]
    roster: dict[str, Any] | None
    identities: dict[str, list[signoff.Identity]]
    settings: dict[str, Any]
    # The jurisdictions the base profile covers (the others are overlays); `app.advance_state` re-derives the subjects from it.
    base_codes: tuple[str, ...] = ()
    # Answers derived from this state alone (page specs per (step, subject), and the readers built on them). The events
    # and files a State holds do not change while it is used; a changed store is read into a new State.
    cache: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def index(self) -> EventIndex:
        """The events by `(kind, subject_uri)` and by subject, and the set of event ids: built on first use, over this state's
        own `events` list (a state whose list was replaced gets a new index)."""
        found = self.cache.get("event_index")
        if found is None or found.events is not self.events:
            found = self.cache["event_index"] = EventIndex(self.events)
        return found


def latest_level(registration: dict[str, Any] | None, log: Iterable[dict[str, Any]], uri: str) -> str | None:
    level = (registration or {}).get("level")
    for e in log:
        if e["kind"] == "level_change" and e["subject_uri"] == uri:
            level = e["payload"].get("to", level)
    return level


def current_level(st: State, uri: str) -> str | None:
    """The latest `level_change` `to` for the instructor, else the level in the registration."""
    return latest_level(st.registrations.get(uri), st.index.of("level_change", uri), uri)


def cached(st: State, key: str, make: Callable[[], Any]) -> Any:
    """`make()` once per state under `key`: an answer derived from this state's events alone (a state's events do not change
    while it is used; a state with more events is a new State with an empty cache)."""
    if key not in st.cache:
        st.cache[key] = make()
    return st.cache[key]


def observations(st: State) -> list[rules.Observation]:
    return cached(st, "observations", lambda: records.observations(st.events))


def blocked_check(st: State, step: str, subject: str, reasons: list[str], now: datetime,
                  seed: str = "blocked") -> list[dict[str, Any]]:
    """A `check` event {step, result: blocked, reasons}, unless the latest one for (subject, step) says the same. Its id
    derives from the content and the number of earlier checks of the step (integration review finding 15), so the same log
    gives the same event and reasons that return to earlier ones (A, B, A) are written again. `seed` keeps the ids each
    flow has always written."""
    payload = {"step": step, "result": "blocked", "reasons": reasons}
    mine = [e for e in st.index.of("check", subject) if e["payload"].get("step") == step]
    if mine and mine[-1]["payload"] == payload:
        return []
    return [events.make_event("check", subject, SYSTEM_ACTOR, payload, at=iso_seconds(now),
                              id=signoff.short_sha({seed: [subject, step, reasons, len(mine)]}))]


CLEARER_LEVEL = "clearer"
HEAD_ROLE = "head-of-training"  # the people-list role that decides clearances, benches and overrides
CLEARER_ROLE = signoff.CLEARER_ROLE  # the people-list role


def evidence_score_reasons(fields: Any, domains: Iterable[str]) -> list[str]:
    """Why the answers to an `evidence_score` page cannot count: for each framework domain a whole-number score of 1-4 and
    a non-empty note are required. A reason names the domain, never the answer."""
    if not isinstance(fields, dict):
        return ["the sign-off carries no fields"]
    reasons: list[str] = []
    for domain in domains:
        entry = fields.get(domain)
        if not isinstance(entry, dict) or type(entry.get("score")) is not int or entry["score"] not in (1, 2, 3, 4):
            reasons.append(f"domain {domain}: a score of 1 to 4 is required")
        elif not isinstance(entry.get("note"), str) or not entry["note"].strip():
            reasons.append(f"domain {domain}: an evidence note is required")
    return reasons


def signed_scores(st: State, subject: str, step: str, signer: str, domains: Iterable[str]) -> tuple[str, dict[str, int]] | None:
    """(sign-off id, scores) of `signer`'s latest accepted approving sign-off of the scoring `step` for `subject`, read from
    the stored sign-off document; None when there is none or it is incomplete (a score of 1-4 and a note for every domain)."""
    latest = None
    for e in st.index.of("signoff", subject):
        p = e["payload"]
        if e["actor"] == signer and p.get("step") == step and p.get("decision") in APPROVING:
            latest = e
    sid = latest["payload"].get("signoff_id") if latest else None
    if not (isinstance(sid, str) and _SIGNOFF_ID.match(sid)):
        return None
    try:
        doc = json.loads((st.private / "signoffs" / f"{sid}.json").read_text(encoding="utf-8"))
        if (doc["step"], doc["subject_uri"], doc["signer"]) != (step, subject, signer):
            return None
        scores = {}
        for d in domains:
            answer = doc["fields"][d]
            if not (type(answer["score"]) is int and 1 <= answer["score"] <= 4
                    and isinstance(answer.get("note"), str) and answer["note"].strip()):
                return None
            scores[d] = answer["score"]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return sid, scores


def is_head(st: State, signer: Any) -> bool:
    """Whether `signer` has the head-of-training role in the people list."""
    return any(r["person"] == signer and HEAD_ROLE in r["roles"] for r in st.people)


def mapped_instructors(people: Iterable[dict[str, Any]], role: str) -> set[str]:
    """The instructor URIs of the people-list persons who hold `role` and carry an explicit `instructor` mapping
    (people.yaml, decision 0012). Slugs and mailboxes are never compared."""
    return {r["instructor"] for r in people if role in r["roles"] and isinstance(r.get("instructor"), str)}


def clearer_instructors(
    registrations: dict[str, dict[str, Any]], log: Iterable[dict[str, Any]], people: Iterable[dict[str, Any]] = ()
) -> list[str]:
    """Registered instructors who hold `clearer`: their latest level is clearer (the latest `level_change`, else the
    registration). Sorted.

    Clearer status comes from the level alone (integration review finding 5): a people-list person with the `clearer` role
    mapped to an instructor does not make that instructor a clearer. `people` is kept only so callers need not change."""
    levels = {u: reg.get("level") for u, reg in registrations.items()}
    for e in log:
        if e["kind"] == "level_change" and e["subject_uri"] in levels:
            levels[e["subject_uri"]] = e["payload"].get("to", levels[e["subject_uri"]])
    return sorted(u for u, level in levels.items() if level == CLEARER_LEVEL)


def coach_instructors(registrations: dict[str, dict[str, Any]], people: Iterable[dict[str, Any]]) -> set[str]:
    """Registered instructors a person holding the coach role is mapped to."""
    named = mapped_instructors(people, "coach")
    return {u for u in registrations if u in named}


def coaches_of(st: State, instructor: str) -> set[str]:
    """The instructor URIs of `instructor`'s coaches (W7, decision 0014): for each people-list person who holds the `coach`
    role and lists `instructor` in their `coaches` (people.yaml), the instructor that person is mapped to.

    A coach with no `instructor` mapping is ignored: the limits on coaches (a coach is at most one of the observers, or of
    the clearers) are about instructor URIs, and a person with none cannot appear in an observer or clearer pool. A coach
    whose `coaches` is absent or empty coaches nobody; there is no "coaches everyone" default. An instructor is never their
    own coach. Registration is not checked here: the pools only hold registered instructors, so a coach who is not
    registered is never in one."""
    return {r["instructor"] for r in st.people
            if "coach" in r["roles"] and isinstance(r.get("instructor"), str) and r["instructor"] != instructor
            and instructor in r.get("coaches", ())}


def calibrations(st: State) -> dict[str, list[date]]:
    """Per instructor, the dates of the calibrations they passed (`records.calibrations`), once per state."""
    return cached(st, "calibrations", lambda: records.calibrations(st.events))


def lapses(st: State) -> dict[str, list[date]]:
    """Per instructor, the dates of the audits that referred them back to calibration (`records.lapses`), once per state."""
    return cached(st, "lapses", lambda: records.lapses(st.events))


def is_calibrated_on(st: State, instructor: str, on: date) -> bool:
    """`rules.is_calibrated`: a passed calibration of `instructor` whose renewal period includes `on`, dated after any audit
    referral of theirs on or before `on` (decision 0015)."""
    return rules.is_calibrated(instructor, on, calibrations(st), st.standards["rules"], lapses(st).get(instructor))


def bench_block(st: State, instructor: str, on: date) -> str | None:
    """The instructor's blocking bench decision on `on`, by name ("exit" or "return-to-co-teaching"), not yet superseded by a
    clearance issued after it (`records.bench_blocks.blocking_decision`); None when there is none. Decision 0015, integration
    review finding 3: the observer pool leaves out an instructor with one, and the coaching, quality and observation steps
    leave out one who exited."""
    if not cached(st, "has bench decisions", lambda: any(e["kind"] == "bench_decision" for e in st.events)):
        return None
    found = records.bench_blocks.blocking_decision(st.events, instructor, on)
    return found["decision"] if found else None


def observer_pool(st: State, on: date) -> list[str]:
    """The instructors who may observe or dry-run on the day `on`: a clearer by level that day's log shows, and calibrated on
    `on`. Sorted. A level and a calibration are both read from the log (`clearer_instructors`, `records.calibrations`). A
    clearer with a blocking bench decision (`bench_block`) is left out until cleared again (finding 3)."""
    def build() -> list[str]:
        clearers = cached(st, "clearers", lambda: clearer_instructors(st.registrations, st.events, st.people))
        return [c for c in clearers if is_calibrated_on(st, c, on) and bench_block(st, c, on) is None]

    return list(cached(st, f"observer_pool {on.isoformat()}", build))


def clearer_people(st: State, on: date) -> list[dict[str, Any]]:
    """The people-list persons who may sign as a clearer on the day `on`: they hold the `clearer` role AND are mapped
    (people.yaml `instructor`) to an instructor in the `observer_pool` (a clearer by level, calibrated that day). The role
    alone is not enough. Sorted by person URI."""
    pool = set(observer_pool(st, on))
    return sorted((r for r in st.people if CLEARER_ROLE in r["roles"] and r.get("instructor") in pool),
                  key=lambda r: r["person"])


def latest_day(st: State) -> date | None:
    """The day of the newest event in the log, the day the page builders (which are given no clock) judge a pool on."""
    return cached(st, "latest_day", lambda: max((date.fromisoformat(e["at"][:10]) for e in st.events), default=None))


def opened_day(st: State, subject: str) -> date | None:
    """The day the child subject was opened (its first `subject` event); None for a subject the log never opened."""
    opening = st.index.of("subject", subject)
    return date.fromisoformat(opening[0]["at"][:10]) if opening else None


def people_with(st: State, role: str) -> list[dict[str, Any]]:
    rows = sorted((r for r in st.people if role in r["roles"]), key=lambda r: r["person"])
    if not rows:
        raise PageProblem(f"no person in {PEOPLE} holds role {role}")
    return rows


def generated(st: State, step_id: str, subject: str = PROGRAMME) -> tuple[str, dict[str, Any]]:
    """Text of the output named by the latest `step` event for (subject, step), plus that event's payload. Read once per
    state (page builders ask for the same output once per subject; a state's events and the outputs they name do not change
    while it is used, and a state with more events is a new State with an empty cache). A missing output is not cached."""
    return cached(st, f"generated {step_id} {subject}", lambda: _read_generated(st, step_id, subject))


def _read_generated(st: State, step_id: str, subject: str) -> tuple[str, dict[str, Any]]:
    found = None
    for e in st.index.of("step", subject):
        if e["payload"].get("step") == step_id:
            found = e
    if found is None:
        raise PageProblem(f"{step_id} has no output yet")
    rel = found["payload"].get("output")
    path = (st.private / str(rel)).resolve()
    home = cached(st, "private_resolved", st.private.resolve)  # one filesystem lookup per state, not per call
    if not isinstance(rel, str) or not path.is_relative_to(home) or not path.is_file():
        raise PageProblem(f"output of {step_id} is missing from the store")
    return path.read_text(encoding="utf-8"), found["payload"]


def spec(st: State, step_id: str, subject: str, signer: str, template: str, inputs: dict[str, Any],
         fields: list[dict[str, Any]] | None = None, intro: str = "") -> dict[str, Any]:
    d = st.step_defs[step_id]
    return {
        "template": template, "step": step_id, "subject_uri": subject, "signer": signer, "role": d["role"],
        "inputs": inputs, "fields": fields or [], "title": d["name"], "intro": intro,
    }


def per_signer(st: State, step_id: str, subject: str, template: str, inputs: dict[str, Any],
               fields: list[dict[str, Any]] | None = None, intro: str = "") -> list[dict[str, Any]]:
    role = st.step_defs[step_id]["role"]
    return [spec(st, step_id, subject, r["person"], template, inputs, fields, intro) for r in people_with(st, role)]
