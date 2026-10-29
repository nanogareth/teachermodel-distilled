"""W9 CPD (standards/workflows/cpd.yaml, flows/cpd.py, records/cpd.py).

cpd-plan (auto, per instructor) seeds generated/cpd/<slug>.json from the lowest-scoring domains across the last 180 days of
observations; log-activity (the instructor) writes `cpd` events, the activity text staying private; the next coaching cycle's
close keeps or closes each gap (closed when the domain's latest average is 3 or more). Fictional people only.
"""

import json
from datetime import date, timedelta

import pytest
from ingest_helpers import ingest, signoff
from test_coaching_support import (
    BASIC,
    C5,
    CQ,
    DOMAINS,
    K7,
    LF,
    LOW,
    P3,
    PK,
    R8,
    RI,
    T0,
    TD,
    UNIT,
    cycle_uri,
    drive_cycle,
    due_ids,
    log,
    world,
)
from test_observation import of_kind, sign

from teachermodel import app, due, events, flows, records, rules
from teachermodel.flows import cpd
from teachermodel.standards import ROOT, check_standards, load_standards

STEP_PLAN, STEP_LOG = "tm:step/cpd-plan", "tm:step/log-activity"
PLAN = "generated/cpd/p3x9d.json"
CYCLE = cycle_uri(P3)
ACTIVITY = "TAU-ACTIVITY read the retry chapter and rebuilt the lab from scratch"


def wf():
    return {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/cpd"]


def plan(private, rel=PLAN):
    return json.loads((private / rel).read_text(encoding="utf-8"))


def log_fields(domains=(PK,), hours=2.5, day="2026-10-26", text=ACTIVITY):
    return {"activity": text, "hours": hours, "date": day, **{f"domain-{d}": d in domains for d in DOMAINS}}


# --- the workflow file -------------------------------------------------------------------------------------------


def test_the_workflow_file_defines_the_two_cpd_steps():
    steps = {s["id"]: s for s in wf()["steps"]}
    assert set(steps) == {STEP_PLAN, STEP_LOG}
    assert (steps[STEP_PLAN]["type"], steps[STEP_PLAN]["subject"]) == ("auto", "instructor")
    log_step = steps[STEP_LOG]
    assert (log_step["type"], log_step["role"], log_step["subject"], log_step["needs"]) == ("human", "instructor", "instructor", [STEP_PLAN])
    assert log_step["done_when"]["bind"] == "input" and log_step["due"] == "cpd_activity_window"
    assert "cpd_activity_window" in due.names() and set(wf()["event_kinds"]) >= {"step", "signoff", "cpd"}


def test_standards_validate_with_the_cpd_file():
    assert check_standards(ROOT) == []


def test_every_cpd_step_has_its_runner_or_builder():
    assert flows.AUTO_STEPS[STEP_PLAN].per == "instructor" and STEP_LOG in flows.PAGE_SPECS
    assert STEP_LOG in flows.SIGNOFF_HOOKS


# --- pure: seeding and reviewing gaps ----------------------------------------------------------------------------


def test_the_gaps_are_the_two_lowest_domains_below_the_target():
    order = DOMAINS
    assert cpd.TARGET == 3
    assert cpd.seed_gaps({TD: 4.0, PK: 2.0, CQ: 3.0, LF: 1.0, RI: 3.0}, order) == [(LF, 1.0), (PK, 2.0)]
    assert cpd.seed_gaps({TD: 4.0, PK: 2.99, CQ: 3.0, LF: 3.0, RI: 3.0}, order) == [(PK, 2.99)]   # 3.0 is not a gap
    assert cpd.seed_gaps({d: 3.0 for d in order}, order) == []
    assert cpd.seed_gaps({TD: 1.0, PK: 1.0, CQ: 1.0, LF: 1.0, RI: 1.0}, order) == [(TD, 1.0), (PK, 1.0)]  # at most two
    assert cpd.seed_gaps({}, order) == []


def test_the_latest_average_is_over_the_observations_of_the_latest_day():
    def obs(n, day, score, observer):
        return rules.Observation(f"o{n}", P3, UNIT, observer, day, "full", True, {d: score for d in DOMAINS})

    found = [obs(1, date(2026, 9, 1), 1, R8), obs(2, date(2026, 10, 1), 2, R8), obs(3, date(2026, 10, 1), 4, K7),
             obs(4, date(2026, 8, 1), 1, K7)]
    assert cpd.latest_averages(found, P3) == {d: 3.0 for d in DOMAINS}
    assert cpd.latest_averages(found, C5) == {}


# --- records.cpd -------------------------------------------------------------------------------------------------


def cpd_event(n, day, **over):
    payload = {"instructor": P3, "activity_key": f"cpd/{n}.json", "domains": [PK], "hours": 1.5, "logged_on": day,
               "signoff_id": f"{n:016x}", **over}
    return events.make_event("cpd", P3, P3, payload, id=f"cpd-event-{n}", at=f"{day}T10:00:00+00:00")


def test_records_cpd_is_empty_on_no_events():
    assert records.cpd([]) == []


def test_records_cpd_lists_activities_oldest_first_with_parsed_dates_and_ids():
    later, earlier, same = cpd_event(1, "2026-10-20"), cpd_event(2, "2026-09-01"), cpd_event(3, "2026-10-20", hours=4)
    other = events.make_event("check", P3, "tm:system/teachermodel", {"step": "x"}, id="not-cpd-1")
    found = records.cpd([later, other, earlier, same])
    assert [c["id"] for c in found] == ["cpd-event-2", "cpd-event-1", "cpd-event-3"]   # by logged_on, ties in log order
    assert found[0] == {"id": "cpd-event-2", "instructor": P3, "activity_key": "cpd/2.json", "domains": [PK], "hours": 1.5,
                        "logged_on": date(2026, 9, 1), "signoff_id": f"{2:016x}"}
    assert all("activity" not in c for c in found)


# --- cpd-plan ----------------------------------------------------------------------------------------------------


def test_the_plan_is_seeded_from_the_lowest_domains_of_the_last_180_days(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),
                                                    ("obs", P3, "2026-01-01", {d: 1 for d in DOMAINS})))  # too old: ignored
    doc = plan(store)
    assert doc["instructor"] == P3 and doc["target"] == 3 and doc["window_days"] == 180
    assert doc["gaps"] == [{"domain": LF, "seed_average": 1.0, "status": "open"},
                           {"domain": PK, "seed_average": 2.0, "status": "open"}]
    assert doc["reviews"] == []
    (step,) = [e for e in of_kind(store, "step") if e["payload"].get("step") == STEP_PLAN and e["subject_uri"] == P3]
    assert step["payload"]["output"] == PLAN and len(step["payload"]["output_sha256"]) == 64
    assert (STEP_PLAN, P3) not in due_ids(store) and (STEP_LOG, P3) in due_ids(store)


def test_no_observation_in_the_window_means_no_plan_yet(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-01-01", LOW),))
    assert not (store / PLAN).exists()
    assert (STEP_PLAN, P3) in due_ids(store)            # the step waits for evidence
    assert (STEP_LOG, P3) not in due_ids(store)
    assert (STEP_PLAN, K7) in due_ids(store) and not (store / "generated/cpd/k7m2q.json").exists()


def test_a_plan_with_no_domain_below_the_target_has_no_gaps(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", {d: 3 for d in DOMAINS}),))
    assert plan(store)["gaps"] == []


def test_the_plan_is_deterministic_and_a_second_run_changes_nothing(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    first, before = (store / PLAN).read_bytes(), log(store)
    app.do_run(store, now=T0 + timedelta(days=3))
    assert (store / PLAN).read_bytes() == first and log(store) == before
    assert not (store / PLAN).read_text(encoding="utf-8").count("\r")


# --- log-activity ------------------------------------------------------------------------------------------------


def page_inputs(private, step=STEP_LOG, subject=P3):
    (spec,) = app._page_specs(app.load_state(private), step, subject)
    return spec


def test_the_activity_page_is_the_instructors_own_and_shows_the_gaps(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    spec = page_inputs(store)
    assert spec["signer"] == P3 and spec["role"] == "instructor" and spec["template"] == "approve"
    assert spec["inputs"] == {"instructor": P3, "logged": 0,
                              "gaps": [{"domain": LF, "status": "open", "hours": 0}, {"domain": PK, "status": "open", "hours": 0}]}
    names = {f["name"] for f in spec["fields"]}
    assert {"activity", "hours", "date"} <= names and {f"domain-{d}" for d in DOMAINS} <= names


def test_logging_an_activity_writes_a_cpd_event_and_keeps_the_text_private(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    before = page_inputs(store)["inputs"]
    sign(store, STEP_LOG, P3, P3, log_fields((PK,), 2.5, "2026-10-26"), at="2026-10-27T09:00:00+00:00")
    (event,) = of_kind(store, "cpd")
    p = event["payload"]
    assert events.check_event(event) == []
    assert (p["instructor"], p["domains"], p["hours"], p["logged_on"]) == (P3, [PK], 2.5, "2026-10-26")
    assert p["activity_key"] == f"cpd/{p['signoff_id']}.json" and event["actor"] == P3 and event["subject_uri"] == P3
    assert json.loads((store / p["activity_key"]).read_text(encoding="utf-8"))["activity"] == ACTIVITY
    assert ACTIVITY.split()[0] not in (store / app.EVENT_LOG).read_text(encoding="utf-8")
    (rec,) = records.cpd(log(store))
    assert rec["logged_on"] == date(2026, 10, 26) and rec["hours"] == 2.5
    after = page_inputs(store)["inputs"]
    assert after != before and after["logged"] == 1                       # the step opens again for the next activity
    assert [g for g in after["gaps"] if g["domain"] == PK][0]["hours"] == 2.5
    assert [g for g in after["gaps"] if g["domain"] == LF][0]["hours"] == 0
    assert (STEP_LOG, P3) in due_ids(store, T0 + timedelta(days=2))


def test_an_activity_may_span_domains_and_hours_add_up_per_gap(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    sign(store, STEP_LOG, P3, P3, log_fields((LF, PK), 1.5), at="2026-10-27T09:00:00+00:00")
    sign(store, STEP_LOG, P3, P3, log_fields((PK, TD), 2), at="2026-10-28T09:00:00+00:00")
    hours = {g["domain"]: g["hours"] for g in page_inputs(store)["inputs"]["gaps"]}
    assert hours == {LF: 1.5, PK: 3.5}


def test_the_activity_is_due_91_days_after_the_plan_or_the_last_activity(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))

    def due_on():
        (d,) = [d for d in app.due_steps(app.load_state(store), T0.date()) if d.step == STEP_LOG and d.subject == P3]
        return d.due

    assert due_on() == T0.date() + timedelta(days=91)
    sign(store, STEP_LOG, P3, P3, log_fields(day="2026-11-02"), at="2026-11-03T09:00:00+00:00")
    assert due_on() == date(2026, 11, 2) + timedelta(days=91)


@pytest.mark.parametrize("damage,why", [
    ({"activity": "  "}, "activity"),
    ({"activity": None}, "activity"),
    ({"hours": 0}, "hours"),
    ({"hours": -1}, "hours"),
    ({"hours": "two"}, "hours"),
    ({"hours": True}, "hours"),
    ({"hours": 500}, "hours"),
    ({"date": "26/10/2026"}, "date"),
    ({"date": "2026-02-30"}, "date"),
    ({"date": "2026-10-29"}, "date"),            # after the day it was signed
    ({f"domain-{PK}": False}, "domain"),         # no domain ticked
])
def test_an_activity_that_cannot_count_is_refused_naming_the_field(fictional_store, example_roster, damage, why):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    st = app.load_state(store)
    fields = {**log_fields((PK,), 2, "2026-10-26"), **damage}
    doc = {"id": "0123456789abcdef", "step": STEP_LOG, "subject_uri": P3, "decision": "approve", "signer": P3,
           "signed_at": "2026-10-27T09:00:00+00:00", "fields": fields}
    reasons = flows.content_reasons(st, doc)
    assert reasons and any(why in r for r in reasons)
    assert all(ACTIVITY not in r for r in reasons)
    assert flows.content_reasons(st, {**doc, "fields": log_fields((PK,), 2, "2026-10-26")}) == []


def test_an_unknown_domain_field_is_not_a_domain(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    st = app.load_state(store)
    fields = {**log_fields((), 2, "2026-10-26"), "domain-no-such-thing": True}
    doc = {"id": "0123456789abcdef", "step": STEP_LOG, "subject_uri": P3, "decision": "approve", "signer": P3,
           "signed_at": "2026-10-27T09:00:00+00:00", "fields": fields}
    assert flows.content_reasons(st, doc)


def test_the_instructor_logs_an_activity_through_the_real_mail_round_trip(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    app.do_tick(store, now=T0)
    doc, sender = signoff(store, STEP_LOG, P3, P3, log_fields((LF,), 1, "2026-10-26"), now=T0)
    rep = ingest(store, [(doc, sender)], now=T0)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    (rec,) = records.cpd(log(store))
    assert rec["domains"] == [LF] and rec["instructor"] == P3


# --- the cycle's close keeps or closes each gap --------------------------------------------------------------------


def test_closing_a_cycle_closes_the_gaps_whose_latest_average_reached_three_and_keeps_the_rest(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    assert [g["status"] for g in plan(store)["gaps"]] == ["open", "open"]
    sign(store, STEP_LOG, P3, P3, log_fields((PK,), 3, "2026-10-26"), at="2026-10-27T09:00:00+00:00")
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 2})
    doc = plan(store)
    assert {g["domain"]: g["status"] for g in doc["gaps"]} == {LF: "closed", PK: "open"}
    assert [g for g in doc["gaps"] if g["domain"] == LF][0]["closed_by"] == CYCLE
    assert doc["reviews"] == [{"cycle": CYCLE, "closed": [LF], "kept": [PK]}]
    (closed_step,) = [e for e in of_kind(store, "step") if e["payload"].get("step") == "tm:step/cycle-close"]
    assert closed_step["payload"]["cpd_review"] == {"closed": [LF], "kept": [PK]}
    assert (store / "generated/cpd/p3x9d.json").read_text(encoding="utf-8").endswith("\n")
    # the hours logged against the kept gap stay on the page; a closed gap is shown closed
    gaps = {g["domain"]: g for g in page_inputs(store)["inputs"]["gaps"]}
    assert gaps[PK]["status"] == "open" and gaps[PK]["hours"] == 3 and gaps[LF]["status"] == "closed"


def test_a_gap_is_closed_at_exactly_three(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 2, PK: 3})
    assert {g["domain"]: g["status"] for g in plan(store)["gaps"]} == {LF: "open", PK: "closed"}


def test_a_cycle_closing_without_the_plan_file_closes_cleanly_and_rewrites_it(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    (store / PLAN).unlink()
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 3})
    assert [e["payload"]["phase"] for e in of_kind(store, "coaching_cycle") if e["payload"]["cycle"] == CYCLE][-1] == "closed"
    assert (store / PLAN).exists()  # the file is derived from the log (finding 17)
