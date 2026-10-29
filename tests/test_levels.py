"""Level moves (standards/workflows/levels.yaml, flows/levels.py): propose-levels proposes promotions to cleared and clearer
and demotions back when their basis lapses; the head of training decides each row (approve or decline) on one
approve page; the hook writes one `level_change` per approved row that is still proposed. Fictional people only."""

import hashlib
import json
from datetime import timedelta

import pytest

from test_clearance import (
    C5, D1, D2, HOT, INSTRUCTOR, P3, R8, T0, calibrate, cleared, decide, document, due_ids, hold, issued, not_yet,
    build_ready, of_kind, put, steps_of, store,
)
from test_observation import set_level

from teachermodel import app, events, flows, signoff as tm_signoff, workflow
from teachermodel.flows import levels

PROPOSE_LEVELS, LEVELS = "tm:step/propose-levels", "tm:step/levels-decided"
AT = "2026-10-30T09:00:00+00:00"


@pytest.fixture
def ready(fictional_store, cached_world):
    """test_clearance's `ready`: the same cached worlds (the same key)."""

    def make(**kw):
        cached_world("clearance_ready " + json.dumps(kw, sort_keys=True), lambda base: build_ready(base, **kw))
        return fictional_store

    return make


def level_rows(private):
    path = private / "generated" / "levels.json"
    return json.loads(path.read_text(encoding="utf-8"))["rows"] if path.is_file() else None


def moves(private):
    return [(r["key"], r["from"], r["to"]) for r in level_rows(private)]


def decide_levels(private, at=AT, **decline):
    """The head decides every row: approve, except the instructors named in `decline` (slug=True)."""
    fields = {levels.field_name(r["key"]): "decline" if decline.get(r["key"].split("/", 1)[1]) else "approve"
              for r in level_rows(private)}
    return decide(private, LEVELS, HOT, fields, at=at, subject=workflow.PROGRAMME)


def changes(private, uri):
    """The level changes the decision hook wrote (their basis names the sign-off; the test set-up's do not)."""
    return [(e["payload"]["from"], e["payload"]["to"]) for e in of_kind(private, "level_change", uri)
            if e["actor"] == HOT and e["payload"]["basis"].startswith("signoff ")]


def test_the_levels_workflow_defines_its_steps():
    steps = steps_of("tm:workflow/levels")
    assert {sid: (s["type"], s["role"], s["subject"]) for sid, s in steps.items()} == {
        PROPOSE_LEVELS: ("auto", "head-of-training", "programme"),
        LEVELS: ("human", "head-of-training", "programme"),
    }
    # one approve page with a decision per row, not a batch page (a batch must approve every row)
    assert steps[LEVELS]["page"] == "approve" and steps[LEVELS]["done_when"] == {
        "kind": "signoff", "match": {"step": LEVELS}, "bind": "input", "skippable": True}
    assert LEVELS not in tm_signoff.BATCH_STEPS
    assert flows.AUTO_STEPS[PROPOSE_LEVELS].per == "programme" and flows.AUTO_STEPS[PROPOSE_LEVELS].refresh
    assert LEVELS in flows.PAGE_SPECS and LEVELS in flows.CONTENT_CHECKS and LEVELS in flows.SIGNOFF_HOOKS


def test_without_a_proposal_the_level_decision_is_skipped(fictional_store, ready):
    ready()
    assert level_rows(fictional_store) == []
    assert (LEVELS, workflow.PROGRAMME) not in due_ids(fictional_store)


def test_a_valid_clearance_proposes_cleared_and_the_head_approves_it(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    later = T0 + timedelta(days=3)
    app.do_run(fictional_store, now=later)
    (row,) = level_rows(fictional_store)
    assert row["key"] == INSTRUCTOR and (row["from"], row["to"]) == ("lead-observed", "cleared")
    assert issued(fictional_store)[0]["payload"]["clearance"] in row["summary"]
    assert (LEVELS, workflow.PROGRAMME) in due_ids(fictional_store, later)
    (spec,) = app._page_specs(app.load_state(fictional_store), LEVELS, workflow.PROGRAMME)
    assert spec["template"] == "approve" and [f["name"] for f in spec["fields"]] == ["decide-k7m2q"]
    assert spec["fields"][0]["kind"] == "enum" and spec["fields"][0]["options"] == ["approve", "decline"]
    decide_levels(fictional_store)
    assert app.current_level(app.load_state(fictional_store), INSTRUCTOR) == "cleared"
    (change,) = [e for e in of_kind(fictional_store, "level_change", INSTRUCTOR) if e["payload"]["to"] == "cleared"]
    assert change["actor"] == HOT and change["payload"]["from"] == "lead-observed"
    app.do_run(fictional_store, now=later + timedelta(days=1))
    assert level_rows(fictional_store) == [] and (LEVELS, workflow.PROGRAMME) not in due_ids(fictional_store, later)

    calibrate(fictional_store, INSTRUCTOR, on="2026-11-01")  # a cleared instructor with a clearance passes calibration
    app.do_run(fictional_store, now=later + timedelta(days=5))
    assert moves(fictional_store) == [(INSTRUCTOR, "cleared", "clearer")]
    decide_levels(fictional_store, at="2026-11-04T09:00:00+00:00")
    st = app.load_state(fictional_store)
    assert app.current_level(st, INSTRUCTOR) == "clearer"
    assert "clearer" in {r for i in st.identities["sme.engineer@example.com"] if i["uri"] == INSTRUCTOR for r in i["roles"]}


def test_a_not_yet_clearance_proposes_no_level(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, not_yet())
    decide(fictional_store, D2, C5, not_yet())
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    assert level_rows(fictional_store) == []


def test_clearer_needs_a_valid_clearance_as_well_as_a_calibration(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=(C5, R8), held=())  # P3 stays at the roster's level: cleared
    calibrate(fictional_store, P3)
    app.do_run(fictional_store, now=T0)
    assert level_rows(fictional_store) == []  # holding the level cleared is not evidence of a clearance
    hold(fictional_store, P3)
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert moves(fictional_store) == [(P3, "cleared", "clearer")]


def test_a_lapsed_calibration_proposes_clearer_back_to_cleared(fictional_store, ready):
    ready()  # P3 and C5 passed calibration on 2026-10-01; it lapses six months later. R8 never passed.
    app.do_run(fictional_store, now=T0.replace(year=2027, month=4, day=2))
    assert moves(fictional_store) == [(C5, "clearer", "cleared"), (P3, "clearer", "cleared")]
    assert all("calibration" in r["basis"] for r in level_rows(fictional_store))


def test_no_valid_clearance_left_proposes_cleared_back_to_lead_observed(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=(C5, R8), calibrated=(C5,), held=())
    app.do_run(fictional_store, now=T0)
    assert level_rows(fictional_store) == []  # a roster level with no clearance on record is not demoted
    hold(fictional_store, P3, issued="2025-11-01", expires="2026-11-01")
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert level_rows(fictional_store) == []  # still valid
    app.do_run(fictional_store, now=T0.replace(day=2, month=11))
    assert moves(fictional_store) == [(P3, "cleared", "lead-observed")]


def test_the_head_may_decline_one_row_and_approve_another(fictional_store, ready):
    ready()
    app.do_run(fictional_store, now=T0.replace(year=2027, month=4, day=2))
    assert [k for k, _, _ in moves(fictional_store)] == [C5, P3]
    decide_levels(fictional_store, at="2027-04-02T10:00:00+00:00", p3x9d=True)
    assert changes(fictional_store, C5)[-1] == ("clearer", "cleared") and changes(fictional_store, P3) == []
    assert (LEVELS, workflow.PROGRAMME) not in due_ids(fictional_store, T0.replace(year=2027, month=4, day=2))


def test_every_row_needs_a_decision(fictional_store, ready):
    ready()
    app.do_run(fictional_store, now=T0.replace(year=2027, month=4, day=2))
    doc = document(fictional_store, LEVELS, HOT, {"decide-p3x9d": "approve"}, at="2027-04-02T10:00:00+00:00",
                   subject=workflow.PROGRAMME)
    found = flows.content_reasons(app.load_state(fictional_store), doc)
    assert any("decide-c5w1t" in r for r in found)
    doc = document(fictional_store, LEVELS, HOT, {"decide-p3x9d": "approve", "decide-c5w1t": "maybe"},
                   at="2027-04-02T10:00:00+00:00", subject=workflow.PROGRAMME)
    assert any("decide-c5w1t" in r for r in flows.content_reasons(app.load_state(fictional_store), doc))


def test_an_approved_row_that_is_no_longer_proposed_writes_no_level_change(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    assert moves(fictional_store) == [(INSTRUCTOR, "lead-observed", "cleared")]
    p = issued(fictional_store)[0]["payload"]
    put(fictional_store, events.make_event("clearance", p["candidate"], workflow.SYSTEM_ACTOR, {**p, "outcome": "revoked"},
                                           at="2026-10-29T12:00:00+00:00"))  # revoked before the head signs
    decide_levels(fictional_store)  # the page still shows the row; the hook recomputes
    assert changes(fictional_store, INSTRUCTOR) == []


def test_a_level_row_whose_instructor_moved_meanwhile_writes_no_level_change(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    signed = {"subject_uri": workflow.PROGRAMME, "actor": HOT, "payload": {"signoff_id": "abcdefabcdefabcd"}}
    set_level(fictional_store, INSTRUCTOR, "cleared")
    moved = app.load_state(fictional_store)
    doc = {"fields": {levels.field_name(INSTRUCTOR): "approve"}}
    new, _ = flows.SIGNOFF_HOOKS[LEVELS][0](moved, signed, doc, T0 + timedelta(days=3))
    assert new == []
    assert levels.level_change_id("abcdefabcdefabcd", INSTRUCTOR) != levels.level_change_id("abcdefabcdefabcd", P3)


def test_a_proposal_that_returns_to_an_earlier_one_is_recorded_again(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=(C5, R8), held=())
    calibrate(fictional_store, P3)
    hold(fictional_store, P3)
    app.do_run(fictional_store, now=T0)  # A: P3 to clearer
    first = level_rows(fictional_store)
    hold(fictional_store, P3, outcome="not_yet")  # the same clearance, superseded: B, nothing to propose
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert level_rows(fictional_store) == []
    hold(fictional_store, P3)  # back to A
    app.do_run(fictional_store, now=T0 + timedelta(hours=2))
    assert level_rows(fictional_store) == first
    steps = [e for e in of_kind(fictional_store, "step", workflow.PROGRAMME) if e["payload"].get("step") == PROPOSE_LEVELS]
    data = (fictional_store / "generated" / "levels.json").read_bytes()
    assert len(steps) == 3 and steps[-1]["payload"]["output_sha256"] == hashlib.sha256(data).hexdigest()
    assert (LEVELS, workflow.PROGRAMME) in due_ids(fictional_store, T0 + timedelta(hours=2))
