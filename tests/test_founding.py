"""The founding round of W4 (decision 0017, flows/clearance.py `founding`, `within_modules`): while fewer than two calibrated
clearers other than the candidate's instructor hold the candidate's unit, a calibrated clearer who holds no clearance for it
may decide. Nothing else is waived, and the clearance carries `founding: true`.

    other calibrated holders of the unit   0 or 1: founding (any calibrated clearer)   2: the ordinary rule
    a holder who is not calibrated, the candidate's own instructor, a holder under a blocking bench decision: not counted
    a clearer under a blocking bench decision never decides under the waiver

Fictional people only.
"""

from datetime import date, timedelta

from test_bench_blocks import decided
from test_clearance import (
    C5, CAND, D1, D2, K7, P3, R8, T0, UNIT, calibrate, check_staffing, cleared, decide, hold, issued, reasons, signers,
)

import test_clearance

from teachermodel import app, events
from teachermodel.flows import clearance

ready = test_clearance.ready  # the fixture: a store with an open round for the SME's candidate

ALL = (P3, C5, R8)
LATER = "2026-10-28T09:00:00+00:00"


def within(found):
    return any("within their modules" in r for r in found)


def info(private):
    return app.load_state(private).subjects[CAND]


def is_founding(private, on=T0.date()):
    return clearance.founding(app.load_state(private), info(private), on)


def test_a_unit_nobody_holds_opens_a_founding_round_and_marks_the_clearance(fictional_store, ready):
    ready(calibrated=ALL, held=())
    assert is_founding(fictional_store)
    assert signers(fictional_store, D1) == sorted(ALL)
    assert all(reasons(fictional_store, D1, c, cleared()) == [] for c in ALL)
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared(), at=LATER)
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    (event,) = issued(fictional_store)
    assert event["payload"]["founding"] is True and event["payload"]["clearers"] == [P3, C5]
    assert events.check_event(event) == []
    assert check_staffing(fictional_store)["verdict"] == "ok"


def test_one_other_holder_still_leaves_the_round_founding(fictional_store, ready):
    ready(calibrated=ALL, held=(P3,))
    assert is_founding(fictional_store)
    assert signers(fictional_store, D1) == sorted(ALL)
    assert reasons(fictional_store, D1, R8, cleared()) == []


def test_two_other_holders_close_the_waiver(fictional_store, ready):
    ready(calibrated=ALL, held=(P3, C5))
    assert not is_founding(fictional_store)
    assert signers(fictional_store, D1) == sorted([P3, C5])
    assert within(reasons(fictional_store, D1, R8, cleared()))


def test_the_waiver_is_judged_on_the_day_of_signing(fictional_store, ready):
    ready(calibrated=ALL, held=(P3,))
    hold(fictional_store, C5, issued="2026-10-28", expires="2027-10-28")  # C5 holds the unit from the 28th
    assert reasons(fictional_store, D1, R8, cleared()) == []  # the 27th: one holder
    assert within(reasons(fictional_store, D1, R8, cleared(), at=LATER))  # the 28th: two holders


def test_a_holder_who_is_not_calibrated_does_not_count(fictional_store, ready):
    ready(calibrated=ALL, held=(P3, C5))
    calibrate(fictional_store, P3, on="2026-12-01")
    calibrate(fictional_store, R8, on="2026-12-01")  # C5's pass of 2026-10-01 lapses after six months; theirs do not
    lapsed = "2027-04-15T09:00:00+00:00"
    assert not is_founding(fictional_store)
    assert is_founding(fictional_store, on=date(2027, 4, 15))
    assert reasons(fictional_store, D1, R8, cleared(), at=lapsed) == []
    assert any("calibrated" in r for r in reasons(fictional_store, D1, C5, cleared(), at=lapsed))  # still refused


def test_the_candidates_own_instructor_does_not_count_and_still_cannot_decide(fictional_store, ready):
    ready(clearers=(P3, C5, R8, K7), calibrated=(P3, C5, R8, K7), held=(P3, K7))
    assert is_founding(fictional_store)
    assert reasons(fictional_store, D1, R8, cleared()) == []
    assert K7 not in signers(fictional_store, D1)
    assert any("instructor" in r for r in reasons(fictional_store, D1, K7, cleared()))


def test_an_uncalibrated_clearer_cannot_decide_under_the_waiver(fictional_store, ready):
    ready(calibrated=(P3, C5), held=())
    assert is_founding(fictional_store)
    assert R8 not in signers(fictional_store, D1)
    assert any("calibrated" in r for r in reasons(fictional_store, D1, R8, cleared()))


def test_a_clearer_under_a_blocking_bench_decision_never_decides_under_the_waiver(fictional_store, ready):
    ready(calibrated=ALL, held=())
    decided(fictional_store, P3, "exit", on="2026-10-25")
    assert is_founding(fictional_store)
    assert signers(fictional_store, D1) == sorted([C5, R8])
    assert within(reasons(fictional_store, D1, P3, cleared()))


def test_a_bench_decision_that_takes_out_a_holder_reopens_the_waiver(fictional_store, ready):
    ready(calibrated=ALL, held=(P3, C5))
    assert within(reasons(fictional_store, D1, R8, cleared()))
    decided(fictional_store, C5, "exit", on="2026-10-25")
    assert reasons(fictional_store, D1, R8, cleared()) == []


def test_one_founding_decision_is_enough_to_mark_the_clearance(fictional_store, ready):
    ready(calibrated=ALL, held=(P3,))
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, R8, cleared(), at=LATER)
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    (event,) = issued(fictional_store)
    assert event["payload"]["founding"] is True


def test_an_ordinary_round_issues_no_founding_mark(fictional_store, ready):
    ready()
    assert not is_founding(fictional_store)
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared(), at=LATER)
    app.do_run(fictional_store, now=T0 + timedelta(days=3))
    (event,) = issued(fictional_store)
    assert "founding" not in event["payload"]


def test_a_founding_clearance_counts_toward_the_ordinary_rule_for_the_next_candidate(fictional_store, ready):
    ready(calibrated=ALL, held=(P3,))
    st = app.load_state(fictional_store)
    assert clearance.unit_deciders(st, info(fictional_store), T0.date()) == [P3]
    hold(fictional_store, C5)
    st = app.load_state(fictional_store)
    assert clearance.unit_deciders(st, info(fictional_store), T0.date()) == [C5, P3]
    assert not clearance.founding(st, info(fictional_store), T0.date())
    assert UNIT == info(fictional_store)["unit"]


def test_the_decision_pages_go_to_the_clearers_who_may_decide_today_not_on_the_day_the_round_opened(fictional_store, ready):
    """Found by the simulation (2026-10-27): the pool was judged on the round's day, the content check on the signing
    day, so a founding round that closed after the round opened still sent pages to clearers it would refuse."""
    ready(calibrated=ALL, held=(P3,))
    assert signers(fictional_store, D1) == sorted(ALL)  # the 27th: founding, any calibrated clearer
    hold(fictional_store, C5, issued="2026-10-28", expires="2027-10-28")  # an event of the 28th: two holders from today
    assert signers(fictional_store, D1) == sorted([P3, C5])
    assert within(reasons(fictional_store, D1, R8, cleared(), at=LATER))
