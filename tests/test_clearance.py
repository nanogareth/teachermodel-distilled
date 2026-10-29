"""W4 clearance (standards/workflows/clearance.yaml, flows/clearance.py) and the level moves to cleared and clearer
(standards/workflows/levels.yaml, flows/levels.py: tests/test_levels.py, which reuses the helpers here).

evidence-ready (auto: rules.clearance_check over the records) -> clearer-decision-1 -> clearer-decision-2 (two different
calibrated clearers, neither the instructor, at most one a coach) -> head-resolves (only on disagreement) -> issue (the
`clearance` event) -> recheck-lapse (a missed recheck lapses to not_yet). The evidence is written as events directly; the
decisions go through the page builders, the content checks ingest runs and the sign-off hooks (`decide`), and one test
takes the real mail round trip. Fictional people only.
"""

import json
import shutil
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from conftest import EXAMPLE_ROSTER_PATH, make_fictional_store
from ingest_helpers import ingest, page_data, signoff
from privacy_helpers import import_roster_ungated
from test_observation import set_level

from teachermodel import app, bridge, due, events, flows, records, rules, signoff as tm_signoff, staffing, units, workflow
from teachermodel import pages as pagegen
from teachermodel.flows import clearance
from teachermodel.flows.common import PageProblem
from teachermodel.standards import ROOT, check_standards, load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
UNIT = "sl:unit/example-agent-loop@1"
K7, P3, C5, R8 = (f"tm:instructor/{s}" for s in ("k7m2q", "p3x9d", "c5w1t", "r8n4h"))
INSTRUCTOR = K7  # the SME engineer, moved to lead-observed; delivers the example unit in-person and hybrid
CAND = "tm:candidate/k7m2q--example-agent-loop-1--in-person"
EVIDENCE, D1, D2, HEAD, ISSUE, LAPSE = (f"tm:step/{s}" for s in (
    "evidence-ready", "clearer-decision-1", "clearer-decision-2", "head-resolves", "issue", "recheck-lapse"))
HOT = "tm:person/hot-1"
STD = load_standards()
DOMAINS = [d["id"] for d in STD["framework"]["domains"]]
RUBRIC = STD["rubric"]["framework_version"]


# --- evidence written straight into the log ---------------------------------------------------------------------


def log(private):
    return app.read_events(private)


def of_kind(private, kind, subject=None):
    return [e for e in log(private) if e["kind"] == kind and (subject is None or e["subject_uri"] == subject)]


def put(private, event):
    events.append(private / app.EVENT_LOG, event)
    return event


def calibrate(private, who, on="2026-10-01", passed=True):
    hexid = tm_signoff.input_sha256([who, on])[:16]
    return put(private, events.make_event(
        "calibration", who, workflow.SYSTEM_ACTOR,
        {"exercise": f"tm:exercise/{hexid}", "observer": who, "unit": UNIT, "rubric_version": RUBRIC,
         "within_one_share": 1.0, "exact_share": 1.0, "passed": passed, "signoff_id": hexid},
        at=f"{on}T09:00:00+00:00"))


def observe(private, observer, score=3, *, day="2026-10-20", length="full", lead=True, mode="in-person", rubric=RUBRIC,
            **domain):
    scores = {d: score for d in DOMAINS}
    scores.update(domain)
    n = len(of_kind(private, "observation"))
    return put(private, events.make_event(
        "observation", INSTRUCTOR, observer,
        {"instructor": INSTRUCTOR, "unit": UNIT, "observer": observer, "length": length, "lead": lead, "mode": mode,
         "rubric_version": rubric, "scores": scores},
        id=tm_signoff.input_sha256(["obs", observer, day, n])[:32], at=f"{day}T10:00:00+00:00"))


def dry_run(private, mode="in-person", day="2026-10-21", env=None):
    unit = units.load(UNIT)
    sid = tm_signoff.input_sha256(["dry", mode, day])[:16]
    return put(private, events.make_event(
        "dry_run", workflow.candidate_uri(INSTRUCTOR, UNIT, mode), "tm:person/clearer-1",
        {"candidate": workflow.candidate_uri(INSTRUCTOR, UNIT, mode), "instructor": INSTRUCTOR, "unit": UNIT,
         "mode": mode, "passed": True, "checks": {"clock": "pass"}, "failure_injected": unit["failure_catalogue"][0]["id"],
         "fallback_exercised": True, "environment_sha256": env or units.environment_sha256(unit), "signoff_id": sid},
        at=f"{day}T10:00:00+00:00"))


def hold(private, who, *, unit=UNIT, issued="2026-09-01", expires="2027-09-01", framework="0.2.0", outcome="cleared"):
    """A clearance the clearer `who` holds for `unit` (in person): a clearer decides only within their modules. The same
    `who` and `unit` give the same clearance URI, so a later call supersedes an earlier one."""
    slug = who.split("/", 1)[1]
    cand = workflow.candidate_uri(who, unit, "in-person")
    return put(private, events.make_event(
        "clearance", cand, workflow.SYSTEM_ACTOR,
        {"clearance": f"tm:clearance/{tm_signoff.input_sha256(['held', who, unit])[:16]}", "candidate": cand,
         "instructor": who, "unit": unit, "modes": ["in-person"], "outcome": outcome, "conditions": [], "recheck": None,
         "clearers": ["tm:person/seed-a", "tm:person/seed-b"], "observations": [f"seed-obs-{slug}"], "issued": issued,
         "expires": expires, "framework_version": framework},
        at=f"{issued}T09:00:00+00:00"))


def add_coaches(private, *slugs, of=(INSTRUCTOR,)):
    """A coach is a person with the coach role, mapped to the instructor of that slug (people.yaml `instructor`) and listing
    the instructors they coach (`coaches`, decision 0014): by default the instructor of these tests."""
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for s in slugs:
        doc["people"].append({"person": f"tm:person/{s}", "name": f"Coach {s}", "email": f"coach.{s}@example.com",
                              "roles": ["coach"], "instructor": f"tm:instructor/{s}", "coaches": list(of)})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def store(private, roster, *, clearers=(P3, C5, R8), calibrated=(P3, C5), coaches=(), coaches_of=(INSTRUCTOR,), held=None):
    """`held`: the clearers who hold a clearance for the unit (default: every clearer but the instructor)."""
    import_roster_ungated(private, roster, T0)
    set_level(private, INSTRUCTOR, "lead-observed")
    for c in clearers:
        set_level(private, c, "clearer")
    add_coaches(private, *(c.split("/", 1)[1] for c in coaches), of=coaches_of)
    for c in calibrated:
        calibrate(private, c)
    for c in (held if held is not None else [c for c in clearers if c != INSTRUCTOR]):
        hold(private, c)
    return private


def build_ready(base, **kw):
    """Two calibrated clearers observed the SME's lead delivery and a dry run passed: evidence-ready has a round."""
    private = make_fictional_store(base)
    roster = base / "roster-in.yaml"
    shutil.copy(EXAMPLE_ROSTER_PATH, roster)
    store(private, roster, **kw)
    observe(private, P3)
    observe(private, C5)
    dry_run(private)
    app.do_run(private, now=T0)


@pytest.fixture
def ready(fictional_store, cached_world):
    """`ready(**store_kw)`: build_ready, built once per session for each set of arguments and copied into this test's
    tmp_path; returns the store."""

    def make(**kw):
        cached_world("clearance_ready " + json.dumps(kw, sort_keys=True), lambda base: build_ready(base, **kw))
        return fictional_store

    return make


def rounds(private):
    return [e for e in of_kind(private, "step", CAND) if e["payload"].get("step") == EVIDENCE]


def blocked(private):
    return [e["payload"]["reasons"] for e in of_kind(private, "check", CAND) if e["payload"].get("step") == EVIDENCE]


def due_ids(private, now=T0):
    return {(d.step, d.subject) for d in app.due_steps(app.load_state(private), now.date())}


def due_of(private, step, now=T0):
    return [d for d in app.due_steps(app.load_state(private), now.date()) if d.step == step and d.subject == CAND]


# --- decisions: the page builder, the content checks ingest runs, and the hooks --------------------------------


AT = "2026-10-27T09:00:00+00:00"


def cleared():
    return {"outcome": "cleared"}


def conditional(recheck="2026-12-01", conditions="Run the pre-check in the first ten minutes"):
    return {"outcome": "cleared_with_conditions", "conditions": conditions, "recheck": recheck}


def not_yet(actions="Two more full lead observations after coaching on questioning"):
    return {"outcome": "not_yet", "actions": actions}


def document(private, step, signer, fields, *, at=AT, subject=CAND):
    st = app.load_state(private)
    specs = app._page_specs(st, step, subject)
    sid = tm_signoff.input_sha256([step, subject, signer, at, fields])[:16]
    return {"schema": "tm:contract/signoff@1", "id": sid, "step": step, "subject_uri": subject,
            "input_sha256": tm_signoff.input_sha256(specs[0]["inputs"]), "decision": "approve", "fields": fields,
            "signer": signer, "signed_at": at, "page_template_sha256": pagegen.template_sha256(specs[0]["template"])}


def signers(private, step, subject=CAND):
    return sorted(s["signer"] for s in app._page_specs(app.load_state(private), step, subject))


def reasons(private, step, signer, fields, **kw):
    doc = document(private, step, signer, fields, **kw)
    return flows.content_reasons(app.load_state(private), doc)


def decide(private, step, signer, fields, *, at=AT, subject=CAND):
    """Sign as ingest would once the bridge accepted the envelope: the content checks must pass, then the event, the
    stored document and the hooks."""
    st = app.load_state(private)
    doc = document(private, step, signer, fields, at=at, subject=subject)
    found = flows.content_reasons(st, doc)
    assert found == [], found
    event = tm_signoff.to_event(doc, "sender@example.com")
    applied = bridge.Applied(events=[event], private=[(f"signoffs/{doc['id']}.json", doc)])
    hook_events, hook_docs = app._signoff_hooks(st, applied, datetime.fromisoformat(at))
    app._store_documents(private, applied.private)
    app._store_documents(private, hook_docs, under="")
    app.append_new(private, [event, *hook_events])
    return event


def issued(private):
    return of_kind(private, "clearance", CAND)


def check_staffing(private, on="2026-11-02", mode="in-person"):
    return staffing.check(log(private), {"instructor": INSTRUCTOR, "unit": UNIT, "mode": mode, "date": on}, STD["rules"])


# --- the workflow files ----------------------------------------------------------------------------------------


def steps_of(wf_id):
    wf = {w["id"]: w for w in STD["workflows"]["workflows"]}[wf_id]
    return {s["id"]: s for s in wf["steps"]}


def test_the_clearance_workflow_defines_its_steps():
    steps = steps_of("tm:workflow/clearance")
    shape = {sid: (s["type"], s["role"], s["subject"], tuple(s["needs"])) for sid, s in steps.items()}
    assert shape == {
        EVIDENCE: ("auto", "head-of-training", "candidate", ()),
        D1: ("human", "clearer", "candidate", (EVIDENCE,)),
        D2: ("human", "clearer", "candidate", (D1,)),
        HEAD: ("human", "head-of-training", "candidate", (D2,)),
        ISSUE: ("auto", "head-of-training", "candidate", (HEAD,)),
        LAPSE: ("auto", "head-of-training", "candidate", (ISSUE,)),
    }
    for sid in (D1, D2, HEAD):
        assert steps[sid]["done_when"]["bind"] == "input" and steps[sid]["page"] == "approve"
    assert steps[HEAD]["done_when"].get("skippable") is True
    assert steps[D1]["due"] == steps[D2]["due"] == "clearance_expiry" and steps[LAPSE]["due"] == "conditional_recheck"
    assert {"clearance_expiry", "conditional_recheck"} <= due.names()


def test_standards_validate_with_the_new_workflows():
    assert check_standards(ROOT) == []


def test_every_step_has_its_runner_or_builder():
    for sid in (EVIDENCE, ISSUE, LAPSE):
        assert flows.AUTO_STEPS[sid].per == "candidate" and flows.AUTO_STEPS[sid].refresh
    assert {D1, D2, HEAD} <= set(flows.PAGE_SPECS) and {D1, D2, HEAD} <= set(flows.CONTENT_CHECKS)


# --- evidence-ready ----------------------------------------------------------------------------------------------


def test_evidence_ready_blocks_with_the_rules_reasons_until_the_evidence_meets_the_minimum(fictional_store, example_roster):
    store(fictional_store, example_roster)
    observe(fictional_store, P3)
    app.do_run(fictional_store, now=T0)
    assert rounds(fictional_store) == []
    (why,) = blocked(fictional_store)
    assert any("calibrated observations; need 2" in r for r in why) and any("dry-run" in r for r in why)
    assert (EVIDENCE, CAND) in due_ids(fictional_store) and (D1, CAND) not in due_ids(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert len(blocked(fictional_store)) == 1  # the same reasons are not written twice

    observe(fictional_store, C5)
    dry_run(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(hours=2))
    (rnd,) = rounds(fictional_store)
    p = rnd["payload"]
    assert p["observers"] == sorted([P3, C5]) and len(p["observations"]) == 2 and p["after"] is None
    assert p["averages"] == {d: 3 for d in DOMAINS} and len(p["evidence_sha256"]) == 64
    assert (EVIDENCE, CAND) not in due_ids(fictional_store) and (D1, CAND) in due_ids(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(hours=3))
    assert len(rounds(fictional_store)) == 1  # refreshed, unchanged: nothing appended


@pytest.mark.parametrize("first,second,ok,why", [
    # a domain averaging exactly the minimum (2) passes; below it, not (the other domains keep the overall mean up)
    ({"score": 4, "prior-knowledge": 1}, {"score": 4, "prior-knowledge": 3}, True, None),
    ({"score": 4, "prior-knowledge": 1}, {"score": 4, "prior-knowledge": 2}, False, "domain prior-knowledge averages 1.50"),
    # an overall mean of exactly 3 passes; below it, not
    ({"score": 3}, {"score": 3}, True, None),
    ({"score": 3, "prior-knowledge": 2}, {"score": 3}, False, "overall mean 2.90"),
])
def test_the_domain_average_and_the_overall_mean_at_their_edges(fictional_store, example_roster, first, second, ok, why):
    assert "prior-knowledge" in DOMAINS
    store(fictional_store, example_roster)
    observe(fictional_store, P3, first.pop("score"), **first)
    observe(fictional_store, C5, second.pop("score"), **second)
    dry_run(fictional_store)
    app.do_run(fictional_store, now=T0)
    assert bool(rounds(fictional_store)) is ok
    if not ok:
        assert any(why in r for r in blocked(fictional_store)[-1])


def test_a_coach_counts_once_among_the_observers(fictional_store, example_roster):
    store(fictional_store, example_roster, coaches=(P3, C5))
    observe(fictional_store, P3)
    observe(fictional_store, C5)
    dry_run(fictional_store)
    app.do_run(fictional_store, now=T0)
    assert rounds(fictional_store) == [] and any("distinct calibrated observers" in r for r in blocked(fictional_store)[-1])


def test_a_coach_of_another_instructor_is_an_ordinary_observer(fictional_store, example_roster):
    """The coach limit is per instructor (decision 0014, flows.common.coaches_of): P3 and C5 coach R8, not the SME, so
    both count as full observers of the SME."""
    store(fictional_store, example_roster, coaches=(P3, C5), coaches_of=(R8,))
    observe(fictional_store, P3)
    observe(fictional_store, C5)
    dry_run(fictional_store)
    app.do_run(fictional_store, now=T0)
    assert len(rounds(fictional_store)) == 1


def test_a_coach_who_lists_nobody_coaches_nobody(fictional_store, example_roster):
    store(fictional_store, example_roster, coaches=(P3, C5), coaches_of=())
    observe(fictional_store, P3)
    observe(fictional_store, C5)
    dry_run(fictional_store)
    app.do_run(fictional_store, now=T0)
    assert len(rounds(fictional_store)) == 1  # no "coaches everyone" default


def test_a_short_observation_is_not_the_only_full_lead_evidence(fictional_store, example_roster):
    store(fictional_store, example_roster)
    observe(fictional_store, P3, length="short", lead=True)
    observe(fictional_store, C5, length="full", lead=False)
    dry_run(fictional_store)
    app.do_run(fictional_store, now=T0)
    assert rounds(fictional_store) == [] and any("no full observation" in r for r in blocked(fictional_store)[-1])
    observe(fictional_store, C5, length="full", lead=True)
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert len(rounds(fictional_store)) == 1  # the short one still counts toward the minimum beside a full lead


def test_the_verdict_names_the_observations_that_counted(calibrations):
    eng = "tm:instructor/eng-1"
    obs = [rules.Observation(f"o{n}", eng, UNIT, f"tm:instructor/{o}", date(2026, 10, 1), "full", True,
                             {d: 3 for d in DOMAINS}) for n, o in enumerate(("obs-a", "obs-b", "obs-d"))]
    dry = [rules.DryRun(eng, UNIT, "remote", True, date(2026, 9, 20))]
    verdict = rules.clearance_check(eng, UNIT, "remote", obs, dry, calibrations, set(), DOMAINS, STD["rules"])
    assert verdict.ok and verdict.detail["observations"] == ["o0", "o1"]  # obs-d's calibration had lapsed


# --- who may decide ---------------------------------------------------------------------------------------------


def test_the_decision_pages_go_to_the_calibrated_clearers_who_are_not_the_instructor(fictional_store, ready):
    ready(calibrated=(P3, C5, K7))  # the instructor is calibrated, not a clearer
    assert signers(fictional_store, D1) == sorted([P3, C5])  # R8 is a clearer but not calibrated


def test_the_instructor_cannot_decide_their_own_clearance(fictional_store, ready):
    ready(clearers=(P3, C5, K7), calibrated=(P3, C5, K7))
    assert K7 not in signers(fictional_store, D1)
    assert any("instructor" in r for r in reasons(fictional_store, D1, K7, cleared()))


def test_a_person_mapped_to_the_instructor_cannot_decide_either(fictional_store, ready):
    ready()
    st = app.load_state(fictional_store)
    assert clearance.is_instructor(st, INSTRUCTOR, INSTRUCTOR)
    doc = document(fictional_store, D1, INSTRUCTOR, cleared())
    assert any("instructor" in r for r in flows.content_reasons(st, doc))


def test_an_uncalibrated_clearer_is_refused(fictional_store, ready):
    ready()
    assert any("calibrated" in r for r in reasons(fictional_store, D1, R8, cleared()))
    # calibrated, but the pass has lapsed by the decision date (renewal is 6 months)
    assert any("calibrated" in r for r in reasons(fictional_store, D1, P3, cleared(), at="2027-04-02T09:00:00+00:00"))


def test_the_same_clearer_cannot_make_both_decisions(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    assert signers(fictional_store, D2) == [C5]
    assert any("decision 1" in r for r in reasons(fictional_store, D2, P3, cleared()))


def test_a_coach_may_be_one_clearer_but_not_both(fictional_store, ready):
    ready(calibrated=(P3, C5, R8), coaches=(P3, R8))
    decide(fictional_store, D1, P3, cleared())
    assert signers(fictional_store, D2) == [C5]  # R8 is a coach too
    assert any("coach" in r for r in reasons(fictional_store, D2, R8, cleared()))
    assert reasons(fictional_store, D2, C5, cleared()) == []


def test_two_coaches_of_other_instructors_may_both_decide(fictional_store, ready):
    ready(calibrated=(P3, C5, R8), coaches=(P3, R8), coaches_of=(C5,))
    decide(fictional_store, D1, P3, cleared())
    assert signers(fictional_store, D2) == [C5, R8]  # neither coaches the SME, so the pair is not limited
    assert reasons(fictional_store, D2, R8, cleared()) == []


@pytest.mark.parametrize("fields,why", [
    ({}, "outcome"),
    ({"outcome": "revoked"}, "outcome"),
    ({"outcome": "cleared_with_conditions", "recheck": "2026-12-01"}, "conditions"),
    ({"outcome": "cleared_with_conditions", "conditions": "Run the pre-check"}, "recheck"),
    ({"outcome": "cleared_with_conditions", "conditions": "Run the pre-check", "recheck": "2026-10-27"}, "recheck"),
    ({"outcome": "cleared_with_conditions", "conditions": "Run the pre-check", "recheck": "2028-01-01"}, "recheck"),
    ({"outcome": "not_yet"}, "actions"),
    ({"outcome": "not_yet", "actions": "   "}, "actions"),
])
def test_a_decision_must_carry_what_its_outcome_needs(fictional_store, ready, fields, why):
    ready()
    found = reasons(fictional_store, D1, P3, fields)
    assert found and any(why in r for r in found)
    assert all("pre-check" not in r for r in found)  # a reason names the field, never the answer


def test_the_decision_page_shows_the_evidence_and_not_the_other_decision(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, not_yet())
    (spec,) = app._page_specs(app.load_state(fictional_store), D2, CAND)
    assert spec["inputs"]["averages"] == {d: 3 for d in DOMAINS} and spec["inputs"]["observers"] == sorted([P3, C5])
    shown = json.dumps([spec["inputs"], spec["intro"]])
    assert "not_yet" not in shown and "coaching" not in shown and spec["inputs"]["decision_1_signer"] == P3  # blind
    assert {f["name"] for f in spec["fields"]} == {"outcome", "conditions", "recheck", "actions"}


# --- agreement, disagreement and the clearance event ---------------------------------------------------------------


def test_two_cleared_decisions_skip_the_head_and_issue_the_clearance(fictional_store, ready):
    ready()
    assert check_staffing(fictional_store)["verdict"] == "block"
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared(), at="2026-10-28T09:00:00+00:00")
    assert (HEAD, CAND) not in due_ids(fictional_store)  # skipped: the outcomes agree
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    (event,) = issued(fictional_store)
    p = event["payload"]
    assert p["outcome"] == "cleared" and p["clearers"] == [P3, C5] and p["modes"] == ["in-person"]
    assert p["issued"] == "2026-10-28" and p["expires"] == rules.expiry_date(date(2026, 10, 28), STD["rules"]).isoformat()
    assert p["framework_version"] == STD["framework"]["version"] and p["recheck"] is None and p["conditions"] == []
    assert sorted(p["observations"]) == sorted(o["id"] for o in of_kind(fictional_store, "observation"))
    assert p["clearance"].startswith("tm:clearance/") and p["candidate"] == CAND and event["subject_uri"] == CAND
    assert events.check_event(event) == []
    assert check_staffing(fictional_store) == {"verdict": "ok", "reasons": [], "clearance": p["clearance"]}
    assert check_staffing(fictional_store, mode="hybrid")["verdict"] == "block"
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert len(issued(fictional_store)) == 1  # idempotent
    assert not ({D1, D2, HEAD, ISSUE} & {s for s, c in due_ids(fictional_store, T0 + timedelta(days=4)) if c == CAND})


def test_a_disagreement_goes_to_the_head_who_decides(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, not_yet())
    assert (HEAD, CAND) in due_ids(fictional_store)
    (spec,) = app._page_specs(app.load_state(fictional_store), HEAD, CAND)
    assert spec["signer"] == HOT
    assert [(d["signer"], d["outcome"]) for d in spec["inputs"]["decisions"]] == [(P3, "cleared"), (C5, "not_yet")]
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    assert issued(fictional_store) == []  # the head has not decided
    decide(fictional_store, HEAD, HOT, conditional(), at="2026-10-29T09:00:00+00:00")
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    (event,) = issued(fictional_store)
    p = event["payload"]
    assert p["outcome"] == "cleared_with_conditions" and p["recheck"] == "2026-12-01" and p["clearers"] == [P3, C5]
    assert p["issued"] == "2026-10-29" and len(p["conditions"]) == 1
    assert "pre-check" not in json.dumps(log(fictional_store))  # the condition text stays in the private store
    kept = json.loads((fictional_store / p["conditions"][0].split("#", 1)[0]).read_text(encoding="utf-8"))
    assert kept["conditions"] == ["Run the pre-check in the first ten minutes"]
    assert check_staffing(fictional_store, on="2026-10-31")["verdict"] == "ok"
    assert check_staffing(fictional_store)["verdict"] == "warn"  # 29 days before the recheck


def test_two_conditional_decisions_join_their_conditions_and_take_the_earlier_recheck(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, conditional("2026-12-15", "Pace the remote room"))
    decide(fictional_store, D2, C5, conditional("2026-12-01", "Run the pre-check\nPace the remote room"))
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    (event,) = issued(fictional_store)
    assert event["payload"]["recheck"] == "2026-12-01" and len(event["payload"]["conditions"]) == 2


def test_not_yet_from_both_issues_a_not_yet_that_blocks_staffing(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, not_yet())
    decide(fictional_store, D2, C5, not_yet())
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    (event,) = issued(fictional_store)
    assert event["payload"]["outcome"] == "not_yet" and check_staffing(fictional_store)["verdict"] == "block"
    assert "coaching" not in json.dumps(log(fictional_store))  # the actions stay private too


# --- a new observation, the recheck and the expiry --------------------------------------------------------------


def test_a_new_observation_reopens_undecided_decisions_but_not_an_issued_clearance(fictional_store, ready):
    ready(calibrated=(P3, C5, R8))
    stale = document(fictional_store, D1, P3, cleared())
    observe(fictional_store, R8, day="2026-10-22")
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert len(rounds(fictional_store)) == 2 and len(rounds(fictional_store)[-1]["payload"]["observations"]) == 3
    fresh = document(fictional_store, D1, P3, cleared())
    assert fresh["input_sha256"] != stale["input_sha256"]  # the old page's sign-off is stale at ingest

    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    assert len(issued(fictional_store)) == 1
    observe(fictional_store, R8, day="2026-10-29")
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert len(rounds(fictional_store)) == 2  # a cleared candidate's evidence is not re-decided
    assert (D1, CAND) not in due_ids(fictional_store, T0 + timedelta(days=4))


def test_after_not_yet_new_evidence_opens_a_new_round(fictional_store, ready):
    ready(calibrated=(P3, C5, R8))
    decide(fictional_store, D1, P3, not_yet())
    decide(fictional_store, D2, C5, not_yet())
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    first = issued(fictional_store)[0]["payload"]["clearance"]
    observe(fictional_store, R8, day="2026-11-10")
    later = T0 + timedelta(days=16)
    app.do_run(fictional_store, now=later)
    assert rounds(fictional_store)[-1]["payload"]["after"] == first
    assert (D1, CAND) in due_ids(fictional_store, later)
    decide(fictional_store, D1, R8, cleared(), at="2026-11-12T09:00:00+00:00")
    decide(fictional_store, D2, C5, cleared(), at="2026-11-12T10:00:00+00:00")
    app.do_run(fictional_store, now=later + timedelta(days=1))
    assert [e["payload"]["outcome"] for e in issued(fictional_store)] == ["not_yet", "cleared"]
    assert check_staffing(fictional_store, on="2026-11-13")["verdict"] == "ok"


def test_a_missed_recheck_lapses_the_clearance_to_not_yet(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, conditional("2026-12-01"))
    decide(fictional_store, D2, C5, conditional("2026-12-01"))
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    (lapse,) = due_of(fictional_store, LAPSE, T0 + timedelta(days=2))
    assert lapse.due == date(2026, 12, 1)  # the conditional_recheck due rule
    on_day = datetime(2026, 12, 1, 8, tzinfo=timezone.utc)
    app.do_run(fictional_store, now=on_day)
    # still valid on the recheck day, with the recheck warning (rules.staffing.warn_expiry_days)
    assert len(issued(fictional_store)) == 1 and check_staffing(fictional_store, on="2026-12-01")["verdict"] == "warn"
    day_after = on_day + timedelta(days=1)
    app.do_run(fictional_store, now=day_after)
    first, superseding = issued(fictional_store)
    assert superseding["payload"]["clearance"] == first["payload"]["clearance"]
    assert superseding["payload"]["outcome"] == "not_yet" and superseding["payload"]["issued"] == first["payload"]["issued"]
    assert [c.outcome for c in records.clearances(log(fictional_store)) if c.instructor == INSTRUCTOR] == ["not_yet"]
    assert check_staffing(fictional_store, on="2026-11-30")["verdict"] == "block"  # the record now says not yet
    app.do_run(fictional_store, now=day_after + timedelta(days=1))
    assert len(issued(fictional_store)) == 2  # idempotent
    assert (LAPSE, CAND) not in due_ids(fictional_store, day_after)


def test_the_renewal_opens_thirty_days_before_expiry_on_new_evidence_and_falls_due_on_it(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    first = issued(fictional_store)[0]["payload"]
    expires = date.fromisoformat(first["expires"])
    for c in (P3, C5):
        calibrate(fictional_store, c, on=(expires - timedelta(days=60)).isoformat())  # still calibrated then
        hold(fictional_store, c, issued=(expires - timedelta(days=60)).isoformat(),
             expires=(expires + timedelta(days=300)).isoformat())  # and still cleared for the unit
    early = datetime.combine(expires - timedelta(days=31), datetime.min.time(), timezone.utc)
    app.do_run(fictional_store, now=early)
    assert len(rounds(fictional_store)) == 1 and check_staffing(fictional_store, on=early.date().isoformat())["verdict"] == "ok"
    warn = early + timedelta(days=1)  # 30 days left: rules.staffing.warn_expiry_days
    app.do_run(fictional_store, now=warn)
    assert check_staffing(fictional_store, on=warn.date().isoformat())["verdict"] == "warn"
    # The renewal rests on new evidence: the observations of the first round predate the clearance it renews.
    assert len(rounds(fictional_store)) == 1 and any("calibrated observations" in r for r in blocked(fictional_store)[-1])
    new_day = (expires - timedelta(days=40)).isoformat()
    for c in (P3, C5):
        observe(fictional_store, c, day=new_day)
    app.do_run(fictional_store, now=warn + timedelta(hours=1))
    rnd = rounds(fictional_store)[-1]["payload"]
    assert rnd["after"] == first["clearance"] and rnd["reason"] == "renewal" and rnd["since"] == first["issued"]
    assert len(rnd["observations"]) == 2 and not set(rnd["observations"]) & set(first["observations"])
    (d1,) = due_of(fictional_store, D1, warn)
    assert d1.due == expires and not d1.overdue  # `next` shows the renewal decision, due on the expiry date


def test_the_first_decision_is_due_a_fortnight_after_the_round_opened(fictional_store, ready):
    ready()
    (d1,) = due_of(fictional_store, D1)
    assert d1.due == T0.date() + timedelta(days=clearance.DECISION_DAYS)


# --- through the real mail round trip ---------------------------------------------------------------------------


def test_decisions_through_ingest_refuse_the_same_clearer_twice_and_issue_on_two(fictional_store, ready):
    ready()
    app.do_tick(fictional_store, now=T0)
    rep = ingest(fictional_store, [signoff(fictional_store, D1, CAND, P3, cleared(), now=T0)], now=T0, name="d1")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    later = T0 + timedelta(hours=3)
    app.do_tick(fictional_store, now=later)
    page = (fictional_store / "pages" / f"{app.page_stem(D2, CAND, C5)}.html")
    assert page.is_file() and not (fictional_store / "pages" / f"{app.page_stem(D2, CAND, P3)}.html").exists()
    data = page_data(fictional_store, D2, CAND, C5)
    twice = signoff(fictional_store, D2, CAND, P3, cleared(), now=later, data={**data, "signer": P3})
    rep = ingest(fictional_store, [twice], now=later, name="twice")
    assert "1 rejected" in rep.summary and any("decision 1" in line for line in rep.lines), rep.all_lines()
    rep = ingest(fictional_store, [signoff(fictional_store, D2, CAND, C5, cleared(), now=later)], now=later, name="d2")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    app.do_run(fictional_store, now=later + timedelta(hours=3))
    assert [e["payload"]["outcome"] for e in issued(fictional_store)] == ["cleared"]


# --- integration-review fixes ----------------------------------------------------------------------------------------


def add_person(private, person, roles, instructor=None):
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    slug = person.split("/", 1)[1]
    row = {"person": person, "name": f"Person {slug}", "email": f"{slug}@example.com", "roles": roles}
    if instructor:
        row["instructor"] = instructor
    doc["people"].append(row)
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def issue_checks(private):
    return [e["payload"]["reasons"] for e in of_kind(private, "check", CAND) if e["payload"].get("step") == ISSUE]


def test_issue_rechecks_the_evidence_and_issues_nothing_once_it_fails(fictional_store, ready, monkeypatch):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    real = clearance.current_environment_hashes
    monkeypatch.setattr(clearance, "current_environment_hashes", lambda uris, root=None: {u: "f" * 64 for u in uris})
    app.do_run(fictional_store, now=T0 + timedelta(days=2))  # the unit's environment changed: the dry run is void
    assert issued(fictional_store) == []
    (why,) = issue_checks(fictional_store)
    assert why[0].startswith("evidence no longer meets the clearance minimum: ") and "dry-run" in why[0]
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    assert len(issue_checks(fictional_store)) == 1  # said once
    monkeypatch.setattr(clearance, "current_environment_hashes", real)
    app.do_run(fictional_store, now=T0 + timedelta(days=4))
    assert [e["payload"]["outcome"] for e in issued(fictional_store)] == ["cleared"]


def test_a_voided_dry_run_and_a_new_one_open_a_new_round(fictional_store, ready, monkeypatch):
    ready()
    stale = document(fictional_store, D1, P3, cleared())
    monkeypatch.setattr(clearance, "current_environment_hashes", lambda uris, root=None: {u: "f" * 64 for u in uris})
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert len(rounds(fictional_store)) == 1 and any("dry-run" in r for r in blocked(fictional_store)[-1])
    with pytest.raises(PageProblem, match="evidence no longer meets"):  # no page while the evidence is short
        app._page_specs(app.load_state(fictional_store), D1, CAND)
    assert any("evidence" in r for r in flows.content_reasons(app.load_state(fictional_store), stale))  # nor a sign-off
    dry_run(fictional_store, day="2026-10-26", env="f" * 64)  # the dry run is redone on the changed environment
    app.do_run(fictional_store, now=T0 + timedelta(hours=2))
    first, second = rounds(fictional_store)
    assert second["payload"]["evidence_sha256"] != first["payload"]["evidence_sha256"]
    assert second["payload"]["dry_runs"] == ["2026-10-26"]
    assert document(fictional_store, D1, P3, cleared())["input_sha256"] != stale["input_sha256"]


def test_the_head_must_hold_the_role_and_not_be_the_instructor(fictional_store, ready):
    ready()
    add_person(fictional_store, "tm:person/head-k7", ["head-of-training"], instructor=INSTRUCTOR)
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, not_yet())
    assert signers(fictional_store, HEAD) == [HOT]  # the head mapped to the instructor gets no page
    assert any("instructor" in r for r in reasons(fictional_store, HEAD, "tm:person/head-k7", cleared()))
    assert any("instructor" in r for r in reasons(fictional_store, HEAD, INSTRUCTOR, cleared()))
    assert any("head of training" in r for r in reasons(fictional_store, HEAD, P3, cleared()))
    assert reasons(fictional_store, HEAD, HOT, cleared()) == []


def test_a_decision_signed_before_the_round_opened_is_refused(fictional_store, ready):
    ready(calibrated=(P3, C5))
    calibrate(fictional_store, R8, on="2026-03-01")  # lapsed on 1 September; the round opened on 26 October
    assert R8 not in signers(fictional_store, D1)
    assert any("calibrated" in r for r in reasons(fictional_store, D1, R8, cleared()))
    backdated = reasons(fictional_store, D1, R8, cleared(), at="2026-08-31T09:00:00+00:00")
    assert any("signed_at" in r and "round" in r for r in backdated)
    assert any("signed_at" in r for r in reasons(fictional_store, D1, P3, cleared(), at="2026-10-25T23:00:00+00:00"))
    assert reasons(fictional_store, D1, P3, cleared(), at="2026-10-26T09:00:00+00:00") == []
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, not_yet())
    assert any("signed_at" in r for r in reasons(fictional_store, HEAD, HOT, cleared(), at="2026-10-25T09:00:00+00:00"))


def test_a_decision_signed_more_than_a_day_after_ingest_is_refused(fictional_store, ready):
    ready()
    st = app.load_state(fictional_store)
    st.cache[clearance.NOW_KEY] = T0
    late = document(fictional_store, D1, P3, cleared(), at=(T0 + timedelta(days=1, minutes=1)).isoformat())
    assert any("signed_at" in r for r in flows.content_reasons(st, late))
    fine = document(fictional_store, D1, P3, cleared(), at=(T0 + timedelta(hours=23)).isoformat())
    assert flows.content_reasons(st, fine) == []


def test_observations_against_another_rubric_major_do_not_count(fictional_store, example_roster):
    store(fictional_store, example_roster)
    observe(fictional_store, P3, rubric="2.0.0")
    observe(fictional_store, C5)
    dry_run(fictional_store)
    app.do_run(fictional_store, now=T0)
    assert rounds(fictional_store) == [] and any("calibrated observations; need 2" in r for r in blocked(fictional_store)[-1])


def test_the_same_person_under_another_uri_cannot_make_decision_two(fictional_store, ready):
    ready()
    add_person(fictional_store, "tm:person/p3-alias", ["clearer"], instructor=P3)
    decide(fictional_store, D1, P3, cleared())
    assert "tm:person/p3-alias" not in signers(fictional_store, D2)
    assert any("decision 1" in r for r in reasons(fictional_store, D2, "tm:person/p3-alias", cleared()))


def test_a_clearer_decides_only_within_their_modules(fictional_store, ready):
    ready(calibrated=(P3, C5, R8), held=(P3, C5))
    assert signers(fictional_store, D1) == sorted([P3, C5])  # R8 is calibrated but holds no clearance for the unit
    assert any("within their modules" in r for r in reasons(fictional_store, D1, R8, cleared()))
    hold(fictional_store, R8, unit="sl:unit/another-unit@1")
    assert any("within their modules" in r for r in reasons(fictional_store, D1, R8, cleared()))
    hold(fictional_store, R8)
    assert reasons(fictional_store, D1, R8, cleared()) == []


def test_no_decision_page_while_the_evidence_no_longer_meets_the_minimum(fictional_store, ready, monkeypatch):
    """Found by the simulation (2026-10-27): evidence that fell below the minimum after the round opened left a decision-2
    page that every sign-off was refused on, every day. The builders now refuse to build it, as the issue step refuses to
    issue, and the page comes back once the evidence meets the minimum again."""
    ready()
    decide(fictional_store, D1, P3, cleared())
    assert signers(fictional_store, D2)
    real = clearance.current_environment_hashes
    monkeypatch.setattr(clearance, "current_environment_hashes", lambda uris, root=None: {u: "f" * 64 for u in uris})
    with pytest.raises(PageProblem, match="evidence no longer meets the clearance minimum"):
        app._page_specs(app.load_state(fictional_store), D2, CAND)
    with pytest.raises(PageProblem, match="evidence no longer meets the clearance minimum"):
        app._page_specs(app.load_state(fictional_store), D1, CAND)
    monkeypatch.setattr(clearance, "current_environment_hashes", real)
    assert signers(fictional_store, D2)
