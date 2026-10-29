"""W2 observation (standards/workflows/observation.yaml, flows/observation.py, records/observations.py).

propose-observations (auto, per candidate) -> assignments-approved (coordinator batch, opens the assignment subjects)
-> observe (the assigned observer) and self-assessment (the instructor), per assignment -> release (auto): the
observation events, written only once every assignment of a delivery has its observe sign-off (blind until then).

Sign-offs here are applied the way `app.do_ingest` applies them after the bridge accepted them (the sign-off event, the
stored document, the registered hooks), because the bridge cannot yet accept a signer for a child subject; see the report
of the stream. Fictional people only.
"""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from clearer_helpers import calibrate, set_level
from conftest import make_fictional_store
from privacy_helpers import import_roster_ungated
from world_cache import copy_world

from teachermodel import app, bridge, due, events, flows, records, rules, signoff, workflow
from teachermodel import pages as pagegen
from teachermodel.flows import clearance, observation
from teachermodel.standards import ROOT, check_standards, load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
UNIT = "sl:unit/example-agent-loop@1"
INSTRUCTOR = "tm:instructor/p3x9d"  # cleared; delivers the example unit in all three modes
CANDIDATE = "tm:candidate/p3x9d--example-agent-loop-1--remote"
K7, C5, R8 = "tm:instructor/k7m2q", "tm:instructor/c5w1t", "tm:instructor/r8n4h"
COORD = "tm:person/coord-1"
STEP_PROPOSE, STEP_APPROVED, STEP_OBSERVE, STEP_SELF, STEP_RELEASE = (
    f"tm:step/{s}" for s in ("propose-observations", "assignments-approved", "observe", "self-assessment", "release"))
DOMAINS = [d["id"] for d in load_standards()["framework"]["domains"]]
STEP_ASSIGN = "tm:step/assign-observer"
NOTE = "ZETA-NOTE the learner asked about retries and the answer was exact"


def log(private):
    return app.read_events(private)


def of_kind(private, kind):
    return [e for e in log(private) if e["kind"] == kind]


EVERYONE = (INSTRUCTOR, K7, C5, R8)  # the example roster; add_coaches' default is a coach of each of them


def add_coaches(private, *slugs, of=EVERYONE):
    """A coach is a person with the coach role, mapped to the instructor of that slug (people.yaml `instructor`), who coaches
    the instructors `of` (people.yaml `coaches`, read by flows.common.coaches_of). By default a coach of every instructor in
    the example roster, which is what "every coach coaches everyone" used to mean."""
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for s in slugs:
        doc["people"].append({"person": f"tm:person/{s}", "name": f"Coach {s}", "email": f"coach.{s}@example.com",
                              "roles": ["coach"], "instructor": f"tm:instructor/{s}", "coaches": list(of)})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def _build_store(base, roster_bytes, clearers, coaches, run, calibrated, coaches_of):
    private = make_fictional_store(base)
    roster = base / "roster-in.yaml"
    roster.write_bytes(roster_bytes)
    import_roster_ungated(private, roster, T0)
    for s in clearers:
        set_level(private, f"tm:instructor/{s}", "clearer")
    calibrate(private, *(clearers if calibrated is None else calibrated))
    add_coaches(private, *coaches, of=coaches_of)
    if run:
        app.do_run(private, now=T0)


def store(fictional_store, example_roster, clearers=("k7m2q", "c5w1t", "r8n4h"), coaches=(), run=True, calibrated=None,
          coaches_of=EVERYONE):
    """The roster imported, `clearers` at level clearer, each calibrated unless `calibrated` names who is (an observer must
    be calibrated on the day), `coaches` mapped (each coaching `coaches_of`, everyone by default), and one run: built once
    per session for each set of arguments (conftest.copy_world) and copied into the test's tmp_path, beside
    `fictional_store`."""
    data = example_roster.read_bytes()
    key = ("observation_store", hashlib.sha256(data).hexdigest(), tuple(clearers), tuple(coaches), run,
           None if calibrated is None else tuple(calibrated), tuple(coaches_of))
    copy_world(key, lambda base: _build_store(base, data, clearers, coaches, run, calibrated, coaches_of),
               fictional_store.parent)
    return fictional_store


def proposal_steps(private, candidate=CANDIDATE):
    """The `step` events of the candidate's proposal rounds, in log order."""
    return [e for e in log(private) if e["kind"] == "step" and e["subject_uri"] == candidate
            and e["payload"].get("step") == STEP_PROPOSE]


def proposal(private, candidate=CANDIDATE):
    """The latest proposal of the candidate (round 1 is generated/observations/<slug>.json)."""
    slug = candidate.split("/", 1)[1]
    found = proposal_steps(private, candidate)
    rel = found[-1]["payload"]["output"] if found else f"generated/observations/{slug}.json"
    return json.loads((private / rel).read_text(encoding="utf-8"))


def sign(private, step, subject, signer, fields, *, decision="approve", at="2026-10-27T09:00:00+00:00"):
    """Apply a sign-off as do_ingest does once the bridge accepted it: the event, the stored document, the hooks."""
    st = app.load_state(private)
    spec = app._page_specs(st, step, subject)[0]
    sid = signoff.input_sha256([step, subject, signer, at])[:16]
    doc = {"schema": "tm:contract/signoff@1", "id": sid, "step": step, "subject_uri": subject,
           "input_sha256": signoff.input_sha256(spec["inputs"]), "decision": decision, "fields": fields,
           "signer": signer, "signed_at": at, "page_template_sha256": pagegen.template_sha256(spec["template"])}
    event = signoff.to_event(doc, "sender@example.com")
    applied = bridge.Applied(events=[event], private=[(f"signoffs/{sid}.json", doc)])
    hook_events, hook_docs = app._signoff_hooks(st, applied, datetime.fromisoformat(at))
    app._store_documents(private, applied.private)
    app._store_documents(private, hook_docs, under="")
    app.append_new(private, [event, *hook_events])
    return event


def approve_batch(private, candidate=CANDIDATE, **kw):
    rows = {r["key"]: "approve" for r in proposal(private, candidate)["rows"]}
    return sign(private, STEP_APPROVED, candidate, COORD, {"rows": rows}, **kw)


def observe_fields(score=3, day="2026-10-27", **over):
    out = {"date": day, "length": "full", "lead": True, "mode": "remote",
           **{d: {"score": score, "note": f"{NOTE} ({d})"} for d in DOMAINS}}
    out.update(over)
    return out


def assignments(private, candidate=CANDIDATE):
    return sorted((e for e in of_kind(private, "subject") if e["payload"]["subject_kind"] == "assignment"
                   and e["payload"]["attrs"]["candidate"] == candidate), key=lambda e: e["subject_uri"])


def due_ids(private, now=T0):
    return {(d.step, d.subject) for d in app.due_steps(app.load_state(private), now.date())}


def observed(private, score=3, candidate=CANDIDATE):
    """Both observers of the candidate's delivery sign; returns the assignments."""
    found = assignments(private, candidate)
    for n, a in enumerate(found):
        sign(private, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"],
             observe_fields(score), at=f"2026-10-28T1{n}:00:00+00:00")
    return found


# --- the workflow file ------------------------------------------------------------------------------------------


def wf():
    return {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/observation"]


def test_the_workflow_file_defines_its_six_steps():
    steps = {s["id"]: s for s in wf()["steps"]}
    assert set(steps) == {STEP_PROPOSE, STEP_APPROVED, STEP_ASSIGN, STEP_OBSERVE, STEP_SELF, STEP_RELEASE}
    shape = {sid: (s["type"], s["role"], s["subject"]) for sid, s in steps.items()}
    assert shape == {
        STEP_PROPOSE: ("auto", "coordinator", "candidate"),
        STEP_APPROVED: ("human", "coordinator", "candidate"),
        STEP_ASSIGN: ("human", "coordinator", "candidate"),  # the ad-hoc assignment (tests/test_adhoc_assignment.py)
        STEP_OBSERVE: ("human", "clearer", "assignment"),
        STEP_SELF: ("human", "instructor", "assignment"),
        STEP_RELEASE: ("auto", "coordinator", "assignment"),
    }
    assert steps[STEP_APPROVED]["done_when"].get("bind") == "input" and steps[STEP_APPROVED]["page"] == "batch_approve"
    assert steps[STEP_OBSERVE]["page"] == "approve" and steps[STEP_SELF]["page"] == "self_assessment"
    assert set(wf()["event_kinds"]) >= {"step", "signoff", "subject", "observation"}


def test_the_observation_window_rule_is_registered_and_used_by_the_human_steps():
    assert "observation_window" in due.names()
    steps = {s["id"]: s for s in wf()["steps"]}
    assert steps[STEP_OBSERVE]["due"] == steps[STEP_SELF]["due"] == "observation_window"


def test_standards_validate_with_the_observation_file():
    assert check_standards(ROOT) == []


def test_every_step_has_its_runner_or_builder():
    assert {STEP_PROPOSE, STEP_RELEASE} <= set(flows.AUTO_STEPS)
    assert flows.AUTO_STEPS[STEP_PROPOSE].per == "candidate" and flows.AUTO_STEPS[STEP_RELEASE].per == "assignment"
    assert {STEP_APPROVED, STEP_OBSERVE, STEP_SELF} <= set(flows.PAGE_SPECS)
    assert STEP_APPROVED in flows.SIGNOFF_HOOKS and STEP_OBSERVE in flows.SIGNOFF_HOOKS


# --- choosing observers (pure) ----------------------------------------------------------------------------------

POOL = [f"tm:instructor/o{n}" for n in range(8)]


def test_the_choice_is_hash_ranked_and_does_not_depend_on_the_order_of_the_pool():
    a = observation.choose_observers(CANDIDATE, INSTRUCTOR, POOL, set(), 2, 1)
    b = observation.choose_observers(CANDIDATE, INSTRUCTOR, list(reversed(POOL)), set(), 2, 1)
    assert a == b
    ranked = sorted(POOL, key=lambda o: hashlib.sha256(f"{CANDIDATE}:{o}".encode()).hexdigest())
    assert a == ranked[:2]
    assert observation.rank(CANDIDATE, a[0]) < observation.rank(CANDIDATE, a[1])


def test_the_rotation_differs_between_candidates():
    firsts = {observation.choose_observers(f"tm:candidate/x{n}--u-1--remote", INSTRUCTOR, POOL, set(), 1, 1)[0]
              for n in range(12)}
    assert len(firsts) > 1


def test_the_instructor_is_never_chosen():
    pool = [INSTRUCTOR, *POOL[:2]]
    for n in range(20):
        chosen = observation.choose_observers(f"tm:candidate/y{n}--u-1--remote", INSTRUCTOR, pool, set(), 2, 1)
        assert INSTRUCTOR not in chosen and sorted(chosen) == sorted(POOL[:2])


def test_at_most_the_allowed_number_of_coaches_is_chosen():
    coaches = set(POOL[:6])  # six of eight are coaches: ranking alone would often pick two
    for n in range(30):
        chosen = observation.choose_observers(f"tm:candidate/z{n}--u-1--remote", INSTRUCTOR, POOL, coaches, 2, 1)
        assert len(chosen) == 2 and len(set(chosen) & coaches) <= 1


def test_fewer_than_asked_when_the_pool_cannot_supply_them():
    assert len(observation.choose_observers(CANDIDATE, INSTRUCTOR, POOL[:1], set(), 2, 1)) == 1
    assert len(observation.choose_observers(CANDIDATE, INSTRUCTOR, POOL[:2], set(POOL[:2]), 2, 1)) == 1  # two coaches
    assert len(observation.choose_observers(CANDIDATE, INSTRUCTOR, POOL[:2], set(POOL[:2]), 2, 0)) == 0


# --- propose-observations ---------------------------------------------------------------------------------------


def test_a_proposal_is_written_for_each_candidate_with_the_minimum_observers(fictional_store, example_roster):
    store(fictional_store, example_roster)
    rows = proposal(fictional_store)["rows"]
    need = load_standards()["rules"]["clearance"]["min_distinct_observers"]
    assert len(rows) == need >= 2
    observers = [r["attrs"]["observer"] for r in rows]
    assert len(set(observers)) == len(observers) and INSTRUCTOR not in observers
    assert set(observers) <= {K7, C5, R8}
    for r in rows:
        a = r["attrs"]
        assert r["key"] == observation.assignment_uri(CANDIDATE, a["observer"], a["delivery_ref"])
        assert (a["candidate"], a["instructor"], a["unit"], a["mode"]) == (CANDIDATE, INSTRUCTOR, UNIT, "remote")
        assert a["length"] == "full" and a["lead"] is True  # at least one full lead observation
        assert r["changed"] is True and r["summary"]
    assert len({r["attrs"]["delivery_ref"] for r in rows}) == 1  # the pair observes the same session


def test_the_proposal_step_is_done_and_writes_a_step_event_naming_the_output(fictional_store, example_roster):
    store(fictional_store, example_roster)
    (done,) = [e for e in of_kind(fictional_store, "step")
               if e["payload"].get("step") == STEP_PROPOSE and e["subject_uri"] == CANDIDATE]
    assert done["payload"]["output"] == "generated/observations/p3x9d--example-agent-loop-1--remote.json"
    assert (STEP_PROPOSE, CANDIDATE) not in due_ids(fictional_store)
    assert (STEP_APPROVED, CANDIDATE) in due_ids(fictional_store)


def test_the_proposal_is_deterministic(fictional_store, example_roster, tmp_path):
    store(fictional_store, example_roster)
    first = proposal(fictional_store)
    other = tmp_path / "again"
    (other / "identities").mkdir(parents=True)
    for name in ("settings.yaml", "identities/people.yaml"):
        (other / name).write_bytes((fictional_store / name).read_bytes())
    import_roster_ungated(other, example_roster, T0)
    for s in ("k7m2q", "c5w1t", "r8n4h"):
        set_level(other, f"tm:instructor/{s}", "clearer")
    calibrate(other, "k7m2q", "c5w1t", "r8n4h")
    app.do_run(other, now=T0 + timedelta(days=3))
    assert proposal(other) == first


def test_a_second_run_changes_nothing(fictional_store, example_roster):
    store(fictional_store, example_roster)
    before = log(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert log(fictional_store) == before


def test_the_instructor_never_observes_themself_even_as_a_clearer(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("p3x9d", "k7m2q", "c5w1t"))
    observers = {r["attrs"]["observer"] for r in proposal(fictional_store)["rows"]}
    assert INSTRUCTOR not in observers and observers == {K7, C5}
    other = "tm:candidate/k7m2q--example-agent-loop-1--in-person"  # k7m2q is a clearer and has candidates of their own
    assert K7 not in {r["attrs"]["observer"] for r in proposal(fictional_store, other)["rows"]}


def test_a_coach_is_never_the_second_observer(fictional_store, example_roster):
    # k7m2q and c5w1t are both coaches of everyone: the pair must be one of them and r8n4h.
    store(fictional_store, example_roster, coaches=("k7m2q", "c5w1t"))
    for cand in sorted(u for u, i in app.load_state(fictional_store).subjects.items()
                       if i["kind"] == "candidate" and i["instructor"] == INSTRUCTOR):
        observers = {r["attrs"]["observer"] for r in proposal(fictional_store, cand)["rows"]}
        assert R8 in observers and len(observers & {K7, C5}) == 1, (cand, observers)


def test_a_coach_of_someone_else_is_not_limited_as_a_coach(fictional_store, example_roster):
    """coaches_of is per instructor: coaches of r8n4h only are ordinary clearers when p3x9d is observed."""
    top = sorted((K7, C5, R8), key=lambda o: observation.rank(CANDIDATE, o))[:2]
    store(fictional_store, example_roster, coaches=tuple(o.split("/", 1)[1] for o in top), coaches_of=(R8,))
    assert {r["attrs"]["observer"] for r in proposal(fictional_store)["rows"]} == set(top)
    st = app.load_state(fictional_store)
    assert observation.coaches(st, INSTRUCTOR) == set() and observation.coaches(st, R8) == set(top) - {R8}


def test_a_coach_of_this_instructor_is_limited_to_one_observer(fictional_store, example_roster):
    ranked = sorted((K7, C5, R8), key=lambda o: observation.rank(CANDIDATE, o))
    top = ranked[:2]
    store(fictional_store, example_roster, coaches=tuple(o.split("/", 1)[1] for o in top), coaches_of=(INSTRUCTOR,))
    observers = {r["attrs"]["observer"] for r in proposal(fictional_store)["rows"]}
    assert ranked[2] in observers and len(observers & set(top)) == 1
    assert observation.coaches(app.load_state(fictional_store), INSTRUCTOR) == set(top)


def blocked_note(private, candidate=CANDIDATE):
    path = private / "generated" / "observations" / f"{candidate.split('/', 1)[1]}.blocked.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def test_no_proposal_when_only_coaches_could_observe(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("k7m2q", "c5w1t"), coaches=("k7m2q", "c5w1t"))
    slug = CANDIDATE.split("/", 1)[1]
    assert not (fictional_store / "generated" / "observations" / f"{slug}.json").exists()
    assert (STEP_PROPOSE, CANDIDATE) in due_ids(fictional_store)  # still waiting
    note = blocked_note(fictional_store)
    assert note["step"] == STEP_PROPOSE and note["candidate"] == CANDIDATE and note["reasons"]
    # (W4's evidence-ready writes its own blocked check on the candidate; this step writes none)
    assert not [e for e in log(fictional_store) if e["subject_uri"] == CANDIDATE and e["kind"] in ("step", "check")
                and e["payload"].get("step") == STEP_PROPOSE]
    before = log(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert log(fictional_store) == before  # waiting appends nothing


def test_a_proposal_follows_when_a_clearer_appears_later(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("k7m2q",))
    assert (STEP_PROPOSE, CANDIDATE) in due_ids(fictional_store)
    set_level(fictional_store, C5, "clearer", at="2026-10-26T09:00:00+00:00")
    calibrate(fictional_store, C5)
    assert blocked_note(fictional_store) is not None
    app.do_run(fictional_store, now=T0 + timedelta(hours=2))
    assert {r["attrs"]["observer"] for r in proposal(fictional_store)["rows"]} == {K7, C5}
    assert blocked_note(fictional_store) is None  # the note goes once the proposal exists


def test_no_clearers_means_blocked(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=())
    assert (STEP_PROPOSE, CANDIDATE) in due_ids(fictional_store)
    assert "0 eligible observers" in blocked_note(fictional_store)["reasons"][0]


# --- the observer pool: clearer by level AND calibrated on the day (integration review finding 5) -------------------


def test_an_uncalibrated_clearer_is_not_in_the_observer_pool(fictional_store, example_roster):
    store(fictional_store, example_roster, calibrated=("k7m2q", "c5w1t"))  # r8n4h is a clearer who never calibrated
    assert {r["attrs"]["observer"] for r in proposal(fictional_store)["rows"]} == {K7, C5}
    st = app.load_state(fictional_store)
    assert observation.clearers(st) == [C5, K7, R8]  # by level alone
    assert observation.observer_pool(st, T0.date()) == [C5, K7]


def test_a_failed_calibration_does_not_make_a_clearer_an_observer(fictional_store, example_roster):
    store(fictional_store, example_roster, calibrated=("k7m2q", "c5w1t"))
    calibrate(fictional_store, R8, passed=False)
    assert observation.observer_pool(app.load_state(fictional_store), T0.date()) == [C5, K7]


def test_a_lapsed_calibration_is_not_current(fictional_store, example_roster):
    # a pass is good for rules.calibration.renewal_months (6): the one of 2026-03-01 ended on 2026-09-01
    store(fictional_store, example_roster, calibrated=())
    calibrate(fictional_store, K7, C5, at="2026-03-01T08:00:00+00:00")
    assert observation.observer_pool(app.load_state(fictional_store), T0.date()) == []
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert not (fictional_store / "generated" / "observations" / f"{CANDIDATE.split('/', 1)[1]}.json").exists()
    assert "0 eligible observers" in blocked_note(fictional_store)["reasons"][0]
    day = date(2026, 8, 31)  # but on a day inside that renewal period the same pass counts
    assert observation.observer_pool(app.load_state(fictional_store), day) == [C5, K7]


def test_the_pool_is_judged_on_the_day_of_the_proposal(fictional_store, example_roster):
    store(fictional_store, example_roster, run=False)  # calibrated on 2026-09-01: current until 2027-03-01
    app.do_run(fictional_store, now=datetime(2027, 3, 2, 8, 0, tzinfo=timezone.utc))
    slug = CANDIDATE.split("/", 1)[1]
    assert not (fictional_store / "generated" / "observations" / f"{slug}.json").exists()
    assert "0 eligible observers" in blocked_note(fictional_store)["reasons"][0]


def test_a_people_list_clearer_with_a_mapping_is_not_a_clearer_by_that_alone(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("c5w1t", "k7m2q"), run=False)
    path = fictional_store / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/obs-9", "name": "Ola Observer", "email": "ola.observer@example.com",
                          "roles": ["clearer"], "instructor": R8})  # R8 is shadow-level here: the role alone grants nothing
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    calibrate(fictional_store, R8)
    st = app.load_state(fictional_store)
    assert observation.clearers(st) == [C5, K7]
    assert observation.observer_pool(st, T0.date()) == [C5, K7]
    assert "clearer" not in {r for e in st.identities["ola.observer@example.com"] for r in e["roles"]}


# --- later rounds: a candidate who needs more observations (integration review finding 4) -----------------------

SLUG = CANDIDATE.split("/", 1)[1]


def settle_first_round(private, score=3):
    """Approve the first proposal, both observers score `score`, and the release runs (and the refresh after it)."""
    approve_batch(private)
    observed(private, score=score)
    app.do_run(private, now=T0 + timedelta(days=3))


def not_yet_event(candidate=CANDIDATE, outcome="not_yet", at="2026-10-29T09:00:00+00:00"):
    return events.make_event("clearance", candidate, workflow.SYSTEM_ACTOR, {
        "clearance": "tm:clearance/0123456789abcdef", "candidate": candidate, "instructor": INSTRUCTOR, "unit": UNIT,
        "modes": ["remote"], "outcome": outcome, "conditions": [], "recheck": None, "clearers": [K7, C5],
        "observations": [], "issued": "2026-10-29", "expires": "2027-10-29", "framework_version": "0.2.0"}, at=at)


def test_the_first_round_is_numbered_one_and_keeps_its_file(fictional_store, example_roster):
    store(fictional_store, example_roster)
    assert proposal(fictional_store)["delivery_ref"] == f"{SLUG}-1"
    (first,) = proposal_steps(fictional_store)
    assert first["payload"]["output"] == f"generated/observations/{SLUG}.json"


def test_evidence_that_falls_short_gets_a_new_round_once_the_old_one_has_settled(fictional_store, example_roster):
    store(fictional_store, example_roster)
    first = proposal(fictional_store)
    settle_first_round(fictional_store, score=1)  # every domain scored 1: the averages are below the minimum
    assert len(of_kind(fictional_store, "observation")) == 2
    rounds = proposal_steps(fictional_store)
    assert len(rounds) == 2
    second = proposal(fictional_store)
    assert second["delivery_ref"] == f"{SLUG}-2" and rounds[1]["payload"]["output"] == f"generated/observations/{SLUG}.2.json"
    assert {r["key"] for r in second["rows"]}.isdisjoint({r["key"] for r in first["rows"]})  # the URIs carry the round
    assert {r["attrs"]["delivery_ref"] for r in second["rows"]} == {f"{SLUG}-2"}
    assert all(r["key"] == observation.assignment_uri(CANDIDATE, r["attrs"]["observer"], f"{SLUG}-2") for r in second["rows"])
    assert (STEP_APPROVED, CANDIDATE) in due_ids(fictional_store, T0 + timedelta(days=3))  # new rows, new approval
    assert events.verify(fictional_store / app.EVENT_LOG) == []


def test_a_round_that_is_still_pending_is_not_proposed_again(fictional_store, example_roster):
    store(fictional_store, example_roster)
    settle_first_round(fictional_store, score=1)
    for day in (4, 5, 6):
        app.do_run(fictional_store, now=T0 + timedelta(days=day))
    assert len(proposal_steps(fictional_store)) == 2  # round 2 waits for its approval: no round 3 with the same pair
    pair = {r["attrs"]["observer"] for r in proposal(fictional_store)["rows"]}
    approve_batch(fictional_store, at="2026-10-30T09:00:00+00:00")  # approved: its assignments now await observation
    for day in (7, 8):
        app.do_run(fictional_store, now=T0 + timedelta(days=day))
    assert len(proposal_steps(fictional_store)) == 2
    assert {e["payload"]["attrs"]["observer"] for e in assignments(fictional_store)
            if e["payload"]["attrs"]["delivery_ref"] == f"{SLUG}-2"} == pair


def test_evidence_that_meets_the_minimum_gets_no_new_round(fictional_store, example_roster):
    store(fictional_store, example_roster)
    settle_first_round(fictional_store, score=3)
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert len(proposal_steps(fictional_store)) == 1


@pytest.mark.parametrize("how", ["not_yet", "recheck round"])
def test_a_not_yet_or_a_recheck_asks_for_more_observations_even_when_the_minimum_is_met(fictional_store, example_roster, how):
    store(fictional_store, example_roster)
    settle_first_round(fictional_store, score=3)
    assert len(proposal_steps(fictional_store)) == 1  # the evidence meets the minimum, so nothing is asked yet
    if how == "recheck round":
        # evidence-ready reads the latest round's evidence_sha256 (flows/clearance.py): carry the real round's hash over
        real = clearance.rounds(log(fictional_store), CANDIDATE)
        later = events.make_event("step", CANDIDATE, workflow.SYSTEM_ACTOR, {
            "step": "tm:step/evidence-ready", "round": "0123456789abcdef", "reason": "recheck", "after": None,
            "evidence_sha256": real[-1]["payload"]["evidence_sha256"] if real else "0" * 64},
            at="2026-10-29T09:00:00+00:00")
    else:  # a lapsed recheck supersedes the conditional clearance with a not_yet of the same id, so it is this event too
        later = not_yet_event()
    events.append(fictional_store / app.EVENT_LOG, later)
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert len(proposal_steps(fictional_store)) == 2 and proposal(fictional_store)["delivery_ref"] == f"{SLUG}-2"
    app.do_run(fictional_store, now=T0 + timedelta(days=5))
    assert len(proposal_steps(fictional_store)) == 2  # the one decision is answered once


def test_a_not_yet_that_arrives_while_a_round_is_pending_is_answered_once_it_settles(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    events.append(fictional_store / app.EVENT_LOG, not_yet_event())
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    assert len(proposal_steps(fictional_store)) == 1  # round 1 has not been observed yet
    observed(fictional_store, score=3)
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert len(proposal_steps(fictional_store)) == 2


def test_a_later_round_waits_when_the_pool_cannot_supply_it(fictional_store, example_roster):
    store(fictional_store, example_roster)
    settle_first_round(fictional_store, score=1)
    app.do_run(fictional_store, now=datetime(2027, 3, 2, 8, 0, tzinfo=timezone.utc))
    # on 2027-03-02 every calibration of 2026-09-01 has lapsed: round 2 was proposed on 2026-10-29, so nothing more asks
    assert len(proposal_steps(fictional_store)) == 2
    approve_batch(fictional_store, at="2026-10-30T09:00:00+00:00")
    for a in assignments(fictional_store):
        if a["payload"]["attrs"]["delivery_ref"] == f"{SLUG}-2":
            sign(fictional_store, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"],
                 observe_fields(1, day="2026-10-31"), at="2026-10-31T10:00:00+00:00")
    before = len(proposal_steps(fictional_store))
    app.do_run(fictional_store, now=datetime(2027, 3, 3, 8, 0, tzinfo=timezone.utc))
    assert len(proposal_steps(fictional_store)) == before == 2  # round 2 settled, evidence short, but no pool: waiting
    assert "0 eligible observers" in blocked_note(fictional_store)["reasons"][0]
    assert events.verify(fictional_store / app.EVENT_LOG) == []


# --- assignments-approved ---------------------------------------------------------------------------------------


def test_the_batch_page_shows_the_proposed_rows_to_each_coordinator(fictional_store, example_roster):
    store(fictional_store, example_roster)
    specs = app._page_specs(app.load_state(fictional_store), STEP_APPROVED, CANDIDATE)
    assert sorted(s["signer"] for s in specs) == ["tm:person/coord-1", "tm:person/coord-2"]
    assert {s["template"] for s in specs} == {"batch_approve"}
    inputs = specs[0]["inputs"]
    assert inputs["candidate"] == CANDIDATE
    assert [r["key"] for r in inputs["rows"]] == [r["key"] for r in proposal(fictional_store)["rows"]]
    assert specs[0]["inputs"] == specs[1]["inputs"]
    page, _ = pagegen.render(**specs[0], channel={"kind": "mail", "to": "signoffs@example.com"})
    assert all(r["key"] in page for r in inputs["rows"])


def test_approval_opens_one_assignment_per_row_with_the_fixed_shape(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    found = assignments(fictional_store)
    rows = proposal(fictional_store)["rows"]
    assert [e["subject_uri"] for e in found] == sorted(r["key"] for r in rows)
    for e in found:
        assert e["actor"] == COORD
        assert e["payload"]["subject_kind"] == "assignment" and e["payload"]["opened_by"] == STEP_APPROVED
        assert events.check_event(e) == []
        assert e["id"] == flows.pathway.subject_event_id(e["subject_uri"])
        want = next(r["attrs"] for r in rows if r["key"] == e["subject_uri"])
        assert e["payload"]["attrs"] == want
    assert (STEP_APPROVED, CANDIDATE) not in due_ids(fictional_store)


def test_replaying_an_approval_opens_nothing_twice(fictional_store, example_roster):
    store(fictional_store, example_roster)
    event = approve_batch(fictional_store)
    n = len(assignments(fictional_store))
    st = app.load_state(fictional_store)
    document = json.loads((fictional_store / "signoffs" / f"{event['payload']['signoff_id']}.json").read_text("utf-8"))
    again, _ = observation._open_assignments(st, event, document, T0)
    assert sorted(e["id"] for e in again) == sorted(e["id"] for e in assignments(fictional_store))
    app.append_new(fictional_store, again)
    assert len(assignments(fictional_store)) == n


def test_the_hook_opens_every_row_of_the_proposal_the_approval_was_accepted_against(fictional_store, example_roster):
    # Ingest accepts a batch approval only when every row of the page is decided and approved (signoff.content_reasons;
    # tests/test_observation_ingest.py rejects a partial one), so the hook has no row to skip: a "not approved" branch in
    # it could never run (integration review finding 13).
    store(fictional_store, example_roster)
    keys = [r["key"] for r in proposal(fictional_store)["rows"]]
    sign(fictional_store, STEP_APPROVED, CANDIDATE, COORD, {"rows": {k: "approve" for k in keys}})
    assert [e["subject_uri"] for e in assignments(fictional_store)] == sorted(keys)


def test_a_row_whose_observer_is_the_instructor_never_opens(fictional_store, example_roster):
    store(fictional_store, example_roster)
    path = fictional_store / "generated" / "observations" / "p3x9d--example-agent-loop-1--remote.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"][0]["attrs"]["observer"] = INSTRUCTOR
    doc["rows"][0]["key"] = observation.assignment_uri(CANDIDATE, INSTRUCTOR, doc["rows"][0]["attrs"]["delivery_ref"])
    path.write_text(json.dumps(doc), encoding="utf-8")
    sign(fictional_store, STEP_APPROVED, CANDIDATE, COORD, {"rows": {r["key"]: "approve" for r in doc["rows"]}})
    assert INSTRUCTOR not in {e["payload"]["attrs"]["observer"] for e in assignments(fictional_store)}
    assert len(assignments(fictional_store)) == len(doc["rows"]) - 1


def test_changing_the_proposal_reopens_the_approval(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    assert (STEP_APPROVED, CANDIDATE) not in due_ids(fictional_store)
    path = fictional_store / "generated" / "observations" / "p3x9d--example-agent-loop-1--remote.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"][0]["summary"] += " (changed)"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert (STEP_APPROVED, CANDIDATE) in due_ids(fictional_store)


def test_the_engine_sees_assignments_only_once_the_candidate_is_approved(fictional_store, example_roster):
    store(fictional_store, example_roster)
    lone = "tm:assignment/00000000000000aa"
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "subject", lone, workflow.SYSTEM_ACTOR,
        {"subject_kind": "assignment", "opened_by": "tm:step/test",
         "attrs": {"candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote", "observer": K7,
                   "length": "full", "lead": True, "delivery_ref": "d-lone"}},
        at="2026-10-26T08:30:00+00:00"))
    assert app.load_state(fictional_store).subjects[lone]["kind"] == "assignment"
    assert (STEP_OBSERVE, lone) not in due_ids(fictional_store) and (STEP_SELF, lone) not in due_ids(fictional_store)
    approve_batch(fictional_store)
    now = due_ids(fictional_store)
    assert (STEP_OBSERVE, lone) in now and (STEP_SELF, lone) in now
    for e in assignments(fictional_store):
        assert (STEP_OBSERVE, e["subject_uri"]) in now and (STEP_SELF, e["subject_uri"]) in now
        assert (STEP_RELEASE, e["subject_uri"]) not in now  # not before an observe sign-off


# --- the pages --------------------------------------------------------------------------------------------------


def test_the_observe_page_is_for_the_assigned_observer_only_and_scores_every_domain(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    st = app.load_state(fictional_store)
    for e in assignments(fictional_store):
        (spec,) = app._page_specs(st, STEP_OBSERVE, e["subject_uri"])
        attrs = e["payload"]["attrs"]
        assert spec["signer"] == attrs["observer"] and spec["role"] == "clearer" and spec["template"] == "approve"
        fields = {f["name"]: f for f in spec["fields"]}
        assert [n for n, f in fields.items() if f["kind"] == "evidence_score"] == DOMAINS
        assert all(fields[d]["required"] for d in DOMAINS)
        assert fields["date"]["kind"] == "date" and fields["date"]["required"]
        assert (fields["length"]["kind"], fields["length"]["value"]) == ("enum", "full")
        assert (fields["lead"]["kind"], fields["lead"]["value"]) == ("bool", True)
        assert (fields["mode"]["kind"], fields["mode"]["value"]) == ("enum", "remote")
        assert spec["inputs"]["assignment"] == e["subject_uri"]
        page, _ = pagegen.render(**spec, channel={"kind": "mail", "to": "signoffs@example.com"})
        assert "Recording timestamp" in page


def test_the_observe_page_shows_nothing_of_the_other_observer(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, b = assignments(fictional_store)
    (spec,) = app._page_specs(app.load_state(fictional_store), STEP_OBSERVE, a["subject_uri"])
    flat = json.dumps(spec["inputs"])
    assert b["payload"]["attrs"]["observer"] not in flat and b["subject_uri"] not in flat
    sign(fictional_store, STEP_OBSERVE, b["subject_uri"], b["payload"]["attrs"]["observer"], observe_fields())
    (after,) = app._page_specs(app.load_state(fictional_store), STEP_OBSERVE, a["subject_uri"])
    assert after["inputs"] == spec["inputs"]  # the other's submission changes nothing a page shows


def test_the_self_assessment_page_is_for_the_instructor(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    st = app.load_state(fictional_store)
    for e in assignments(fictional_store):
        (spec,) = app._page_specs(st, STEP_SELF, e["subject_uri"])
        assert spec["signer"] == INSTRUCTOR and spec["role"] == "instructor" and spec["template"] == "self_assessment"
        assert [f["name"] for f in spec["fields"] if f["kind"] == "score"] == DOMAINS
        pagegen.render(**spec, channel={"kind": "mail", "to": "signoffs@example.com"})


def test_an_observer_who_is_the_instructor_gets_no_page(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    st = app.load_state(fictional_store)
    uri = assignments(fictional_store)[0]["subject_uri"]
    st.subjects[uri]["observer"] = INSTRUCTOR
    with pytest.raises(flows.common.PageProblem, match="observer"):
        observation._b_observe(st, uri)


# --- observing, blindness and release ---------------------------------------------------------------------------


def test_an_observe_signoff_stores_the_notes_privately_and_records_no_observation(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, _ = assignments(fictional_store)
    sign(fictional_store, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"], observe_fields())
    key = observation.evidence_key(a["subject_uri"])
    stored = json.loads((fictional_store / key).read_text(encoding="utf-8"))
    assert stored["scores"] == {d: 3 for d in DOMAINS} and stored["notes"][DOMAINS[0]]["note"].startswith("ZETA-NOTE")
    assert stored["observer"] == a["payload"]["attrs"]["observer"]
    assert of_kind(fictional_store, "observation") == []
    assert NOTE.split()[0] not in (fictional_store / app.EVENT_LOG).read_text(encoding="utf-8")


def test_blind_until_the_second_observer_has_submitted(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, b = assignments(fictional_store)
    sign(fictional_store, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"], observe_fields())
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert of_kind(fictional_store, "observation") == []
    assert not [e for e in of_kind(fictional_store, "step") if e["payload"].get("step") == STEP_RELEASE]
    assert (STEP_RELEASE, a["subject_uri"]) in due_ids(fictional_store, T0 + timedelta(days=4))  # waiting, not done
    sign(fictional_store, STEP_OBSERVE, b["subject_uri"], b["payload"]["attrs"]["observer"], observe_fields(2),
         at="2026-10-29T09:00:00+00:00")
    app.do_run(fictional_store, now=T0 + timedelta(days=5))
    assert len(of_kind(fictional_store, "observation")) == 2


def test_release_writes_one_valid_observation_event_per_assignment(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, b = assignments(fictional_store)
    sign(fictional_store, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"],
         observe_fields(4, day="2026-10-28"), at="2026-10-28T17:00:00+00:00")
    sign(fictional_store, STEP_OBSERVE, b["subject_uri"], b["payload"]["attrs"]["observer"],
         observe_fields(2, day="2026-10-27", length="short", lead=False, mode="hybrid"), at="2026-10-29T09:00:00+00:00")
    app.do_run(fictional_store, now=T0 + timedelta(days=5))
    found = {e["payload"]["assignment"]: e for e in of_kind(fictional_store, "observation")}
    assert set(found) == {a["subject_uri"], b["subject_uri"]}
    ea, eb = found[a["subject_uri"]], found[b["subject_uri"]]
    for e, src in ((ea, a), (eb, b)):
        attrs = src["payload"]["attrs"]
        assert events.check_event(e) == []
        assert e["subject_uri"] == INSTRUCTOR and e["actor"] == attrs["observer"]
        p = e["payload"]
        assert (p["instructor"], p["unit"], p["observer"], p["delivery_ref"]) == (
            INSTRUCTOR, UNIT, attrs["observer"], attrs["delivery_ref"])
        assert p["rubric_version"] == load_standards()["rubric"]["framework_version"]
        assert p["evidence_ref"] == observation.evidence_key(src["subject_uri"])
        assert (fictional_store / p["evidence_ref"]).is_file()
        assert "note" not in json.dumps(p)
    assert ea["payload"]["scores"] == {d: 4 for d in DOMAINS} and eb["payload"]["scores"] == {d: 2 for d in DOMAINS}
    assert (ea["payload"]["length"], ea["payload"]["lead"], ea["payload"]["mode"]) == ("full", True, "remote")
    assert (eb["payload"]["length"], eb["payload"]["lead"], eb["payload"]["mode"]) == ("short", False, "hybrid")
    assert ea["at"].startswith("2026-10-28") and eb["at"].startswith("2026-10-27")  # the observation date
    assert ea["payload"]["recorded_at"] == "2026-10-28T17:00:00+00:00"
    assert NOTE.split()[0] not in (fictional_store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert (STEP_RELEASE, a["subject_uri"]) not in due_ids(fictional_store, T0 + timedelta(days=5))


def test_release_is_idempotent(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    observed(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    before = log(fictional_store)
    assert len(of_kind(fictional_store, "observation")) == 2
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    # The released observations are now calibrated evidence, so the clearance workflow's evidence-ready rewrites its blocked
    # check once with the shorter list of reasons, and W9 seeds the instructor's CPD plan from the new observations; those
    # are the only things the run after the release may add.
    added = [e for e in log(fictional_store) if e["id"] not in {b["id"] for b in before}]
    assert all(e["payload"].get("step") in ("tm:step/evidence-ready", "tm:step/cpd-plan") for e in added)
    assert {e["kind"] for e in added} == {"check", "step"} and len([e for e in added if e["kind"] == "step"]) == 1
    before = log(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert log(fictional_store) == before
    st = app.load_state(fictional_store)
    known = {e["id"] for e in before}
    for uri in (e["subject_uri"] for e in assignments(fictional_store)):  # called directly, it can only repeat itself
        assert {e["id"] for e in observation.release(st, uri, T0 + timedelta(days=9))} <= known


def test_assignments_of_other_deliveries_release_independently(fictional_store, example_roster):
    store(fictional_store, example_roster)
    other = "tm:candidate/p3x9d--example-agent-loop-1--hybrid"
    approve_batch(fictional_store)
    approve_batch(fictional_store, other)
    observed(fictional_store, candidate=CANDIDATE)
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    released = {e["payload"]["assignment"] for e in of_kind(fictional_store, "observation")}
    assert released == {e["subject_uri"] for e in assignments(fictional_store)}
    assert not released & {e["subject_uri"] for e in assignments(fictional_store, other)}


def test_a_signoff_with_scores_out_of_range_is_blocked_not_released(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, b = assignments(fictional_store)
    bad = observe_fields()
    bad[DOMAINS[0]] = {"score": 5, "note": "off the scale"}
    sign(fictional_store, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"], bad)
    sign(fictional_store, STEP_OBSERVE, b["subject_uri"], b["payload"]["attrs"]["observer"], observe_fields(),
         at="2026-10-29T09:00:00+00:00")
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    released = {e["payload"]["assignment"] for e in of_kind(fictional_store, "observation")}
    assert released == {b["subject_uri"]}  # the other observer's valid submission is released; the bad one is not
    (blocked,) = [e for e in of_kind(fictional_store, "check") if e["subject_uri"] == a["subject_uri"]]
    assert blocked["payload"]["result"] == "blocked" and blocked["payload"]["step"] == STEP_RELEASE
    assert any(DOMAINS[0] in r for r in blocked["payload"]["reasons"])


def test_a_signoff_by_someone_else_than_the_observer_is_not_released(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, b = assignments(fictional_store)
    sign(fictional_store, STEP_OBSERVE, a["subject_uri"], "tm:person/coord-1", observe_fields())
    sign(fictional_store, STEP_OBSERVE, b["subject_uri"], b["payload"]["attrs"]["observer"], observe_fields(),
         at="2026-10-29T09:00:00+00:00")
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    assert {e["payload"]["assignment"] for e in of_kind(fictional_store, "observation")} == {b["subject_uri"]}


def test_a_changes_decision_does_not_complete_observe(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, _ = assignments(fictional_store)
    sign(fictional_store, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"], observe_fields(),
         decision="changes")
    assert (STEP_OBSERVE, a["subject_uri"]) in due_ids(fictional_store)
    assert not (fictional_store / observation.evidence_key(a["subject_uri"])).exists()


def session_document(a, day, signed_at):
    return {"id": "e" * 16, "signer": a["payload"]["attrs"]["observer"], "subject_uri": a["subject_uri"],
            "signed_at": signed_at, "fields": observe_fields(day=day)}


def test_a_session_before_the_assignment_opened_is_not_usable_evidence(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store, at="2026-10-27T09:00:00+00:00")  # the assignments opened on the 27th
    a, _ = assignments(fictional_store)
    st = app.load_state(fictional_store)
    info = st.subjects[a["subject_uri"]]
    data, reasons = observation.evidence(session_document(a, "2026-10-26", "2026-10-28T09:00:00+00:00"), info, st)
    assert data is None and reasons == ["date: the session is before the assignment was opened"]
    assert observation.evidence(session_document(a, "2026-10-27", "2026-10-28T09:00:00+00:00"), info, st)[0] is not None
    # and, as before, not after the sign-off
    data, reasons = observation.evidence(session_document(a, "2026-10-29", "2026-10-28T09:00:00+00:00"), info, st)
    assert data is None and reasons == ["date: the session is after the sign-off"]


def test_a_session_cannot_be_backdated_into_a_lapsed_calibration(fictional_store, example_roster):
    # The reviewer's scenario: the observers' calibration (2026-09-01, six months) ends on 2027-03-01. An assignment opened
    # on 2027-03-05 would give no counting observation (rules.clearance_check wants a calibrated observer on the session
    # day), unless the observer dates the session before the calibration lapsed.
    store(fictional_store, example_roster)
    approve_batch(fictional_store, at="2027-03-05T09:00:00+00:00")
    a, _ = assignments(fictional_store)
    observer = a["payload"]["attrs"]["observer"]
    cals = records.calibrations(log(fictional_store))
    std = load_standards()["rules"]
    assert rules.is_calibrated(observer, date(2027, 2, 20), cals, std)  # the backdated day would have counted
    assert not rules.is_calibrated(observer, date(2027, 3, 5), cals, std)  # the real one does not
    st = app.load_state(fictional_store)
    data, reasons = observation.evidence(session_document(a, "2027-02-20", "2027-03-06T09:00:00+00:00"),
                                         st.subjects[a["subject_uri"]], st)
    assert data is None and reasons == ["date: the session is before the assignment was opened"]


def test_the_log_still_verifies(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    observed(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    assert events.verify(fictional_store / app.EVENT_LOG) == []


# --- the due rule -----------------------------------------------------------------------------------------------


def test_observation_window_is_fourteen_days_from_the_assignment(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store, at="2026-10-27T09:00:00+00:00")
    uri = assignments(fictional_store)[0]["subject_uri"]
    assert observation.OBSERVATION_WINDOW_DAYS == 14
    got = {d.step: d for d in app.due_steps(app.load_state(fictional_store), date(2026, 10, 30)) if d.subject == uri}
    opened = date.fromisoformat(assignments(fictional_store)[0]["at"][:10])
    assert got[STEP_OBSERVE].due == got[STEP_SELF].due == opened + timedelta(days=14)
    late = {d.step: d for d in app.due_steps(app.load_state(fictional_store), opened + timedelta(days=15))
            if d.subject == uri}
    assert late[STEP_OBSERVE].overdue and late[STEP_SELF].overdue


def test_the_rule_has_no_date_for_an_unknown_subject():
    fn = due.resolve("observation_window")
    assert fn({}, "tm:assignment/00000000000000bb", {"kind": "assignment"}, [], date(2026, 10, 30)) is None


# --- records.observations ---------------------------------------------------------------------------------------


def test_records_observations_round_trip(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    a, b = assignments(fictional_store)
    sign(fictional_store, STEP_OBSERVE, a["subject_uri"], a["payload"]["attrs"]["observer"],
         observe_fields(4, day="2026-10-28"), at="2026-10-28T17:00:00+00:00")
    sign(fictional_store, STEP_OBSERVE, b["subject_uri"], b["payload"]["attrs"]["observer"],
         observe_fields(2, day="2026-10-27", length="short", lead=False, mode="hybrid"), at="2026-10-29T09:00:00+00:00")
    app.do_run(fictional_store, now=T0 + timedelta(days=5))
    got = records.observations(log(fictional_store))
    assert [o.at for o in got] == [date(2026, 10, 27), date(2026, 10, 28)]  # oldest first
    by_obs = {o.observer: o for o in got}
    ob_a, ob_b = by_obs[a["payload"]["attrs"]["observer"]], by_obs[b["payload"]["attrs"]["observer"]]
    ev = {e["payload"]["observer"]: e for e in of_kind(fictional_store, "observation")}
    assert ob_a == rules.Observation(
        id=ev[ob_a.observer]["id"], instructor=INSTRUCTOR, unit=UNIT, observer=ob_a.observer, at=date(2026, 10, 28),
        length="full", lead=True, scores={d: 4 for d in DOMAINS}, mode="remote", rubric_version="1.1.0")
    assert ob_b == rules.Observation(
        id=ev[ob_b.observer]["id"], instructor=INSTRUCTOR, unit=UNIT, observer=ob_b.observer, at=date(2026, 10, 27),
        length="short", lead=False, scores={d: 2 for d in DOMAINS}, mode="hybrid", rubric_version="1.1.0")


def test_records_observations_ignores_other_kinds_and_handles_an_empty_log(fictional_store, example_roster):
    assert records.observations([]) == []
    store(fictional_store, example_roster)
    assert records.observations(log(fictional_store)) == []


def test_observations_from_the_flow_feed_the_clearance_rule(fictional_store, example_roster):
    std = load_standards()
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    observed(fictional_store, score=3)
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    got = records.observations(log(fictional_store))
    observers = {o.observer for o in got}
    calibrated = {o: [date(2026, 9, 1)] for o in observers}
    dry = [rules.DryRun(INSTRUCTOR, UNIT, "remote", True, date(2026, 10, 20))]
    ok = rules.clearance_check(INSTRUCTOR, UNIT, "remote", got, dry, calibrated, set(), DOMAINS, std["rules"])
    assert ok.ok, ok.reasons
    one = rules.clearance_check(INSTRUCTOR, UNIT, "remote", got[:1], dry, calibrated, set(), DOMAINS, std["rules"])
    assert not one.ok
    co = rules.clearance_check(INSTRUCTOR, UNIT, "remote", got, dry, calibrated, observers, DOMAINS, std["rules"])
    assert not co.ok  # both observers coaches: one distinct observer counts


def test_after_a_return_to_co_teaching_a_settled_round_does_not_hide_the_missing_evidence(fictional_store, example_roster):
    """Decision 0015, finding 4: only observations dated after a blocking bench decision count, so a candidate whose old round
    settled (and met the minimum) is short again once the decision is on record, and gets a new automatic proposal."""
    store(fictional_store, example_roster)
    settle_first_round(fictional_store, score=3)  # observed 2026-10-28; meets the minimum
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert len(proposal_steps(fictional_store)) == 1
    slug = INSTRUCTOR.split("/", 1)[1]
    bench = f"tm:bench/{slug}--1"
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "subject", bench, workflow.SYSTEM_ACTOR,
        {"subject_kind": "bench", "attrs": {"instructor": INSTRUCTOR, "reason": "requested"}, "opened_by": "tm:cli/request-bench"},
        id="obs-bench-open", at="2026-10-21T09:00:00+00:00"))
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "bench_decision", bench, "tm:person/hot-1",
        {"bench": bench, "instructor": INSTRUCTOR, "decision": "return-to-co-teaching", "rationale_key": f"bench/{slug}-1.json",
         "evidence_pack_sha256": "ab" * 32, "decided_by": "tm:person/hot-1", "signoff_id": "cd" * 8},
        id="obs-bench-decision", at="2026-10-29T09:00:00+00:00"))
    app.do_run(fictional_store, now=T0 + timedelta(days=5))
    assert len(proposal_steps(fictional_store)) == 2 and proposal(fictional_store)["delivery_ref"] == f"{SLUG}-2"


def test_no_observation_page_while_the_observer_is_not_a_clearer(fictional_store, example_roster):
    """Found by the simulation (2026-10-27): an observer whose calibration lapsed (and so their level, back to cleared) kept
    an observation page that every sign-off was refused on until they were a clearer again. The page now waits for them."""
    from clearer_helpers import set_level as level_to

    from teachermodel.flows.common import PageProblem

    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    app.do_run(fictional_store, now=T0)
    first = assignments(fictional_store)[0]
    observer = first["payload"]["attrs"]["observer"]
    assert app._page_specs(app.load_state(fictional_store), STEP_OBSERVE, first["subject_uri"])
    level_to(fictional_store, observer, "cleared", at="2026-10-26T08:00:00+00:00")
    with pytest.raises(PageProblem, match="not a clearer"):
        app._page_specs(app.load_state(fictional_store), STEP_OBSERVE, first["subject_uri"])
    level_to(fictional_store, observer, "clearer", at="2026-10-26T09:00:00+00:00")
    assert app._page_specs(app.load_state(fictional_store), STEP_OBSERVE, first["subject_uri"])
