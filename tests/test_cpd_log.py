"""Integration review finding 17: the log, not the plan file, is the record of the CPD gaps.

The cpd-plan `step` event carries the seeded gaps ({domain, seed_average}); the cycle-close `step` event carries
`cpd_review: {closed, kept}`. `cpd.plan_document` rebuilds the plan (statuses, who closed which gap, the reviews) from them,
so a lost or edited plan file changes nothing: the file is derived and rewritten. Fictional people only.
"""

import json

from test_coaching_support import BASIC, LF, P3, PK, cycle_uri, drive_cycle, world
from test_cpd import ACTIVITY, PLAN, log_fields, plan
from test_observation import of_kind, sign

from teachermodel import app
from teachermodel.flows import cpd

CYCLE = cycle_uri(P3)
CLOSE = "tm:step/cycle-close"


def plan_event(store):
    (event,) = [e for e in of_kind(store, "step") if e["payload"].get("step") == "tm:step/cpd-plan"]
    return event


def close_event(store):
    (event,) = [e for e in of_kind(store, "step") if e["payload"].get("step") == CLOSE]
    return event


def test_the_plan_step_event_carries_the_seeded_gaps(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    gaps = plan_event(store)["payload"]["gaps"]
    assert gaps == [{"domain": g["domain"], "seed_average": g["seed_average"]} for g in plan(store)["gaps"]]
    assert [g["domain"] for g in gaps] == [LF, PK]


def test_the_close_step_event_records_the_review_as_cpd_review(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 2})
    payload = close_event(store)["payload"]
    assert payload["cpd_review"] == {"closed": [LF], "kept": [PK]}
    assert "gaps_closed" not in payload and "gaps_kept" not in payload


def test_the_plan_is_rebuilt_from_the_log_whatever_the_file_says(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 2})
    from_file = plan(store)
    st = app.load_state(store)
    assert cpd.plan_document(st, P3) == from_file
    (store / PLAN).write_text(json.dumps({**from_file, "gaps": [], "reviews": ["tampered"]}), encoding="utf-8")
    assert cpd.plan_document(app.load_state(store), P3) == from_file
    (store / PLAN).unlink()
    assert cpd.plan_document(app.load_state(store), P3) == from_file


def test_the_log_activity_page_reads_the_gap_status_from_the_log(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, "tm:step/log-activity", P3, P3, log_fields((PK,), 3, "2026-10-26"), at="2026-10-27T09:00:00+00:00")
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 2})
    (store / PLAN).unlink()  # the file is gone; the page still shows what the log says
    spec = app._page_specs(app.load_state(store), "tm:step/log-activity", P3)[0]
    gaps = {g["domain"]: g for g in spec["inputs"]["gaps"]}
    assert gaps[LF]["status"] == "closed" and gaps[PK]["status"] == "open" and gaps[PK]["hours"] == 3
    assert ACTIVITY not in json.dumps(spec["inputs"])


def test_a_close_with_the_file_missing_rewrites_the_plan_from_the_log(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    (store / PLAN).unlink()
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 3})
    assert close_event(store)["payload"]["cpd_review"] == {"closed": [LF, PK], "kept": []}
    assert {g["domain"]: g["status"] for g in plan(store)["gaps"]} == {LF: "closed", PK: "closed"}


def test_an_instructor_with_no_plan_event_has_no_plan(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC, run=False)
    assert cpd.plan_document(app.load_state(store), P3) is None
