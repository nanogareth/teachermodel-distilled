"""Integration review finding 11: an ad-hoc assignment does not wait for the candidate's batch to be approved.

The engine reads an optional step key `needs_except_opened_by` ({need step id: [opener step ids]}): a need is waived for a
child subject whose opening `subject` event names one of those openers. Joining a delivery whose assignments are already
released is refused. Fictional people only.
"""

from datetime import timedelta

from test_adhoc_assignment import STEP, adhoc, page_fields, reasons
from test_observation import (
    CANDIDATE, COORD, INSTRUCTOR, K7, R8, STEP_APPROVED, STEP_OBSERVE, STEP_SELF, T0, UNIT, due_ids, observe_fields, of_kind,
    sign, store,
)
from test_standards import _mutate, _step, _temp_root
from test_workflow_children import (
    ALICE, CAND_A, TODAY, assignment, cand, child, doc, ids, reg, step, subjects,
)

from teachermodel import app, events
from teachermodel.workflow import needs_met, next_steps, unmet_needs

ASSIGN_A = "tm:assignment/0123456789abcdef"
ASSIGN_B = "tm:assignment/00000000000000aa"


def test_a_need_is_waived_for_a_child_opened_by_the_named_step():
    d = doc(
        step("approve-batch", "candidate"),
        step("observe", "assignment", needs=["tm:step/approve-batch"],
             needs_except_opened_by={"tm:step/approve-batch": ["tm:step/ad-hoc"]}))
    attrs = assignment(ASSIGN_A, CAND_A, ALICE)["payload"]["attrs"]
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE),
           child(ASSIGN_A, "assignment", attrs, by="tm:step/ad-hoc"),
           child(ASSIGN_B, "assignment", {**attrs, "delivery_ref": "d-2"}, by="tm:step/approve-batch")]
    s = subjects(log)
    due = ids(next_steps(d, log, s, TODAY))
    assert ("tm:step/observe", ASSIGN_A) in due  # opened by the ad-hoc step: the batch approval is not asked of it
    assert ("tm:step/observe", ASSIGN_B) not in due  # opened by the batch step: still needs it
    assert needs_met(d, log, s, "tm:step/observe", ASSIGN_A) and not needs_met(d, log, s, "tm:step/observe", ASSIGN_B)
    assert unmet_needs(d, log, s, "tm:step/observe", ASSIGN_A) == []
    assert unmet_needs(d, log, s, "tm:step/observe", ASSIGN_B) == ["tm:step/approve-batch"]


def test_an_adhoc_assignment_does_not_need_the_candidates_batch_approved(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(R8))
    (mine,) = adhoc(fictional_store)
    uri = mine["subject_uri"]
    due = due_ids(fictional_store)
    assert (STEP_APPROVED, CANDIDATE) in due  # the batch has not been approved
    assert (STEP_OBSERVE, uri) in due and (STEP_SELF, uri) in due  # but the ad-hoc assignment's own steps are open
    sign(fictional_store, STEP_OBSERVE, uri, R8, observe_fields(3, "2026-10-27"))
    app.do_run(fictional_store, now=T0 + timedelta(days=1))
    assert [e for e in of_kind(fictional_store, "observation") if e["payload"].get("assignment") == uri]


def test_an_assignment_opened_by_another_step_still_needs_the_batch(fictional_store, example_roster):
    store(fictional_store, example_roster)
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "subject", "tm:assignment/00000000000000cc", "tm:system/teachermodel",
        {"subject_kind": "assignment", "opened_by": "tm:step/test",
         "attrs": {"candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote", "observer": R8,
                   "length": "full", "lead": True, "delivery_ref": "elsewhere-1"}}, at="2026-10-26T08:30:00+00:00"))
    assert (STEP_OBSERVE, "tm:assignment/00000000000000cc") not in due_ids(fictional_store)


def test_joining_a_delivery_that_has_been_released_is_refused(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7, delivery_ref="shared-2"))
    (mine,) = adhoc(fictional_store)
    assert reasons(fictional_store, page_fields(R8, delivery_ref="shared-2")) == []  # not released yet: the observer may join
    sign(fictional_store, STEP_OBSERVE, mine["subject_uri"], K7, observe_fields(3, "2026-10-27"))
    app.do_run(fictional_store, now=T0 + timedelta(days=1))
    assert of_kind(fictional_store, "observation")
    found = reasons(fictional_store, page_fields(R8, delivery_ref="shared-2"))
    assert any("delivery_ref" in r and "released" in r for r in found), found
    assert reasons(fictional_store, page_fields(R8, delivery_ref="shared-3")) == []


def test_needs_except_opened_by_must_name_a_need_and_known_steps(tmp_path):
    root = _temp_root(tmp_path)

    def good(d):
        _step(d, "observe")["needs_except_opened_by"] = {"tm:step/assignments-approved": ["tm:step/assign-observer"]}

    assert _mutate(root, good, "observation") == []
    errors = _mutate(root, lambda d: _step(d, "observe").update(
        needs_except_opened_by={"tm:step/propose-observations": ["tm:step/assign-observer"]}), "observation")
    assert any("needs_except_opened_by" in e and "not one of its needs" in e for e in errors), errors
    errors = _mutate(root, lambda d: _step(d, "observe").update(
        needs_except_opened_by={"tm:step/assignments-approved": ["tm:step/nonesuch"]}), "observation")
    assert any("needs_except_opened_by" in e and "unknown step" in e for e in errors), errors
