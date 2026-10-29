"""The coordinator's ad-hoc observation assignment (standards/workflows/observation.yaml, step assign-observer; increment 3 plan
section J; decision 0015).

A human step on the candidate, beside and independent of the automatic proposals: the coordinator picks an observer from the
calibrated clearers, the length, lead and mode, and optionally the delivery reference; approving it opens one `assignment`
subject through the same opener the batch approval uses. The step reopens after each approval (`bind: input`, with the number of
ad-hoc assignments in its inputs, as log-activity does). Fictional people only.
"""

import json
from datetime import timedelta

import pytest
import yaml
from clearer_helpers import calibrate, set_level
from ingest_helpers import ingest, signoff as make_signoff
from test_observation import (
    C5, CANDIDATE, COORD, INSTRUCTOR, K7, R8, STEP_APPROVED, STEP_OBSERVE, STEP_PROPOSE, STEP_RELEASE, STEP_SELF, T0, UNIT,
    approve_batch, assignments, due_ids, log, observe_fields, of_kind, proposal, sign, store,
)

from teachermodel import app, events, flows
from teachermodel.flows import observation
from teachermodel.standards import ROOT, check_standards, load_standards

STEP = "tm:step/assign-observer"
SLUG = "p3x9d--example-agent-loop-1--remote"


def adhoc(private, candidate=CANDIDATE):
    return [e for e in assignments(private, candidate) if e["payload"]["opened_by"] == STEP]


def page_fields(observer, **over):
    return {"observer": observer, "length": "full", "lead": True, "mode": "remote", **over}


def reasons(private, fields, *, signer=COORD, at="2026-10-27T09:00:00+00:00", subject=CANDIDATE):
    doc = {"id": "abc0123456789abc", "step": STEP, "subject_uri": subject, "decision": "approve", "signer": signer,
           "signed_at": at, "fields": fields}
    return flows.content_reasons(app.load_state(private), doc)


def spec_of(private, candidate=CANDIDATE):
    return app._page_specs(app.load_state(private), STEP, candidate)[0]


# --- the workflow file -------------------------------------------------------------------------------------------


def test_the_workflow_defines_a_separate_repeatable_coordinator_step_on_the_candidate():
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/observation"]
    steps = {s["id"]: s for s in wf["steps"]}
    step = steps[STEP]
    assert (step["type"], step["role"], step["subject"], step["page"]) == ("human", "coordinator", "candidate", "approve")
    assert step["done_when"] == {"kind": "signoff", "match": {"step": STEP}, "bind": "input"}
    assert STEP not in (steps[STEP_PROPOSE]["needs"], steps[STEP_APPROVED]["needs"])  # nothing waits for it
    assert STEP not in {n for s in wf["steps"] for n in s["needs"]}
    assert "due" not in step  # an optional item is never overdue
    assert STEP in flows.PAGE_SPECS and STEP in flows.CONTENT_CHECKS and STEP in flows.SIGNOFF_HOOKS
    assert check_standards(ROOT) == []


# --- the page --------------------------------------------------------------------------------------------------------


def test_the_page_offers_the_eligible_observers_and_both_coordinators_get_it(fictional_store, example_roster):
    store(fictional_store, example_roster)
    specs = app._page_specs(app.load_state(fictional_store), STEP, CANDIDATE)
    assert sorted(s["signer"] for s in specs) == ["tm:person/coord-1", "tm:person/coord-2"]
    assert specs[0]["inputs"] == specs[1]["inputs"] and {s["template"] for s in specs} == {"assign"}
    assert specs[0]["inputs"] == {"candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote",
                                 "ad_hoc_assignments_so_far": 0}
    fields = {f["name"]: f for f in specs[0]["fields"]}
    assert fields["observer"]["options"] == sorted([K7, C5, R8]) and fields["observer"]["required"] is True
    assert fields["length"]["options"] == ["full", "short"] and fields["length"]["value"] == "full"
    assert fields["lead"]["kind"] == "bool" and fields["lead"]["value"] is True
    assert fields["mode"]["options"] == ["in-person", "remote", "hybrid"] and fields["mode"]["value"] == "remote"
    assert fields["delivery_ref"]["kind"] == "text" and fields["delivery_ref"]["required"] is False


def test_the_observer_options_are_the_pool_of_the_proposals_less_the_instructor(fictional_store, example_roster):
    store(fictional_store, example_roster, calibrated=("k7m2q", "c5w1t"))  # r8 is a clearer who is not calibrated
    set_level(fictional_store, INSTRUCTOR, "clearer")
    calibrate(fictional_store, INSTRUCTOR)
    options = {f["name"]: f for f in spec_of(fictional_store)["fields"]}["observer"]["options"]
    assert options == sorted([K7, C5])  # not R8 (uncalibrated), not the instructor (a calibrated clearer, but the one observed)


def test_the_page_page_renders_for_the_coordinator(fictional_store, example_roster):
    from teachermodel import pages as pagegen

    store(fictional_store, example_roster)
    page, _ = pagegen.render(**spec_of(fictional_store), channel={"kind": "mail", "to": "signoffs@example.com"})
    assert "observer" in page and "delivery_ref" in page


# --- approval opens an assignment through the W2 opener --------------------------------------------------------------


def test_approval_opens_one_assignment_with_a_generated_delivery_reference(fictional_store, example_roster):
    store(fictional_store, example_roster)
    signed = sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7))
    ref = f"{SLUG}-adhoc-{signed['payload']['signoff_id'][:8]}"  # derived from the sign-off, so a replay opens the same one
    (e,) = adhoc(fictional_store)
    assert e["actor"] == COORD and e["payload"]["subject_kind"] == "assignment" and events.check_event(e) == []
    assert e["payload"]["attrs"] == {"candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote",
                                     "observer": K7, "length": "full", "lead": True, "delivery_ref": ref}
    assert e["subject_uri"] == observation.assignment_uri(CANDIDATE, K7, ref)
    assert e["id"] == flows.pathway.subject_event_id(e["subject_uri"])


def test_a_given_delivery_reference_is_used_and_the_other_answers_pass_through(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sign(fictional_store, STEP, CANDIDATE, COORD,
         page_fields(C5, length="short", lead=False, mode="hybrid", delivery_ref="cohort-7-day-2"))
    (e,) = adhoc(fictional_store)
    assert e["payload"]["attrs"] | {} == {"candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "mode": "hybrid",
                                          "observer": C5, "length": "short", "lead": False, "delivery_ref": "cohort-7-day-2"}


def test_a_blank_delivery_reference_is_generated(fictional_store, example_roster):
    store(fictional_store, example_roster)
    signed = sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7, delivery_ref="  "))
    assert adhoc(fictional_store)[0]["payload"]["attrs"]["delivery_ref"] == f"{SLUG}-adhoc-{signed['payload']['signoff_id'][:8]}"


def test_the_step_reopens_after_each_approval_and_each_generated_reference_is_new(fictional_store, example_roster):
    store(fictional_store, example_roster)
    assert (STEP, CANDIDATE) in due_ids(fictional_store)
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7))
    assert (STEP, CANDIDATE) in due_ids(fictional_store)  # open again: bind: input with the count in its inputs
    assert spec_of(fictional_store)["inputs"]["ad_hoc_assignments_so_far"] == 1
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(C5), at="2026-10-27T10:00:00+00:00")
    refs = [e["payload"]["attrs"]["delivery_ref"] for e in adhoc(fictional_store)]
    assert len(set(refs)) == 2 and all(r.startswith(f"{SLUG}-adhoc-") for r in refs)
    assert (STEP, CANDIDATE) in due_ids(fictional_store) and spec_of(fictional_store)["inputs"]["ad_hoc_assignments_so_far"] == 2


def test_replaying_an_approval_opens_nothing_twice(fictional_store, example_roster):
    store(fictional_store, example_roster)
    event = sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7))
    st = app.load_state(fictional_store)
    document = json.loads((fictional_store / "signoffs" / f"{event['payload']['signoff_id']}.json").read_text("utf-8"))
    again, _ = observation._open_adhoc(st, event, document, T0)
    assert [e["id"] for e in again] == [e["id"] for e in adhoc(fictional_store)]
    app.append_new(fictional_store, again)
    assert len(adhoc(fictional_store)) == 1


# --- it does not touch the automatic proposals -----------------------------------------------------------------------


def test_it_does_not_block_the_proposals_or_the_batch_approval(fictional_store, example_roster):
    store(fictional_store, example_roster)
    rows_before = [r["key"] for r in proposal(fictional_store)["rows"]]
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7))
    assert (STEP_APPROVED, CANDIDATE) in due_ids(fictional_store)  # the batch is still waiting for approval
    app.do_run(fictional_store, now=T0 + timedelta(days=1))
    assert [r["key"] for r in proposal(fictional_store)["rows"]] == rows_before  # the proposal did not change
    approve_batch(fictional_store)
    batch = [e for e in assignments(fictional_store) if e["payload"]["opened_by"] == STEP_APPROVED]
    assert sorted(e["subject_uri"] for e in batch) == sorted(rows_before)
    assert len(adhoc(fictional_store)) == 1 and (STEP_APPROVED, CANDIDATE) not in due_ids(fictional_store)


def test_the_batch_approval_does_not_close_the_adhoc_step(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)
    assert (STEP, CANDIDATE) in due_ids(fictional_store)


# --- the content check -----------------------------------------------------------------------------------------------


def test_a_valid_answer_has_no_reasons(fictional_store, example_roster):
    store(fictional_store, example_roster)
    assert reasons(fictional_store, page_fields(K7)) == []
    assert reasons(fictional_store, page_fields(K7, delivery_ref="cohort-7-day-2")) == []


@pytest.mark.parametrize("bad,field", [
    ({"observer": "tm:instructor/nobody"}, "observer"),
    ({"observer": INSTRUCTOR}, "observer"),
    ({"observer": 7}, "observer"),
    ({"length": "medium"}, "length"),
    ({"lead": "yes"}, "lead"),
    ({"mode": "satellite"}, "mode"),
    ({"delivery_ref": "has a space"}, "delivery_ref"),
    ({"delivery_ref": 5}, "delivery_ref"),
])
def test_an_answer_outside_the_page_is_refused_naming_the_field(fictional_store, example_roster, bad, field):
    store(fictional_store, example_roster)
    found = reasons(fictional_store, {**page_fields(K7), **bad})
    assert found and any(field in r for r in found), found


def test_the_observer_must_be_calibrated_on_the_day_of_signing(fictional_store, example_roster):
    store(fictional_store, example_roster)
    assert reasons(fictional_store, page_fields(K7), at="2027-02-28T09:00:00+00:00") == []
    found = reasons(fictional_store, page_fields(K7), at="2027-03-01T09:00:00+00:00")  # the 2026-09-01 pass has lapsed
    assert any("observer" in r and "calibrated" in r for r in found), found


def test_an_uncalibrated_clearer_is_refused(fictional_store, example_roster):
    store(fictional_store, example_roster, calibrated=("k7m2q", "c5w1t"))
    assert any("observer" in r for r in reasons(fictional_store, page_fields(R8)))


def test_a_signer_other_than_a_coordinator_is_not_offered_the_page_and_the_subject_must_be_a_candidate(fictional_store, example_roster):
    store(fictional_store, example_roster)
    assert any("candidate" in r for r in reasons(fictional_store, page_fields(K7), subject=INSTRUCTOR))
    assert any("coordinator" in r for r in reasons(fictional_store, page_fields(K7), signer="tm:person/hot-1"))


def test_the_coach_limit_applies_to_the_observers_of_one_delivery(fictional_store, example_roster):
    # K7 and C5 are both coaches of the instructor; at most one coach may observe one delivery (rules.clearance.max_coach_observers)
    store(fictional_store, example_roster, coaches=("k7m2q", "c5w1t"), coaches_of=(INSTRUCTOR,))
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7, delivery_ref="shared-1"))
    found = reasons(fictional_store, page_fields(C5, delivery_ref="shared-1"))
    assert any("coach" in r for r in found), found
    assert reasons(fictional_store, page_fields(R8, delivery_ref="shared-1")) == []  # a non-coach may join the delivery
    assert reasons(fictional_store, page_fields(C5, delivery_ref="other-1")) == []  # a coach on another delivery may too


def test_a_coach_of_someone_else_is_an_ordinary_observer_here(fictional_store, example_roster):
    store(fictional_store, example_roster, coaches=("k7m2q", "c5w1t"), coaches_of=(R8,))
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7, delivery_ref="shared-1"))
    assert reasons(fictional_store, page_fields(C5, delivery_ref="shared-1")) == []


def test_an_observer_cannot_be_assigned_twice_to_one_delivery(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7, delivery_ref="shared-1"))
    assert any("observer" in r and "already" in r for r in reasons(fictional_store, page_fields(K7, delivery_ref="shared-1")))


def test_a_delivery_reference_in_use_for_another_candidate_is_refused(fictional_store, example_roster):
    store(fictional_store, example_roster)
    other = "tm:candidate/k7m2q--example-agent-loop-1--in-person"
    events.append(fictional_store / app.EVENT_LOG, events.make_event(
        "subject", "tm:assignment/00000000000000bb", "tm:system/teachermodel",
        {"subject_kind": "assignment", "opened_by": "tm:step/test",
         "attrs": {"candidate": other, "instructor": K7, "unit": UNIT, "mode": "in-person", "observer": C5, "length": "full",
                   "lead": True, "delivery_ref": "taken-1"}}, at="2026-10-26T08:30:00+00:00"))
    found = reasons(fictional_store, page_fields(R8, delivery_ref="taken-1"))
    assert any("delivery_ref" in r for r in found), found


# --- it is an ordinary assignment from then on ---------------------------------------------------------------------


def test_the_assigned_observer_observes_and_the_observation_is_released(fictional_store, example_roster):
    store(fictional_store, example_roster)
    approve_batch(fictional_store)  # the observation steps of an assignment need the candidate's batch to be approved
    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(R8))
    (mine,) = adhoc(fictional_store)
    uri = mine["subject_uri"]
    assert (STEP_OBSERVE, uri) in due_ids(fictional_store) and (STEP_SELF, uri) in due_ids(fictional_store)
    sign(fictional_store, STEP_OBSERVE, uri, R8, observe_fields(3, "2026-10-27"))
    app.do_run(fictional_store, now=T0 + timedelta(days=1))
    released = [e for e in of_kind(fictional_store, "observation") if e["payload"].get("assignment") == uri]
    assert len(released) == 1 and released[0]["payload"]["observer"] == R8
    assert released[0]["payload"]["delivery_ref"] == mine["payload"]["attrs"]["delivery_ref"]
    assert (STEP_RELEASE, uri) not in due_ids(fictional_store)


# --- the real mail round trip ----------------------------------------------------------------------------------------


def test_the_coordinator_signs_through_the_real_mail_round_trip(fictional_store, example_roster):
    store(fictional_store, example_roster)
    app.do_tick(fictional_store, now=T0)
    doc = make_signoff(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7), now=T0)
    rep = ingest(fictional_store, [doc], now=T0, name="adhoc")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    assert len(adhoc(fictional_store)) == 1


def test_a_refused_answer_is_rejected_by_ingest_and_opens_nothing(fictional_store, example_roster):
    store(fictional_store, example_roster)
    app.do_tick(fictional_store, now=T0)
    doc = make_signoff(fictional_store, STEP, CANDIDATE, COORD, page_fields(INSTRUCTOR), now=T0)
    rep = ingest(fictional_store, [doc], now=T0, name="adhoc")
    assert "1 rejected" in rep.summary and adhoc(fictional_store) == []


def test_the_page_offers_one_decision_assign_this_observer(fictional_store, example_roster):
    from teachermodel import pages

    store(fictional_store, example_roster)
    st = app.load_state(fictional_store)
    html, _ = pages.render(**spec_of(fictional_store), channel={"kind": "mail", "to": st.settings["mailbox"]}, root=st.root)
    assert '<option value="approve">Assign this observer</option>' in html
    assert 'value="changes"' not in html and 'value="reject"' not in html
    assert "Ad hoc assignments so far" in html
