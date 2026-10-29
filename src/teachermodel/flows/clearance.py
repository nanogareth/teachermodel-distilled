"""W4 clearance (standards/workflows/clearance.yaml): the evidence check, the two clearers' decisions, the head's
resolution, the `clearance` event and the lapse of a missed recheck.

    evidence-ready (auto, per candidate)  ->  a ROUND: a `step` event with the verdict detail and the evidence hash
    clearer-decision-1 / -2 (clearers)    ->  bound to the round; content checks refuse an ineligible signer
    head-resolves (head of training)      ->  only on disagreement; the hook of decision 2 skips it when they agree
    issue (auto, per candidate)           ->  the `clearance` event (clearance@1) and clearances/<id>.json (private)
    recheck-lapse (auto, per candidate)   ->  a superseding `clearance` event with outcome not_yet after a missed recheck

A round is the unit of decision. Its id derives from the candidate, the evidence hash and the clearance it follows (`after`),
and the clearance it produces is `tm:clearance/<round id>`, so every event here has a deterministic id and a replay appends
nothing. See the workflow file for when a new round opens.

Who decides (spec v0.2 W4, Users and roles, Rules; decision 0012):
- a clearer is a registered instructor at level clearer, or one a people-list person holding the clearer role is mapped to
  (`common.clearer_instructors`); the calibration that gates the role is keyed by that instructor URI, so a signer is first
  normalised through the people mapping (`person_key`: a `tm:person` mapped to an instructor is that instructor), and a
  `tm:person` clearer who is not mapped to an instructor is refused as not calibrated;
- calibrated (`rules.is_calibrated`) on the DECISION DATE, the sign-off's `signed_at`, which must fall on or after the day
  the round opened and (when the caller puts the time of ingest in `st.cache[NOW_KEY]`) no more than a day after now;
- within their modules (spec, Users and roles): holding a clearance the staffing check accepts for the candidate's unit, in
  any mode, on the decision date; or, in a FOUNDING round (decision 0017), any calibrated clearer not under a blocking bench
  decision, while fewer than two calibrated clearers other than the candidate's instructor hold the unit on that date
  (`founding`). Nothing else is waived, and the clearance a founding round issues carries `founding: true`;
- never the candidate's instructor, under any URI or mailbox (`dry_run.is_candidates_instructor`);
- the two are different people after that normalisation, and at most one of them is the instructor's coach. The spec limits
  a coach to one of the two observers; the same limit on the two clearers is an operational default (decision 0002).
  A coach is one of the instructor's own coaches (`common.coaches_of`: a person holding the coach role who lists the
  instructor in `coaches`, mapped to the instructor they are; decision 0014), not every coach.
- head-resolves is signed by a person holding head-of-training who is not the candidate's instructor.

The evidence is re-checked at every step that relies on it: when a round opens, in each decision's content check, and when
`issue` runs (a round whose evidence no longer meets the minimum issues nothing and says why in a `check`). A renewal round
counts only observations dated after the clearance it renews was issued (`since`), so a renewal rests on new evidence.

Only references and dates enter the log: the conditions and actions the clearers write stay in the stored sign-offs and in
clearances/<id>.json, and the `clearance` event's `conditions` are keys into that document.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import events, records, rules, signoff
from ..due import due_rule
from ..records import bench_blocks
from ..workflow import APPROVING, SYSTEM_ACTOR
from . import auto_step, content_check, on_signoff, register
from .common import HEAD_ROLE, is_head, PageProblem, State, cached, clearer_instructors, coaches_of, latest_day, people_with, spec
from .dry_run import FROM_RECORDING, current_environment_hashes, is_candidates_instructor, is_partner
from ..signoff import short_sha as _hex
from ..util import write_if_changed

STEP_EVIDENCE = "tm:step/evidence-ready"
STEP_D1 = "tm:step/clearer-decision-1"
STEP_D2 = "tm:step/clearer-decision-2"
STEP_HEAD = "tm:step/head-resolves"
STEP_ISSUE = "tm:step/issue"
STEP_LAPSE = "tm:step/recheck-lapse"
DECISIONS = (STEP_D1, STEP_D2)

OUTCOMES = ("cleared", "cleared_with_conditions", "not_yet")  # what a clearer or the head may decide
IN_FORCE = ("cleared", "cleared_with_conditions")
DECISION_DAYS = 14  # operational default (decision 0002): days from the day a first or new-evidence round opened
CLEARANCE_DIR = "clearances"  # under the private dir: <clearance hex>.json, the conditions and actions in words
NOW_KEY = "now"  # st.cache key: the aware datetime of the ingest, when the caller sets it (bounds signed_at from above)
SIGNED_AHEAD = timedelta(days=1)  # how far after now a signed_at may be (clock skew); operational default (decision 0002)
FOUNDING_BELOW = 2  # the two clearers of W4 (spec Domain model, "clearers (2)"): structural, not a threshold (0017)

is_instructor = is_candidates_instructor  # the same test as W3: URI, people mapping, or roster mailbox


def _stamp(stamp: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _day(stamp: Any) -> date | None:
    moment = _stamp(stamp)
    return moment.date() if moment else None


def person_key(st: State, uri: Any) -> Any:
    """The instructor URI a people-list person is mapped to (people.yaml `instructor`), else `uri` itself: the key under
    which calibrations, clearances and coaches are recorded."""
    for p in st.people:
        if p["person"] == uri and isinstance(p.get("instructor"), str):
            return p["instructor"]
    return uri


def same_person(st: State, a: Any, b: Any) -> bool:
    """True when two signer URIs are one person: equal, mapped to the same instructor, or one is the other's instructor by
    the people mapping or the roster mailbox."""
    if not (isinstance(a, str) and isinstance(b, str)):
        return False
    ka, kb = person_key(st, a), person_key(st, b)
    return a == b or ka == kb or is_instructor(st, a, kb) or is_instructor(st, b, ka)


def _write(path: Path, doc: Any) -> None:
    write_if_changed(path, (json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def _find_candidate(st: State, subject: Any) -> dict[str, Any] | None:
    info = st.subjects.get(subject)
    return info if info is not None and info.get("kind") == "candidate" else None


def _candidate(st: State, subject: str) -> dict[str, Any]:
    info = _find_candidate(st, subject)
    if info is None:
        raise PageProblem(f"{subject} is not a candidate")
    return info


# --- the evidence ------------------------------------------------------------------------------------------------


def _observations(st: State) -> list[rules.Observation]:
    """records.observations, with each one's rubric version read from its event (rules.clearance_check counts only the
    current framework major)."""
    versions = {e["id"]: e["payload"].get("rubric_version") for e in st.events if e["kind"] == "observation"}
    return [o if o.rubric_version is not None or not isinstance(versions.get(o.id), str)
            else dataclasses.replace(o, rubric_version=versions[o.id]) for o in records.observations(st.events)]


def _recorded(event: Mapping[str, Any]) -> bool:
    """An `observation` event scored from a recording, or a `dry_run` event whose checklist says it was done from one
    (W11)."""
    p = event["payload"]
    if event["kind"] == "observation":
        return p.get("from_recording") is True
    return isinstance(p.get("checks"), dict) and p["checks"].get(FROM_RECORDING) == "pass"


def evidence_since(st: State, instructor: str, since: date | None) -> date | None:
    """The day after which observations count for the instructor's clearance: `since` (a renewal), or the day of their
    latest blocking bench decision (exit or return to co-teaching) when that is later (decision 0015, integration review
    finding 4): a clearance after such a decision rests on observations made after it."""
    if not cached(st, "has bench decisions", lambda: any(e["kind"] == "bench_decision" for e in st.events)):
        return since
    blocking = bench_blocks.latest_blocking(st.events, instructor, date.max)
    if blocking is None or (since is not None and since >= blocking["at"]):
        return since
    return blocking["at"]


def verdict(st: State, info: Mapping[str, Any], since: date | None = None) -> rules.Verdict:
    """rules.clearance_check for a candidate over the records in the log. A dry run counts only while the unit's
    environment hash holds (the hash is in `detail["environment_sha256"]`); the instructor's own coaches
    (`common.coaches_of`) as the coach limit; with `since` (a renewal), only observations dated after it, and after a
    blocking bench decision only observations dated after its day (`evidence_since`).

    W11: for a partner instructor (registration type partner) only observations scored from a recording and a dry run done
    from a recording count; the reasons say how many of the others were left out."""
    domains = [d["id"] for d in st.standards["framework"]["domains"]]
    env = current_environment_hashes([info["unit"]], st.root)
    observations, log = _observations(st), st.events
    since = evidence_since(st, info["instructor"], since)
    partner = is_partner(st, info["instructor"])
    if partner:
        recorded = {e["id"] for e in st.events if e["kind"] == "observation" and _recorded(e)}
        observations = [o for o in observations if o.id in recorded]
        log = [e for e in st.events if e["kind"] != "dry_run" or _recorded(e)]
    runs = records.dry_runs(log, env)
    v = rules.clearance_check(
        info["instructor"], info["unit"], info["mode"], observations, runs, records.calibrations(st.events),
        coaches_of(st, info["instructor"]), domains, st.standards["rules"], since=since, lapses=records.lapses(st.events))
    v.detail["environment_sha256"] = env.get(info["unit"])
    if partner and not v.ok:
        live = sum(1 for e in st.events if e["kind"] == "observation" and e["payload"].get("instructor") == info["instructor"]
                   and e["payload"].get("unit") == info["unit"] and not _recorded(e))
        live_runs = sum(1 for e in st.events if e["kind"] == "dry_run" and e["payload"].get("candidate") is not None
                        and e["payload"].get("instructor") == info["instructor"] and e["payload"].get("passed") is True
                        and not _recorded(e))
        if live:
            v.reasons.append(f"{live} observation(s) not scored from a recording are not counted: a partner instructor "
                             "is cleared on recordings (W11)")
        if live_runs:
            v.reasons.append(f"{live_runs} passed dry-run(s) not done from a recording are not counted (W11)")
    return v


def round_verdict(st: State, info: Mapping[str, Any], rnd: Mapping[str, Any] | None) -> rules.Verdict:
    """The verdict on the evidence a round counts (a renewal round only what is newer than the clearance it renews)."""
    since = (rnd or {}).get("payload", {}).get("since")
    return verdict(st, info, date.fromisoformat(since) if isinstance(since, str) else None)


def evidence_sha256(v: rules.Verdict) -> str:
    """The hash of the evidence a round rests on: the observations that counted, their observers, the averages, the passed
    dry runs and the unit's current environment hash (so a dry run voided by a changed environment, and the new run that
    replaces it, change the hash)."""
    d = v.detail
    return signoff.input_sha256({"observations": d["observations"], "observers": d["observers"],
                                 "averages": d["averages"], "dry_runs": d.get("dry_runs", []),
                                 "environment_sha256": d.get("environment_sha256")})


def rounds(log: Iterable[dict[str, Any]], candidate: str) -> list[dict[str, Any]]:
    """The candidate's rounds (evidence-ready `step` events), in log order."""
    return [e for e in log if e["kind"] == "step" and e["subject_uri"] == candidate
            and e["payload"].get("step") == STEP_EVIDENCE and isinstance(e["payload"].get("round"), str)]


def latest_round(log: Iterable[dict[str, Any]], candidate: str) -> dict[str, Any] | None:
    found = rounds(log, candidate)
    return found[-1] if found else None


def clearance_uri(round_id: str) -> str:
    return f"tm:clearance/{round_id}"


def clearance_states(log: Iterable[dict[str, Any]], candidate: str) -> dict[str, dict[str, Any]]:
    """Clearance URI -> the payload of its latest `clearance` event, for the candidate's clearances, in the order they were
    first issued (a dict keeps insertion order; a later event only replaces the value)."""
    out: dict[str, dict[str, Any]] = {}
    for e in log:
        if e["kind"] == "clearance" and e["subject_uri"] == candidate and isinstance(e["payload"].get("clearance"), str):
            out[e["payload"]["clearance"]] = e["payload"]
    return out


def _round_reason(st: State, candidate: str, info: Mapping[str, Any],
                  today: date) -> tuple[str, str | None, str | None] | None:
    """(reason, after, since) when a new round should open now, else None. `after` is the clearance the round follows;
    `since` the day after which its observations count (a renewal: the day the renewed clearance was issued; a round that
    follows an undecided or a not-yet round keeps the `since` of that round)."""
    rnd = latest_round(st.events, candidate)
    if rnd is None:
        return "first", None, None
    p = rnd["payload"]
    since = p.get("since")

    def changed() -> bool:
        return p["evidence_sha256"] != evidence_sha256(round_verdict(st, info, rnd))

    states = clearance_states(st.events, candidate)
    decided = states.get(clearance_uri(p["round"]))
    if decided is None:  # an undecided round: new evidence reopens both decisions
        return ("evidence", p.get("after"), since) if changed() else None
    cid, outcome = decided["clearance"], decided["outcome"]
    blocking = evidence_since(st, info["instructor"], None)
    if outcome in IN_FORCE and blocking is not None and date.fromisoformat(decided["issued"]) <= blocking:
        # a blocking bench decision followed the clearance: it counts for nothing now (finding 4); new evidence opens a round
        return ("evidence", cid, since) if changed() else None
    if outcome in IN_FORCE:
        left = (date.fromisoformat(decided["expires"]) - today).days
        if left <= st.standards["rules"]["staffing"]["warn_expiry_days"]:  # the staffing check warns (or blocks) now
            return "renewal", cid, decided["issued"]
        if outcome == "cleared_with_conditions" and changed():
            return "recheck", cid, since
        return None
    return ("evidence", cid, since) if changed() else None


def _blocked(st: State, subject: str, reasons: list[str], now: datetime) -> list[dict[str, Any]]:
    payload = {"step": STEP_EVIDENCE, "result": "blocked", "reasons": reasons}
    checks = [e for e in st.events if e["kind"] == "check" and e["subject_uri"] == subject
              and e["payload"].get("step") == STEP_EVIDENCE]
    if checks and checks[-1]["payload"] == payload:
        return []
    return [events.make_event("check", subject, SYSTEM_ACTOR, payload, at=now.isoformat(timespec="seconds"))]


@auto_step(STEP_EVIDENCE, refresh=True, per="candidate")
def evidence_ready(st: State, candidate: str, now: datetime) -> list[dict[str, Any]]:
    """A new round when one should open (see the workflow file) and the evidence meets rules.clearance_check; a blocked
    `check` with the rule's reasons when one should open and it does not; nothing otherwise."""
    info = _find_candidate(st, candidate)
    if info is None:
        return []
    wanted = _round_reason(st, candidate, info, now.date())
    if wanted is None:
        return []
    reason, after, since = wanted
    effective = evidence_since(st, info["instructor"], date.fromisoformat(since) if since else None)
    since = effective.isoformat() if effective else None  # after a blocking bench decision, its day (finding 4)
    v = verdict(st, info, effective)
    if not v.ok:
        return _blocked(st, candidate, v.reasons, now)
    sha = evidence_sha256(v)
    # The count of earlier rounds is in the id, so evidence that returns to an earlier state (A, B, A) opens a round
    # instead of being deduped onto the first one.
    round_id = _hex({"round": [candidate, sha, after, len(rounds(st.events, candidate))]}, 16)
    payload = {"step": STEP_EVIDENCE, "round": round_id, "reason": reason, "after": after, "since": since,
               "evidence_sha256": sha, "observations": v.detail["observations"], "observers": v.detail["observers"],
               "averages": v.detail["averages"], "dry_runs": v.detail["dry_runs"]}
    return [events.make_event("step", candidate, SYSTEM_ACTOR, payload, id=_hex({"evidence_ready": [candidate, round_id]}),
                              at=now.isoformat(timespec="seconds"))]


# --- the decisions -----------------------------------------------------------------------------------------------


def _round_or_problem(st: State, candidate: str) -> dict[str, Any]:
    rnd = latest_round(st.events, candidate)
    if rnd is None:
        raise PageProblem(f"{candidate} has no clearance evidence round yet")
    return rnd


def _base_inputs(st: State, candidate: str, info: Mapping[str, Any], rnd: dict[str, Any]) -> dict[str, Any]:
    p = rnd["payload"]
    return {"candidate": candidate, "instructor": info["instructor"], "unit": info["unit"], "mode": info["mode"],
            "round": p["round"], "reason": p["reason"], "after": p["after"], "since": p.get("since"),
            "evidence_sha256": p["evidence_sha256"], "observations": p["observations"], "observers": p["observers"],
            "averages": p["averages"], "dry_runs": p.get("dry_runs", []),
            "framework_version": st.standards["framework"]["version"]}


def _signed(log: Iterable[dict[str, Any]], step: str, candidate: str, input_sha: str | None) -> list[dict[str, Any]]:
    """The approving sign-off events of `step` for the candidate that cover `input_sha`, in log order."""
    return [e for e in log if e["kind"] == "signoff" and e["subject_uri"] == candidate
            and e["payload"].get("step") == step and e["payload"].get("decision") in APPROVING
            and e["payload"].get("input_sha256") == input_sha]


def _is_coach(st: State, uri: Any, instructor: str) -> bool:
    """True when `uri` (normalised through the people mapping) is one of `instructor`'s coaches (`common.coaches_of`)."""
    return person_key(st, uri) in coaches_of(st, instructor)


def _may_have_calibration(signer: str, on: date, cals: Mapping[str, list[date]], months: int,
                          lapses: Mapping[str, list[date]] | None = None) -> bool:
    """A pass whose renewal period has not ended by `on` (it may be later) and that no audit referral of the signer
    follows (a referral on or after the pass lapses it, decision 0015): the page goes out; the content check decides on the
    signing day."""
    referred = (lapses or {}).get(signer, [])
    return any(rules.add_months(p, months) > on and not any(d >= p for d in referred) for p in cals.get(signer, []))


def previous_version(unit: str) -> str | None:
    """`sl:unit/<slug>@<n>` -> `sl:unit/<slug>@<n-1>`; None for version 1 or a reference that cannot be read."""
    slug, _, version = unit.rpartition("@")
    return f"{slug}@{int(version) - 1}" if slug and version.isdigit() and int(version) > 1 else None


def holds_unit(st: State, signer: Any, unit: str, on: date) -> bool:
    """Within their modules (spec v0.2, Users and roles): the signer (normalised through the people mapping) holds a
    clearance in force on `on` for `unit` (`rules.clearance_valid`, whatever its scope: integration review finding 8), in
    any of its modes.

    W12 (finding 9): for a new version of a unit, a clearance for the previous version of the same unit slug counts too, so
    the clearers of version n-1 can clear the authors of version n. A clearance issued on or before the signer's latest
    blocking bench decision (exit or return to co-teaching, `records.bench_blocks.latest_blocking`) counts for nothing
    (decision 0015, finding 3), as in the staffing check."""
    who = person_key(st, signer)
    rules_doc = st.standards["rules"]
    units = {unit, previous_version(unit)} - {None}
    blocking = bench_blocks.latest_blocking(st.events, who, on) if isinstance(who, str) else None
    return any(c.instructor == who and c.unit in units and rules.clearance_valid(c, on, rules_doc)
               and (blocking is None or c.issued > blocking["at"])
               for c in records.clearances(st.events))


def unit_deciders(st: State, info: Mapping[str, Any], on: date) -> list[str]:
    """The clearers who may decide on the candidate under the ordinary rule on `on`: clearers by level, other than the
    candidate's instructor, calibrated on `on` (`rules.is_calibrated`, audit referrals included) and holding the candidate's
    unit (`holds_unit`, which already sets aside a clearance a blocking bench decision followed). Instructor URIs, sorted."""

    def make() -> list[str]:
        cals, referred = records.calibrations(st.events), records.lapses(st.events)
        rules_doc = st.standards["rules"]
        return sorted({person_key(st, c) for c in clearer_instructors(st.registrations, st.events, st.people)
                       if not is_instructor(st, c, info["instructor"])
                       and rules.is_calibrated(person_key(st, c), on, cals, rules_doc, referred.get(person_key(st, c)))
                       and holds_unit(st, c, info["unit"], on)})

    return cached(st, f"unit deciders {info['instructor']} {info['unit']} {on.isoformat()}", make)


def founding(st: State, info: Mapping[str, Any], on: date) -> bool:
    """A founding round on `on` (decision 0017): fewer than two clearers could decide on the candidate under the ordinary
    rule (`unit_deciders`), so W4 could not run at all. The waiver closes by itself once two calibrated clearers other than
    the instructor hold the unit, and opens again only if that stops being true."""
    return len(unit_deciders(st, info, on)) < FOUNDING_BELOW


def within_modules(st: State, signer: Any, info: Mapping[str, Any], on: date) -> bool:
    """The signer holds the candidate's unit on `on` (`holds_unit`), or the round is a founding one on `on` and the signer is
    not under a blocking bench decision (exit or return to co-teaching, unless a clearance issued after it lifted it).
    The caller checks the rest: a clearer by level, calibrated, not the instructor."""
    if holds_unit(st, signer, info["unit"], on):
        return True
    who = person_key(st, signer)
    return (founding(st, info, on) and isinstance(who, str)
            and bench_blocks.blocking_decision(st.events, who, on) is None)


def _eligible(st: State, info: Mapping[str, Any], on: date) -> list[str]:
    cals, referred = records.calibrations(st.events), records.lapses(st.events)
    months = st.standards["rules"]["calibration"]["renewal_months"]
    return [c for c in clearer_instructors(st.registrations, st.events, st.people)
            if not is_instructor(st, c, info["instructor"])
            and _may_have_calibration(person_key(st, c), on, cals, months, referred)
            and within_modules(st, c, info, on)]


def _decision_fields() -> list[dict[str, Any]]:
    return [
        {"name": "outcome", "label": "Decision", "kind": "enum", "options": list(OUTCOMES), "required": True,
         "help": "cleared, cleared_with_conditions (list the conditions and a recheck date) or not_yet (list the actions)."},
        {"name": "conditions", "label": "Conditions (one per line)", "kind": "textarea", "required": False,
         "help": "Required for cleared_with_conditions. Kept in the private store; the log holds a reference."},
        {"name": "recheck", "label": "Recheck date", "kind": "date", "required": False,
         "help": "Required for cleared_with_conditions: after today and before the clearance would expire. A missed "
                 "recheck lapses the clearance to not yet."},
        {"name": "actions", "label": "Actions (one per line)", "kind": "textarea", "required": False,
         "help": "Required for not_yet: what the instructor should do before the next decision."},
    ]


def _d1_inputs(st: State, candidate: str) -> dict[str, Any]:
    info = _candidate(st, candidate)
    return _base_inputs(st, candidate, info, _round_or_problem(st, candidate))


def _d1_signer(st: State, candidate: str) -> str | None:
    found = _signed(st.events, STEP_D1, candidate, signoff.input_sha256(_d1_inputs(st, candidate)))
    return found[-1]["actor"] if found else None


def _d2_inputs(st: State, candidate: str) -> dict[str, Any]:
    first = _d1_signer(st, candidate)
    if first is None:
        raise PageProblem(f"{candidate}: the first clearer has not decided on this evidence yet")
    return {**_d1_inputs(st, candidate), "decision_1_signer": first}


def _pages(st: State, step: str, candidate: str, inputs: dict[str, Any], pool: list[str], intro: str):
    already = [e["actor"] for e in _signed(st.events, step, candidate, signoff.input_sha256(inputs))]
    who = sorted(set(pool) | set(already))
    if not who:
        raise PageProblem(f"{candidate}: no calibrated clearer other than the instructor can make {step}")
    return [spec(st, step, candidate, s, "approve", inputs, _decision_fields(), intro) for s in who]


INTRO = ("Decide this clearance from the evidence below: the observations that met the clearance minimum, their observers "
         "and the domain averages, and a passed dry run for this unit and mode. Two clearers decide independently; you do "
         "not see the other decision. If the two differ, the head of training resolves it.")


def _decidable(st: State, info: Mapping[str, Any], rnd: dict[str, Any]) -> date:
    """The day a decision page judges its pool on, once the round's evidence still meets the minimum: today (the newest
    event's day), as the content check judges the signer on the day of signing, never earlier than the round. Evidence
    that fell below the minimum after the round opened builds no page (PageProblem), as `issue` issues nothing: a page
    every sign-off would be refused on helps nobody, and it comes back once the evidence meets the minimum again (both
    found by the simulation, 2026-10-27)."""
    v = round_verdict(st, info, rnd)
    if not v.ok:
        raise PageProblem("the evidence no longer meets the clearance minimum: " + "; ".join(v.reasons)
                          + "; the page comes back once it does")
    opened = date.fromisoformat(rnd["at"][:10])
    return max(opened, latest_day(st) or opened)


@register(STEP_D1)
def _b_decision_1(st: State, candidate: str):
    info = _candidate(st, candidate)
    rnd = _round_or_problem(st, candidate)
    on = _decidable(st, info, rnd)
    inputs = _base_inputs(st, candidate, info, rnd)
    return _pages(st, STEP_D1, candidate, inputs, _eligible(st, info, on), INTRO)


@register(STEP_D2)
def _b_decision_2(st: State, candidate: str):
    info = _candidate(st, candidate)
    on = _decidable(st, info, _round_or_problem(st, candidate))
    inputs = _d2_inputs(st, candidate)
    first = inputs["decision_1_signer"]
    pool = [c for c in _eligible(st, info, on)
            if not same_person(st, c, first)
            and not (_is_coach(st, first, info["instructor"]) and _is_coach(st, c, info["instructor"]))]
    return _pages(st, STEP_D2, candidate, inputs, pool,
                  INTRO + "\n\nYou are the second clearer. The first clearer is named below; their decision is not.")


def parse_decision(fields: Any, signed_on: date | None, rules_doc: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """(the decision, reasons) from a decision page's fields: {outcome, conditions [lines], recheck date|None, actions
    [lines]}. A reason names the field, never its value."""
    if not isinstance(fields, Mapping):
        return None, ["the sign-off carries no fields"]
    outcome = fields.get("outcome")
    if outcome not in OUTCOMES:
        return None, [f"outcome: one of {', '.join(OUTCOMES)} is required"]

    def lines(name: str) -> list[str]:
        value = fields.get(name)
        return [s.strip() for s in value.splitlines() if s.strip()] if isinstance(value, str) else []

    conditions, actions = lines("conditions"), lines("actions")
    recheck: date | None = None
    reasons: list[str] = []
    if outcome == "cleared_with_conditions":
        if not conditions:
            reasons.append("conditions: at least one condition is required for cleared_with_conditions")
        raw = fields.get("recheck")
        try:
            recheck = date.fromisoformat(raw) if isinstance(raw, str) and len(raw) == 10 else None
        except ValueError:
            recheck = None
        if recheck is None:
            reasons.append("recheck: a recheck date (YYYY-MM-DD) is required for cleared_with_conditions")
        elif signed_on is None or recheck <= signed_on:
            reasons.append("recheck: the recheck date must be after the day of the decision")
        elif recheck >= rules.expiry_date(signed_on, rules_doc):
            reasons.append("recheck: the recheck date must fall before the clearance would expire")
    if outcome == "not_yet" and not actions:
        reasons.append("actions: at least one action is required for not_yet")
    if reasons:
        return None, reasons
    return {"outcome": outcome, "conditions": conditions if outcome == "cleared_with_conditions" else [],
            "recheck": recheck.isoformat() if recheck else None, "actions": actions if outcome == "not_yet" else []}, []


def _signed_at_reasons(st: State, document: Mapping[str, Any], rnd: Mapping[str, Any] | None) -> list[str]:
    """The round-specific bounds on the decision date: not before the day the round opened (a backdated sign-off cannot
    borrow a calibration or a clearance that has lapsed since), and not more than SIGNED_AHEAD after the time of ingest
    when the caller gave it (`st.cache[NOW_KEY]`). The bridge bounds signed_at against the receipt as well."""
    moment = _stamp(document.get("signed_at"))
    if moment is None:
        return ["signed_at: a date-time with a time zone is required"]
    reasons = []
    if rnd is not None and moment.date() < date.fromisoformat(rnd["at"][:10]):
        reasons.append(f"signed_at: before this evidence round opened on {rnd['at'][:10]}")
    now = st.cache.get(NOW_KEY)
    if isinstance(now, datetime) and now.tzinfo is not None and moment > now + SIGNED_AHEAD:
        reasons.append("signed_at: more than a day after the time of ingest")
    return reasons


def _decision_reasons(st: State, document: Mapping[str, Any], step: str) -> list[str]:
    candidate = document.get("subject_uri")
    info = _find_candidate(st, candidate)
    if info is None:
        return ["the subject is not a candidate"]
    rnd = latest_round(st.events, candidate)
    if rnd is None:
        return ["there is no clearance evidence round for this candidate"]
    signer, signed_on = document.get("signer"), _day(document.get("signed_at"))
    rules_doc = st.standards["rules"]
    reasons = _signed_at_reasons(st, document, rnd)
    if is_instructor(st, signer, info["instructor"]):
        reasons.append("the signer is the instructor of this candidate")
    who = person_key(st, signer)
    if signed_on is None or not rules.is_calibrated(who, signed_on, records.calibrations(st.events), rules_doc,
                                                    records.lapses(st.events).get(who)):
        reasons.append("the signer is not a calibrated clearer on the day of signing")
    if signed_on is None or not within_modules(st, signer, info, signed_on):
        reasons.append(f"the signer holds no valid clearance for {info['unit']} on the day of signing; a clearer decides "
                       "only within their modules (a founding round, decision 0017, applies only while fewer than two "
                       "calibrated clearers hold the unit, and never to a clearer under a blocking bench decision)")
    if step == STEP_D2:
        first = _d1_signer(st, candidate)
        if first is None:
            reasons.append("decision 1 has not been made on this evidence")
        elif same_person(st, signer, first):
            reasons.append("the signer made decision 1; two different clearers decide")
        elif _is_coach(st, first, info["instructor"]) and _is_coach(st, signer, info["instructor"]):
            reasons.append("both clearers would be the instructor's coaches; a coach may be one of the two at most")
    if not round_verdict(st, info, rnd).ok:
        reasons.append("the evidence no longer meets the clearance minimum; wait for the next round")
    reasons += parse_decision(document.get("fields"), signed_on, rules_doc)[1]
    return reasons


@content_check(STEP_D1)
def _check_d1(st: State, document: dict[str, Any]) -> list[str]:
    return _decision_reasons(st, document, STEP_D1)


@content_check(STEP_D2)
def _check_d2(st: State, document: dict[str, Any]) -> list[str]:
    return _decision_reasons(st, document, STEP_D2)


# --- reading the decisions back ----------------------------------------------------------------------------------


def _stored(st: State, sid: str, extra: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if extra and sid in extra:
        return extra[sid]
    path = st.private / "signoffs" / f"{sid}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("id") == sid else None


def _read(st: State, step: str, candidate: str, inputs: dict[str, Any],
          extra: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The latest approving sign-off of `step` on these inputs, parsed: {step, signer, signoff_id, signed_on, decision}."""
    found = _signed(st.events, step, candidate, signoff.input_sha256(inputs))
    if not found:
        return None
    event = found[-1]
    doc = _stored(st, event["payload"]["signoff_id"], extra)
    if doc is None:
        return None
    signed_on = _day(doc.get("signed_at"))
    decision, problems = parse_decision(doc.get("fields"), signed_on, st.standards["rules"])
    if decision is None or problems:
        return None
    return {"step": step, "signer": event["actor"], "signoff_id": event["payload"]["signoff_id"],
            "signed_on": signed_on.isoformat() if signed_on else None, "decision": decision}


def _both(st: State, candidate: str, extra: Mapping[str, dict[str, Any]] | None = None):
    first = _read(st, STEP_D1, candidate, _d1_inputs(st, candidate), extra)
    if first is None:
        return None
    try:
        second = _read(st, STEP_D2, candidate, _d2_inputs(st, candidate), extra)
    except PageProblem:
        return None
    return (first, second) if second is not None else None


def head_inputs(st: State, candidate: str, extra: Mapping[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    both = _both(st, candidate, extra)
    if both is None:
        raise PageProblem(f"{candidate}: both clearers have not decided on this evidence yet")
    rnd = _round_or_problem(st, candidate)
    return {"candidate": candidate, "round": rnd["payload"]["round"], "evidence_sha256": rnd["payload"]["evidence_sha256"],
            "decisions": [{"step": d["step"], "signer": d["signer"], **d["decision"]} for d in both]}


def _agree(inputs: Mapping[str, Any]) -> bool:
    return len({d["outcome"] for d in inputs["decisions"]}) == 1


@register(STEP_HEAD)
def _b_head(st: State, candidate: str):
    info = _candidate(st, candidate)
    inputs = head_inputs(st, candidate)
    heads = [r["person"] for r in people_with(st, HEAD_ROLE) if not is_instructor(st, r["person"], info["instructor"])]
    if not heads:
        raise PageProblem(f"{candidate}: no head of training other than the instructor can resolve it")
    return [spec(st, STEP_HEAD, candidate, h, "approve", inputs, _decision_fields(),
                 "The two clearers disagree. Their decisions, conditions and actions are below. Your decision is the "
                 "outcome of this clearance; both clearers stay named on it.")
            for h in heads]


@content_check(STEP_HEAD)
def _check_head(st: State, document: dict[str, Any]) -> list[str]:
    """The head of training (a people-list person holding the role), never the candidate's instructor, signing
    within the round's bounds, with a decision that carries what its outcome needs."""
    candidate = document.get("subject_uri")
    info = _find_candidate(st, candidate)
    if info is None:
        return ["the subject is not a candidate"]
    signer = document.get("signer")
    reasons = _signed_at_reasons(st, document, latest_round(st.events, candidate))
    if not is_head(st, signer):
        reasons.append("the signer is not the head of training")
    if is_instructor(st, signer, info["instructor"]):
        reasons.append("the signer is the instructor of this candidate")
    return reasons + parse_decision(document.get("fields"), _day(document.get("signed_at")), st.standards["rules"])[1]


@on_signoff(STEP_D2)
def _skip_head_when_they_agree(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """When the second decision has the first's outcome, the system `step` event marked skipped that closes head-resolves
    for the inputs it would show (workflow `skippable`)."""
    candidate = signed["subject_uri"]
    try:
        inputs = head_inputs(st, candidate, {document["id"]: document})
    except (PageProblem, KeyError):
        return [], []
    if not _agree(inputs):
        return [], []
    sha = signoff.input_sha256(inputs)
    return [events.make_event(
        "step", candidate, SYSTEM_ACTOR,
        {"step": STEP_HEAD, "skipped": True, "reason": "the clearers agree", "input_sha256": sha},
        id=_hex({"head_skipped": [candidate, sha]}), at=now.isoformat(timespec="seconds"))], []


# --- issue -------------------------------------------------------------------------------------------------------


def partner_scope(st: State, instructor: str) -> dict[str, Any]:
    """W11: the `scope` of a clearance for a partner instructor (registration type partner): `{partner: the registration's
    organisation, regions: its regions}`. Empty for anyone else, whose clearances are unscoped."""
    if not is_partner(st, instructor):
        return {}
    reg = st.registrations[instructor]
    scope: dict[str, Any] = {}
    if isinstance(reg.get("organisation"), str):
        scope["partner"] = reg["organisation"]
    if isinstance(reg.get("regions"), list) and reg["regions"]:
        scope["regions"] = list(reg["regions"])
    return scope


def _merge(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Agreeing decisions: their conditions and actions joined in order without repeats, the earliest recheck."""
    out = {"outcome": decisions[0]["outcome"], "conditions": [], "actions": [], "recheck": None}
    for d in decisions:
        out["conditions"] += [c for c in d["conditions"] if c not in out["conditions"]]
        out["actions"] += [a for a in d["actions"] if a not in out["actions"]]
    dates = [d["recheck"] for d in decisions if d["recheck"]]
    out["recheck"] = min(dates) if dates else None
    return out


@auto_step(STEP_ISSUE, refresh=True, per="candidate")
def issue(st: State, candidate: str, now: datetime) -> list[dict[str, Any]]:
    """The `clearance` event of the latest round once it is decided (both clearers, and the head when they differ), its
    private document, and a `step` event. Nothing when the round's clearance is already on record (a lapse supersedes it
    by a later event of the same id, which this never undoes)."""
    info = _find_candidate(st, candidate)
    rnd = latest_round(st.events, candidate)
    if info is None or rnd is None:
        return []
    cid = clearance_uri(rnd["payload"]["round"])
    if cid in clearance_states(st.events, candidate):
        return []
    try:
        inputs = head_inputs(st, candidate)
    except PageProblem:
        return []
    deciding = list(_both(st, candidate))
    if _agree(inputs):
        final = _merge([d["decision"] for d in deciding])
    else:
        head = _read(st, STEP_HEAD, candidate, inputs)
        if head is None:
            return []
        deciding.append(head)
        final = {**head["decision"]}
    stamp = now.isoformat(timespec="seconds")
    v = round_verdict(st, info, rnd)
    if not v.ok:  # the evidence changed after the decisions (a dry run voided, a calibration withdrawn): say so once
        why = ["evidence no longer meets the clearance minimum: " + "; ".join(v.reasons)]
        return [events.make_event("check", candidate, SYSTEM_ACTOR,
                                  {"step": STEP_ISSUE, "result": "blocked", "clearance": cid, "reasons": why},
                                  id=_hex({"issue_evidence_blocked": [cid, why]}), at=stamp)]
    issued = max(date.fromisoformat(d["signed_on"]) for d in deciding)
    hexid = cid.split("/", 1)[1]
    key = f"{CLEARANCE_DIR}/{hexid}.json"
    _write(st.private / key, {
        "clearance": cid, "candidate": candidate, "outcome": final["outcome"], "conditions": final["conditions"],
        "actions": final["actions"], "recheck": final["recheck"],
        "decisions": [{"step": d["step"], "signer": d["signer"], "signoff_id": d["signoff_id"]} for d in deciding]})
    payload = {
        "clearance": cid, "candidate": candidate, "instructor": info["instructor"], "unit": info["unit"],
        "modes": [info["mode"]], "outcome": final["outcome"],
        "conditions": [f"{key}#conditions/{n}" for n in range(len(final["conditions"]))],
        "recheck": final["recheck"], "clearers": [d["signer"] for d in deciding if d["step"] in DECISIONS],
        "observations": rnd["payload"]["observations"], "issued": issued.isoformat(),
        "expires": rules.expiry_date(issued, st.standards["rules"]).isoformat(),
        "framework_version": st.standards["framework"]["version"],
    }
    scope = partner_scope(st, info["instructor"])
    if scope:
        payload["scope"] = scope  # W11: a partner's clearance covers that partner and its regions only
    if any(not holds_unit(st, d["signer"], info["unit"], date.fromisoformat(d["signed_on"]))
           for d in deciding if d["step"] in DECISIONS):
        payload["founding"] = True  # decision 0017: a clearer decided under the founding waiver (held no clearance that day)
    made = events.make_event("clearance", candidate, SYSTEM_ACTOR, payload, id=_hex({"clearance": cid}), at=stamp)
    problems = events.check_event(made)
    if problems:  # never append a clearance that breaks its contract; say so once
        return [events.make_event("check", candidate, SYSTEM_ACTOR,
                                  {"step": STEP_ISSUE, "result": "blocked", "reasons": problems},
                                  id=_hex({"issue_blocked": [cid, problems]}), at=stamp)]
    return [made, events.make_event("step", candidate, SYSTEM_ACTOR, {"step": STEP_ISSUE, "clearance": cid},
                                    id=_hex({"issued": cid}), at=stamp)]


# --- recheck-lapse -----------------------------------------------------------------------------------------------


def _current(log: Iterable[dict[str, Any]], candidate: str) -> dict[str, Any] | None:
    """The latest state of the candidate's most recently issued clearance."""
    states = clearance_states(log, candidate)
    return list(states.values())[-1] if states else None


@auto_step(STEP_LAPSE, refresh=True, per="candidate")
def recheck_lapse(st: State, candidate: str, now: datetime) -> list[dict[str, Any]]:
    """A cleared_with_conditions clearance whose recheck date has passed (the run is after it) and that no later clearance
    replaced: a superseding `clearance` event, same id and payload, outcome not_yet, and a `step` event. A clearance that is
    not conditional has nothing to recheck: a `step` event says so once. A conditional one still in time: nothing."""
    p = _current(st.events, candidate)
    if p is None:
        return []
    stamp = now.isoformat(timespec="seconds")
    cid = p["clearance"]
    if any(e["kind"] == "step" and e["subject_uri"] == candidate and e["payload"].get("step") == STEP_LAPSE
           and e["payload"].get("clearance") == cid for e in st.events):
        return []  # this clearance has been dealt with (lapsed, or nothing to recheck)
    if p["outcome"] != "cleared_with_conditions":
        return [events.make_event("step", candidate, SYSTEM_ACTOR,
                                  {"step": STEP_LAPSE, "clearance": cid, "result": "nothing to recheck"},
                                  id=_hex({"no_recheck": cid}), at=stamp)]
    if not p.get("recheck") or now.date() <= date.fromisoformat(p["recheck"]):
        return []
    lapsed = events.make_event("clearance", candidate, SYSTEM_ACTOR, {**p, "outcome": "not_yet"},
                               id=_hex({"lapsed": cid}), at=stamp)
    return [lapsed, events.make_event("step", candidate, SYSTEM_ACTOR,
                                      {"step": STEP_LAPSE, "clearance": cid, "result": "lapsed"},
                                      id=_hex({"lapse_step": cid}), at=stamp)]


# --- due rules ---------------------------------------------------------------------------------------------------


@due_rule("clearance_expiry")
def clearance_expiry(step: dict[str, Any], subject: str, info: dict[str, Any], log: Any, today: date) -> date | None:
    """When the clearers' decisions on the current round fall due: for a renewal round, the expiry date of the clearance it
    renews (the round opens rules.staffing.warn_expiry_days before it, so `next` shows the renewal that far ahead); for a
    recheck round, the recheck date of the conditional clearance; otherwise DECISION_DAYS (an operational default) after
    the round opened. None before the first round."""
    if info.get("kind") != "candidate":
        return None
    events_ = list(log)
    rnd = latest_round(events_, subject)
    if rnd is None:
        return None
    p = rnd["payload"]
    after = clearance_states(events_, subject).get(p.get("after") or "")
    if p.get("reason") == "renewal" and after:
        return date.fromisoformat(after["expires"])
    if p.get("reason") == "recheck" and after and after.get("recheck"):
        return date.fromisoformat(after["recheck"])
    return date.fromisoformat(rnd["at"][:10]) + timedelta(days=DECISION_DAYS)


@due_rule("conditional_recheck")
def conditional_recheck(step: dict[str, Any], subject: str, info: dict[str, Any], log: Any, today: date) -> date | None:
    """The recheck date of the candidate's current clearance while it is cleared with conditions; None otherwise."""
    if info.get("kind") != "candidate":
        return None
    p = _current(list(log), subject)
    if p is None or p["outcome"] != "cleared_with_conditions" or not p.get("recheck"):
        return None
    return date.fromisoformat(p["recheck"])
