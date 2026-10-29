"""A blocking bench decision (exit, return to co-teaching) beyond the staffing check (decision 0015, amended 2026-10-25 for
integration review findings 3 and 4): `records.bench_blocks` and who it takes out of the pools and steps.

    observer pool, second observers, clearers   an instructor with a blocking decision is out until cleared again
    propose-observations, open-cycles,          an exited instructor gets nothing new (one returned to co-teaching
    quality-review, open-candidates             is still coached and observed)
    clearance evidence                          only observations dated after the decision count, and an open round is
                                                superseded by the next one

Fictional people only.
"""

from datetime import datetime, timezone

import pytest

from conftest import EXAMPLE_ROSTER_PATH, make_fictional_store  # noqa: F401
from clearer_helpers import set_level
from privacy_helpers import import_roster_ungated
from test_clearance import (
    C5, CAND, D1, EVIDENCE, K7, P3, T0, UNIT, add_coaches, cleared, document, hold, log, observe, of_kind, put, reasons, rounds,
    signers,
    store,
)

import test_clearance

from teachermodel import app, events, flows, workflow
from teachermodel.flows import AUTO_STEPS, common, quality
from teachermodel.flows.common import PageProblem
from teachermodel.records import bench_blocks

ready = test_clearance.ready  # the fixture: a store with an open round for the SME's candidate
HOT = "tm:person/hot-1"
DAY = T0.date()


def decided(private, instructor, decision, *, on="2026-10-26", n=1):
    """A bench review of `instructor` and its decision on `on`, written straight into the log (no hook runs)."""
    slug = instructor.split("/", 1)[1]
    uri = f"tm:bench/{slug}--{n}"
    put(private, events.make_event(
        "subject", uri, workflow.SYSTEM_ACTOR,
        {"subject_kind": "bench", "attrs": {"instructor": instructor, "reason": "requested"}, "opened_by": "tm:cli/request-bench"},
        id=f"blocks-open-{slug}-{n}", at="2026-10-21T09:00:00+00:00"))
    put(private, events.make_event(
        "bench_decision", uri, HOT,
        {"bench": uri, "instructor": instructor, "decision": decision, "rationale_key": f"bench/{slug}-{n}.json",
         "evidence_pack_sha256": "ab" * 32, "decided_by": HOT, "signoff_id": "cd" * 8},
        id=f"blocks-decision-{slug}-{n}", at=f"{on}T09:00:00+00:00"))


def pool(private, on=DAY):
    return common.observer_pool(app.load_state(private), on)


# --- the pools ------------------------------------------------------------------------------------------------------------


def test_an_exited_clearer_leaves_the_observer_pool_until_cleared_again(ready):
    private = ready()
    assert P3 in pool(private) and C5 in pool(private)
    decided(private, P3, "exit", on="2026-10-25")
    assert P3 not in pool(private) and C5 in pool(private)
    assert P3 in pool(private, on=T0.date().replace(day=24))  # the day before the decision
    hold(private, P3, unit="sl:unit/example-other@1", issued="2026-10-27", expires="2027-10-27")
    assert P3 in pool(private, on=T0.date().replace(day=28))  # a clearance issued after the exit ends it


def test_a_clearer_returned_to_co_teaching_leaves_the_pool_too(ready):
    private = ready()
    decided(private, C5, "return-to-co-teaching", on="2026-10-25")
    assert C5 not in pool(private) and P3 in pool(private)


def test_a_renew_does_not_take_a_clearer_out_of_the_pool(ready):
    private = ready()
    decided(private, P3, "renew", on="2026-10-25")
    assert P3 in pool(private)


def test_an_exited_clearer_cannot_decide_a_clearance(ready):
    private = ready()
    assert signers(private, D1) == [C5, P3]
    decided(private, P3, "exit", on="2026-10-25")
    assert signers(private, D1) == [C5]
    assert any("holds no valid clearance" in r for r in reasons(private, D1, P3, cleared()))
    assert reasons(private, D1, C5, cleared()) == []


# --- the steps of an exited instructor -------------------------------------------------------------------------------------


def _store(base):
    private = make_fictional_store(base)
    roster = base / "roster-in.yaml"
    roster.write_text(EXAMPLE_ROSTER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    return private, roster


def test_open_candidates_opens_nothing_for_an_exited_instructor(tmp_path):
    private, roster = _store(tmp_path)
    import_roster_ungated(private, roster, T0)
    set_level(private, K7, "lead-observed")
    decided(private, K7, "exit", on="2026-10-25")
    app.do_run(private, now=T0)
    assert not [e for e in of_kind(private, "subject") if e["payload"]["subject_kind"] == "candidate"
                and e["payload"]["attrs"]["instructor"] == K7]


def test_propose_observations_proposes_nothing_for_an_exited_instructor(tmp_path):
    private, roster = _store(tmp_path)
    store(private, roster)
    put(private, events.make_event(
        "subject", CAND, workflow.SYSTEM_ACTOR,
        {"subject_kind": "candidate", "attrs": {"instructor": K7, "unit": UNIT, "mode": "in-person"},
         "opened_by": "tm:step/open-candidates"}, at="2026-10-25T09:00:00+00:00"))
    run = AUTO_STEPS["tm:step/propose-observations"].run
    assert run(app.load_state(private), CAND, T0)  # the control: a batch is proposed
    decided(private, K7, "exit", on="2026-10-25")
    assert run(app.load_state(private), CAND, T0) == []


def _low_outcomes(private, instructor=K7):
    for n, day in enumerate(("2026-10-05", "2026-10-12")):
        ref = f"low-{n}"
        put(private, events.make_event(
            "outcome", instructor, workflow.SYSTEM_ACTOR,
            {"delivery_ref": ref, "instructor": instructor, "unit": UNIT, "mode": "in-person", "delivered_on": day,
             "learners_assessed": 40, "score": 60.0, "baseline": 80.0, "source": "tm:test/blocks"},
            id=quality.outcome_id(ref), at=f"{day}T18:00:00+00:00"))


def _triggers(found):
    return [e for e in found if e["kind"] == "check" and e["payload"].get("result") == "trigger"]


def test_quality_review_raises_no_trigger_for_an_exited_instructor(ready):
    private = ready()
    _low_outcomes(private)
    run = AUTO_STEPS[quality.STEP_REVIEW].run
    assert _triggers(run(app.load_state(private), K7, T0))  # the control: two deliveries 20 below the baseline
    decided(private, K7, "exit", on="2026-10-25")
    assert _triggers(run(app.load_state(private), K7, T0)) == []


def test_open_cycles_leaves_an_exited_instructor_alone(ready):
    private = ready()
    run = AUTO_STEPS["tm:step/open-cycles"].run

    def about_k7(found):
        return [e for e in found if e["subject_uri"] == K7 or e["payload"].get("attrs", {}).get("instructor") == K7]

    add_coaches(private, "p3x9d")  # P3 coaches K7, so the next cycle can open
    assert about_k7(run(app.load_state(private), workflow.PROGRAMME, T0))  # the control: a cycle opens for K7
    decided(private, K7, "exit", on="2026-10-25")
    assert about_k7(run(app.load_state(private), workflow.PROGRAMME, T0)) == []


def test_a_returned_instructor_is_still_coached_at_co_deliver_and_a_later_trigger_opens_triggered_coaching(ready):
    """Decision 0015: one returned to co-teaching is still coached. The return lowers the level to co-deliver, below the
    coaching floor; the bench decision keeps them in (a dev-simulate store left a trigger that no cycle could action)."""
    private = ready()
    run = AUTO_STEPS["tm:step/open-cycles"].run

    def opened_for_k7(found):
        return [e for e in found if e["kind"] == "coaching_cycle" and e["payload"].get("instructor") == K7]

    add_coaches(private, "p3x9d")
    set_level(private, K7, "co-deliver", at="2026-10-25T09:00:00+00:00")
    assert opened_for_k7(run(app.load_state(private), workflow.PROGRAMME, T0)) == []  # the control: below the floor
    decided(private, K7, "return-to-co-teaching", on="2026-10-25")
    _low_outcomes(private)
    for e in AUTO_STEPS[quality.STEP_REVIEW].run(app.load_state(private), K7, T0):
        put(private, e)
    found = opened_for_k7(run(app.load_state(private), workflow.PROGRAMME, T0))
    assert [e["payload"]["intensity"] for e in found] == ["triggered"]


def test_a_returned_instructor_is_still_reviewed_for_quality(ready):
    private = ready()
    _low_outcomes(private)
    decided(private, K7, "return-to-co-teaching", on="2026-10-25")
    assert _triggers(AUTO_STEPS[quality.STEP_REVIEW].run(app.load_state(private), K7, T0))


# --- the clearance evidence after a blocking decision (finding 4) ----------------------------------------------------------


def test_after_a_blocking_decision_only_later_observations_count_and_the_open_round_is_superseded(ready):
    private = ready()
    (first,) = rounds(private)
    assert reasons(private, D1, P3, cleared()) == []
    earlier = document(private, D1, P3, cleared())
    decided(private, K7, "return-to-co-teaching", on="2026-10-26")
    st = app.load_state(private)
    assert bench_blocks.latest_blocking(st.events, K7, DAY)["decision"] == "return-to-co-teaching"
    assert any("no longer meets" in r for r in flows.content_reasons(st, earlier))  # the open round is superseded
    with pytest.raises(PageProblem, match="no longer meets"):  # and offers no decision page
        app._page_specs(st, D1, CAND)
    app.do_run(private, now=datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc))
    (blocked,) = [e["payload"]["reasons"] for e in of_kind(private, "check", CAND) if e["payload"].get("step") == EVIDENCE]
    assert any("0 calibrated observations" in r for r in blocked)
    observe(private, P3, day="2026-10-28")
    observe(private, C5, day="2026-10-28")
    app.do_run(private, now=datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc))
    latest = rounds(private)[-1]["payload"]
    assert len(rounds(private)) == 2 and latest["since"] == "2026-10-26"
    old = set(first["payload"]["observations"])
    assert latest["observations"] and not old & set(latest["observations"])


def test_observations_on_the_day_of_the_decision_do_not_count(ready):
    private = ready()
    decided(private, K7, "exit", on="2026-10-28")
    observe(private, P3, day="2026-10-28")
    observe(private, C5, day="2026-10-28")
    app.do_run(private, now=datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc))
    assert len(rounds(private)) == 1
    assert len(log(private)) > 0
