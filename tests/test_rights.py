"""Instructor replies and appeals (flows/rights.py, standards/workflows/rights.yaml, decision 0021). Fictional people only."""

from datetime import timedelta

import pytest
from test_clearance import C5, D1, D2, HOT, INSTRUCTOR, P3, T0, cleared, decide, issued, reasons

import test_clearance

from teachermodel import app, flows, signoff
from teachermodel.flows import rights

ready = test_clearance.ready
REPLY, APPEAL = rights.STEP_REPLY, rights.STEP_APPEAL
TEXT = "SECRET-REPLY I was observed on a day the lab failed"
REASON = "SECRET-REASON the lab failure is on record; the decision stands"


@pytest.fixture
def world(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    (event,) = issued(fictional_store)
    return fictional_store, event["id"]


def log(private):
    return app.read_events(private)


def fields(decision, kind="reply", text=TEXT):
    return {"decision": decision, "kind": kind, "text": text}


def test_the_reply_page_lists_the_instructors_decisions(world):
    store, cid = world
    (spec,) = app._page_specs(app.load_state(store), REPLY, INSTRUCTOR)
    assert spec["signer"] == INSTRUCTOR and cid in [d["id"] for d in spec["inputs"]["decisions"]]
    assert spec["inputs"]["replies"] == 0


def test_a_reply_is_a_step_event_with_the_text_kept_private_and_the_page_reopens(world):
    store, cid = world
    decide(store, REPLY, INSTRUCTOR, fields(cid), subject=INSTRUCTOR)
    (reply,) = [e for e in log(store) if e["kind"] == "step" and e["payload"].get("step") == REPLY]
    assert reply["payload"]["decision"] == cid and reply["payload"]["kind"] == "reply"
    assert TEXT not in (store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert TEXT in (store / reply["payload"]["text_key"]).read_text(encoding="utf-8")
    assert not [e for e in log(store) if e["kind"] == "subject" and e["payload"]["subject_kind"] == "appeal"]
    (spec,) = app._page_specs(app.load_state(store), REPLY, INSTRUCTOR)
    assert spec["inputs"]["replies"] == 1  # the page comes back for another one


def test_only_the_instructor_replies_and_only_on_their_own_decisions(world):
    store, cid = world
    assert any("only the instructor" in r for r in reasons(store, REPLY, P3, fields(cid), subject=INSTRUCTOR))
    assert any("decision:" in r for r in reasons(store, REPLY, INSTRUCTOR, fields("not-a-decision"), subject=INSTRUCTOR))
    assert any("kind:" in r for r in reasons(store, REPLY, INSTRUCTOR, fields(cid, kind="complain"), subject=INSTRUCTOR))
    assert any("text:" in r for r in reasons(store, REPLY, INSTRUCTOR, fields(cid, text=" "), subject=INSTRUCTOR))


def _appealed(store, cid):
    decide(store, REPLY, INSTRUCTOR, fields(cid, kind="appeal"), subject=INSTRUCTOR)
    (opened,) = [e for e in log(store) if e["kind"] == "subject" and e["payload"]["subject_kind"] == "appeal"]
    return opened["subject_uri"]


def test_an_appeal_opens_an_appeal_for_the_head_who_decides_it_once(world):
    store, cid = world
    appeal = _appealed(store, cid)
    assert (APPEAL, appeal) in {(d.step, d.subject) for d in app.due_steps(app.load_state(store), T0.date())}
    specs = app._page_specs(app.load_state(store), APPEAL, appeal)
    assert [s["signer"] for s in specs] == [HOT] and specs[0]["inputs"]["decision"]["id"] == cid
    decide(store, APPEAL, HOT, {"outcome": "upheld", "reason": REASON}, subject=appeal)
    (done,) = [e for e in log(store) if e["kind"] == "check" and e["payload"].get("step") == APPEAL]
    assert done["payload"]["result"] == "upheld" and REASON not in (store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert APPEAL in signoff.SINGLE_DECISION_STEPS


def test_the_appeal_needs_the_head_a_known_outcome_and_a_reason(world):
    store, cid = world
    appeal = _appealed(store, cid)
    assert any("not the head" in r for r in reasons(store, APPEAL, P3, {"outcome": "upheld", "reason": "x"}, subject=appeal))
    assert any("outcome:" in r for r in reasons(store, APPEAL, HOT, {"outcome": "quashed", "reason": "x"}, subject=appeal))
    assert any("reason:" in r for r in reasons(store, APPEAL, HOT, {"outcome": "varied", "reason": ""}, subject=appeal))


def test_the_record_view_shows_the_reply_and_the_appeal_outcome(world):
    from teachermodel import views

    store, cid = world
    appeal = _appealed(store, cid)
    decide(store, APPEAL, HOT, {"outcome": "varied", "reason": REASON}, subject=appeal)
    views.build(store)
    html = (store / "views" / "instructors" / f"{INSTRUCTOR.split('/', 1)[1]}.html").read_text(encoding="utf-8")
    section = html[html.index("<h2>Replies and appeals</h2>"):]
    assert "appeal" in section and "varied" in section and cid[:12] in section
    assert TEXT not in html and REASON not in html


def test_the_rights_steps_are_registered():
    assert REPLY in flows.PAGE_SPECS and APPEAL in flows.PAGE_SPECS
    assert REPLY in flows.CONTENT_CHECKS and APPEAL in flows.SIGNOFF_HOOKS
