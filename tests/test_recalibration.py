"""Recalibration (decision 0024): `open-recalibrations` opens a `recalibration` for a clearer, current or moved back to cleared
by a lapse, whose calibration lapses within 30 days; the head's `recalibration-exercise` page opens the exercise on a
recording already on record; the next run closes the recalibration.

Fictional people only (the example roster): A and C are made clearers, B is the SME who is not one.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from clearer_helpers import calibrate, set_level
from test_bench_blocks import decided
from test_calibration import A, B, C, T0, open_exercise

import test_calibration

from teachermodel import app, events, signoff, workflow
from teachermodel.flows import AUTO_STEPS, PAGE_SPECS, calibration

NOW = datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)
HEAD = "tm:person/hot-1"
OPEN, RECAL = calibration.STEP_OPEN_RECAL, calibration.STEP_RECAL
store = test_calibration.store  # the fixture: a fictional store with the example roster imported


@pytest.fixture
def clearers(store):
    set_level(store, A, "clearer")
    set_level(store, C, "clearer")
    calibrate(store, C, at="2026-10-01T08:00:00+00:00")  # C stays calibrated
    return store


def run(store, now=NOW):
    found = AUTO_STEPS[OPEN].run(app.load_state(store), workflow.PROGRAMME, now)
    for e in found:
        events.append(store / app.EVENT_LOG, e)
    return found


def recalibrations(found):
    return [e["payload"]["attrs"]["instructor"] for e in found if e["kind"] == "subject"]


def closed(found):
    return [e["subject_uri"] for e in found if e["kind"] == "check" and e["payload"].get("result") == "closed"]


def test_a_clearer_who_never_passed_or_whose_pass_expired_gets_a_recalibration_and_no_one_else(clearers):
    calibrate(clearers, A, at="2026-01-05T08:00:00+00:00")  # six months on, lapsed in July
    assert recalibrations(run(clearers)) == [A]  # not C (calibrated), not B (not a clearer)


@pytest.mark.parametrize("passed_on, needed", [("2026-05-24", True), ("2026-05-28", False)])
def test_a_renewal_opens_thirty_days_ahead(clearers, passed_on, needed):
    """A pass on 05-24 lapses on 11-24, within 30 days of 10-27; one on 05-28 lapses on 11-28, after them."""
    calibrate(clearers, A, at=f"{passed_on}T08:00:00+00:00")
    assert recalibrations(run(clearers)) == ([A] if needed else [])


def test_a_clearer_moved_back_to_cleared_by_a_lapse_still_gets_one(clearers):
    set_level(clearers, A, "cleared", at="2026-10-20T07:00:00+00:00")  # from clearer: a lapse moved them back
    events.append(clearers / app.EVENT_LOG, events.make_event(
        "level_change", A, HEAD, {"from": "clearer", "to": "cleared", "basis": "test: calibration lapsed"},
        at="2026-10-20T07:00:01+00:00"))
    assert recalibrations(run(clearers)) == [A]


def test_a_clearer_with_a_blocking_bench_decision_gets_none(clearers):
    decided(clearers, A, "return-to-co-teaching", on="2026-10-20")
    assert recalibrations(run(clearers)) == []


def test_an_exercise_awaiting_its_result_stands_in_for_one(clearers, tmp_path):
    open_exercise(clearers, tmp_path, observers=(A, B))
    assert recalibrations(run(clearers)) == []


def test_a_second_run_opens_nothing_new(clearers):
    assert recalibrations(run(clearers)) == [A]
    assert run(clearers) == []


# --- the head's page ----------------------------------------------------------------------------------------------------


def opened_recalibration(store, tmp_path):
    """A's recalibration, with B and C's exercise on record to use the recording of."""
    open_exercise(store, tmp_path, observers=(B, C), now=T0)
    (uri,) = [e["subject_uri"] for e in run(store) if e["kind"] == "subject"]
    return uri


def test_the_page_goes_to_the_head_with_the_recordings_and_the_other_clearers(clearers, tmp_path):
    uri = opened_recalibration(clearers, tmp_path)
    (page,) = PAGE_SPECS[RECAL](app.load_state(clearers), uri)
    assert page["signer"] == HEAD and page["inputs"]["instructor"] == A
    fields = {f["name"]: f for f in page["fields"]}
    (exercise,) = fields["recording"]["options"]
    assert fields["second_observer"]["options"] == [C]
    assert page["inputs"]["recordings"] == [{"exercise": exercise, "unit": "sl:unit/example-agent-loop@1",
                                             "recording_ref": "recordings/fictional-delivery-1.mp4",
                                             "scored_before": False}]


def test_no_recording_on_record_means_no_page(clearers):
    (uri,) = [e["subject_uri"] for e in run(clearers) if e["kind"] == "subject"]
    with pytest.raises(calibration.PageProblem, match="open-exercise"):
        PAGE_SPECS[RECAL](app.load_state(clearers), uri)


def document(st, uri, *, signer=HEAD, **fields):
    (page,) = PAGE_SPECS[RECAL](st, uri)
    chosen = {"recording": page["fields"][0]["options"][0], "second_observer": C, **fields}
    return {"schema": "tm:contract/signoff@1", "id": "e" * 16, "step": RECAL, "subject_uri": uri, "signer": signer,
            "decision": "approve", "input_sha256": signoff.input_sha256(page["inputs"]), "fields": chosen}


@pytest.mark.parametrize("change, reason", [
    ({"signer": "tm:person/coord-1"}, "not the head"),
    ({"second_observer": B}, "second_observer"),
    ({"recording": "tm:exercise/0000000000000000"}, "recording"),
])
def test_the_content_check_refuses_another_signer_or_an_unlisted_choice(clearers, tmp_path, change, reason):
    uri = opened_recalibration(clearers, tmp_path)
    st = app.load_state(clearers)
    signer = change.pop("signer", HEAD)
    assert any(reason in r for r in calibration._recalibration_content(st, document(st, uri, signer=signer, **change)))


def test_approving_opens_the_exercise_on_the_same_reference_and_the_next_run_closes_the_recalibration(clearers, tmp_path):
    uri = opened_recalibration(clearers, tmp_path)
    st = app.load_state(clearers)
    doc = document(st, uri)
    signed = {"subject_uri": uri, "actor": HEAD, "payload": {"signoff_id": doc["id"]}}
    (event,), [(key, reference)] = calibration._open_recalibration_exercise(st, signed, doc, NOW)
    source = st.subjects[doc["fields"]["recording"]]
    assert event["payload"]["attrs"]["observers"] == sorted([A, C])
    assert event["payload"]["attrs"]["recording_ref"] == source["recording_ref"]
    assert reference["scores"] == calibration._reference(st, source, calibration.domain_ids(st.root))
    assert not events.check_event(event)
    events.append(clearers / app.EVENT_LOG, event)
    (clearers / key).write_text(json.dumps(reference), encoding="utf-8")
    assert closed(run(clearers, NOW + timedelta(days=1))) == [uri]
    st = app.load_state(clearers)
    assert workflow.is_closed(uri, st.subjects, st.index)
    assert PAGE_SPECS["tm:step/calibration-score"](st, event["subject_uri"])  # both observers get a scoring page


def test_a_failed_exercise_opens_a_new_recalibration(clearers, tmp_path):
    first = opened_recalibration(clearers, tmp_path)
    open_exercise(clearers, tmp_path, observers=(A, C), now=NOW)  # by the command this time
    assert closed(run(clearers)) == [first]
    (exercise,) = [u for u, i in app.load_state(clearers).subjects.items()
                   if i.get("kind") == "exercise" and A in i["observers"]]
    events.append(clearers / app.EVENT_LOG, events.make_event(
        "step", exercise, workflow.SYSTEM_ACTOR, {"step": calibration.STEP_RESULT, "observers": sorted([A, C]),
                                                  "renewal_months": 6}, at="2026-10-28T09:00:00+00:00"))
    calibrate(clearers, A, at="2026-10-28T09:00:00+00:00", passed=False)
    found = run(clearers, NOW + timedelta(days=2))
    assert recalibrations(found) == [A] and first not in [e["subject_uri"] for e in found]
