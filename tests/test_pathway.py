"""The pathway workflow: the auto step `open-candidates` (standards/workflows/pathway.yaml).

For every instructor whose latest level is lead-observed or higher, one `candidate` subject per registration `delivers`
unit x mode (event@3 `subject`, decision 0011). It runs once its needs are met and again whenever they still are
(like the ROPA refresh), opening only candidates that do not exist yet. Fictional people only.
"""

from datetime import datetime, timedelta, timezone

from privacy_helpers import import_roster_ungated

from teachermodel import app, events, workflow
from teachermodel.flows import pathway
from teachermodel.standards import ROOT, load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
STEP = "tm:step/open-candidates"
PROGRAMME = "tm:programme/teachermodel"
SME = "tm:instructor/k7m2q"  # co-deliver; delivers the example unit in-person and hybrid
PROFESSIONAL = "tm:instructor/p3x9d"  # cleared; delivers it in-person, remote and hybrid
CONTRACTOR = "tm:instructor/c5w1t"  # lead-observed; delivers nothing
PARTNER = "tm:instructor/r8n4h"  # shadow
UNIT = "sl:unit/example-agent-loop@1"


def log(private):
    return app.read_events(private)


def candidates(private):
    return [e for e in log(private) if e["kind"] == "subject" and e["payload"]["subject_kind"] == "candidate"]


def uris(private):
    return sorted(e["subject_uri"] for e in candidates(private))


def step_events(private):
    return [e for e in log(private) if e["kind"] == "step" and e["payload"].get("step") == STEP]


def due(private, now=T0):
    return {(d.step, d.subject) for d in app.due_steps(app.load_state(private), now.date())}


def imported(private, roster):
    import_roster_ungated(private, roster, T0)


def make_lead_observed(private, uri, at="2026-10-26T09:00:00+00:00", before="co-deliver"):
    events.append(private / app.EVENT_LOG, events.make_event(
        "level_change", uri, "tm:person/hot-1", {"from": before, "to": "lead-observed", "basis": "signoff test"}, at=at))


def test_the_workflow_file_defines_one_auto_programme_step():
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/pathway"]
    (st,) = wf["steps"]
    assert st["id"] == STEP and st["type"] == "auto" and st["subject"] == "programme"
    assert set(wf["event_kinds"]) == {"step", "subject"}
    assert "tm:step/roster-import" in st["needs"]
    assert st["done_when"] == {"kind": "step", "match": {"step": STEP}}


def test_the_step_is_not_due_before_the_roster_import(fictional_store):
    assert (STEP, PROGRAMME) not in due(fictional_store)


def test_the_step_is_due_after_the_roster_import_and_done_after_a_run(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    assert (STEP, PROGRAMME) in due(fictional_store)
    app.do_run(fictional_store, now=T0)
    assert (STEP, PROGRAMME) not in due(fictional_store)


def test_opens_one_candidate_per_unit_and_mode_for_instructors_at_lead_observed_or_higher(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    assert uris(fictional_store) == [
        "tm:candidate/p3x9d--example-agent-loop-1--hybrid",
        "tm:candidate/p3x9d--example-agent-loop-1--in-person",
        "tm:candidate/p3x9d--example-agent-loop-1--remote",
    ]  # the cleared professional only: the SME is co-deliver, the contractor delivers nothing, the partner is shadow


def test_a_candidate_event_has_the_fixed_shape(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    event = next(e for e in candidates(fictional_store) if e["subject_uri"].endswith("--remote"))
    assert event["actor"] == workflow.SYSTEM_ACTOR
    assert event["payload"] == {
        "subject_kind": "candidate",
        "attrs": {"instructor": PROFESSIONAL, "unit": UNIT, "mode": "remote"},
        "opened_by": STEP,
    }
    assert event["subject_uri"] == workflow.candidate_uri(PROFESSIONAL, UNIT, "remote")
    assert events.check_event(event) == []


def test_candidates_are_subjects_of_the_engine(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    st = app.load_state(fictional_store)
    cand = "tm:candidate/p3x9d--example-agent-loop-1--remote"
    assert st.subjects[cand] == {"kind": "candidate", "instructor": PROFESSIONAL, "unit": UNIT, "mode": "remote"}


def test_the_step_event_names_what_it_opened(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    (done,) = step_events(fictional_store)
    assert done["subject_uri"] == PROGRAMME and done["actor"] == workflow.SYSTEM_ACTOR
    assert done["payload"] == {"step": STEP, "opened": uris(fictional_store)}


def test_a_second_run_changes_nothing(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    before = log(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    app.do_run(fictional_store, now=T0 + timedelta(hours=2))
    assert log(fictional_store) == before


def test_event_ids_are_deterministic(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    ids = {e["subject_uri"]: e["id"] for e in candidates(fictional_store)}
    assert ids and all(i == pathway.subject_event_id(u) for u, i in ids.items())
    assert len(set(ids.values())) == len(ids)
    assert pathway.subject_event_id("tm:candidate/x--u-1--remote") == pathway.subject_event_id("tm:candidate/x--u-1--remote")


def test_a_later_level_change_opens_that_instructors_candidates_and_only_those(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    first = uris(fictional_store)
    make_lead_observed(fictional_store, SME)
    rep = app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert any(STEP in line and "refreshed" in line for line in rep.lines), rep.lines
    after = uris(fictional_store)
    assert after == sorted(first + ["tm:candidate/k7m2q--example-agent-loop-1--hybrid",
                                    "tm:candidate/k7m2q--example-agent-loop-1--in-person"])
    assert len(after) == len(set(after))  # nothing opened twice
    assert len(step_events(fictional_store)) == 2  # a step event for the first run and one for the refresh
    assert step_events(fictional_store)[-1]["payload"]["opened"] == [u for u in after if "k7m2q" in u]
    before = log(fictional_store)
    app.do_run(fictional_store, now=T0 + timedelta(hours=2))
    # Nothing of this step (W4's evidence-ready writes its first blocked check for the new candidates on this run)
    assert [e for e in log(fictional_store)[len(before):] if e["kind"] == "subject"
            or e["payload"].get("step") == STEP] == []


def test_a_level_below_lead_observed_opens_nothing(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "level_change", PROFESSIONAL, "tm:person/hot-1", {"from": "cleared", "to": "co-deliver", "basis": "test"},
        at="2026-10-26T09:00:00+00:00"))  # the latest level counts, not the registration's
    app.do_run(fictional_store, now=T0)
    assert uris(fictional_store) == []
    (done,) = step_events(fictional_store)  # the step is still done: it ran and found nobody
    assert done["payload"]["opened"] == []
    assert (STEP, PROGRAMME) not in due(fictional_store)


def test_an_existing_candidate_is_never_reopened(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    existing = workflow.candidate_uri(PROFESSIONAL, UNIT, "remote")
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "subject", existing, workflow.SYSTEM_ACTOR,
        {"subject_kind": "candidate", "attrs": {"instructor": PROFESSIONAL, "unit": UNIT, "mode": "remote"},
         "opened_by": "tm:step/test"}, id="0" * 32, at="2026-10-26T07:00:00+00:00"))
    app.do_run(fictional_store, now=T0)
    assert uris(fictional_store).count(existing) == 1 and len(uris(fictional_store)) == 3


def test_a_new_delivery_in_a_later_roster_opens_a_new_candidate(fictional_store, example_roster, tmp_path):
    import yaml

    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    doc = yaml.safe_load(example_roster.read_text(encoding="utf-8"))
    row = next(r for r in doc["instructors"] if r["instructor"] == PROFESSIONAL)
    row["delivers"][0]["modes"] = ["in-person", "remote", "hybrid"]
    row["delivers"].append({"unit": "sl:unit/example-agent-loop@2", "modes": ["remote"]})
    # a later registration event carries the new delivery
    reg = next(e for e in log(fictional_store) if e["kind"] == "registration" and e["subject_uri"] == PROFESSIONAL)
    payload = {**reg["payload"], "delivers": row["delivers"], "roster_as_of": "2026-11-01"}
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "registration", PROFESSIONAL, workflow.SYSTEM_ACTOR, payload, at="2026-10-27T08:00:00+00:00"))
    app.do_run(fictional_store, now=T0 + timedelta(days=1))
    assert "tm:candidate/p3x9d--example-agent-loop-2--remote" in uris(fictional_store)
    assert len(uris(fictional_store)) == 4


def test_the_log_still_verifies(fictional_store, example_roster):
    imported(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    make_lead_observed(fictional_store, SME)
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert events.verify(fictional_store / app.EVENT_LOG) == []


def test_standards_validate_with_the_pathway_file():
    from teachermodel.standards import check_standards

    assert check_standards(ROOT) == []
