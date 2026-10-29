"""Integration review findings 10 and 18: the coaching cadence and the re-observation date.

10. A cycle is always open for an active instructor at lead-observed or above: the next opens when the previous closes (no wait
    for `rules.coaching_overdue`), with due dates that finish it inside its period (91 days standard, 30 triggered, from
    the day it opened). A quality trigger that arrives while a standard cycle is open switches it to triggered: a
    `coaching_cycle` event of the cycle's current phase carries the new intensity and focus. A cycle that is overdue shows overdue
    in `next`; once it has run past the standard period it no longer holds back the next cycle.
18. The re-observation's session date is not before the first observation's, nor before the day the practice task was set.
Fictional people only.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from test_coaching import doc_for
from test_coaching_support import (
    BASIC,
    K7,
    LF,
    P3,
    PK,
    RI,
    STEP_CLOSE,
    STEP_FEEDBACK,
    STEP_OBSERVE,
    STEP_PRACTICE,
    STEP_REOBSERVE,
    T0,
    add_trigger,
    cycle_uri,
    cycles_opened,
    drive_cycle,
    due_ids,
    feedback_fields,
    log,
    observe_cycle_fields,
    phase_events,
    practice_fields,
    world,
)
from test_observation import of_kind, sign

from teachermodel import app, flows

CYCLE = cycle_uri(P3)
CYCLE2 = cycle_uri(P3, 2)
OPENED = T0.date()  # BASIC opens cycle 1 at the first run


def dues(store, cycle=CYCLE, today=T0.date()):
    return {d.step: d for d in app.due_steps(app.load_state(store), today) if d.subject == cycle}


def intensity(store, cycle=CYCLE):
    return app.load_state(store).subjects[cycle]["intensity"]


def walk(store, cycle=CYCLE, *, session="2026-10-27", at="2026-10-28T09:00:00+00:00", reobserve="2026-11-10"):
    """Sign the four coach steps in order; returns {step: due date} as each one opens."""
    st = app.load_state(store)
    coach, focus = st.subjects[cycle]["coach"], st.subjects[cycle]["focus"]
    seen = {}
    plan = [
        (STEP_OBSERVE, observe_cycle_fields(3, session), at),
        (STEP_FEEDBACK, feedback_fields(focus), "2026-10-29T09:00:00+00:00"),
        (STEP_PRACTICE, practice_fields(focus), "2026-10-30T09:00:00+00:00"),
        (STEP_REOBSERVE, observe_cycle_fields(3, reobserve), "2026-11-11T09:00:00+00:00"),
    ]
    for step, fields, signed in plan:
        seen[step] = dues(store, cycle)[step].due
        sign(store, step, cycle, coach, fields, at=signed)
    seen[STEP_CLOSE] = dues(store, cycle)[STEP_CLOSE].due
    return seen


# --- the next cycle opens when the previous closes -----------------------------------------------------------------


def test_the_next_cycle_opens_at_the_close_not_a_period_later(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    assert [e["subject_uri"] for e in cycles_opened(store)] == [CYCLE]
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 2})
    assert [e["subject_uri"] for e in cycles_opened(store)] == [CYCLE, CYCLE2]
    (closed,) = phase_events(store, "closed", CYCLE)
    (opening,) = [e for e in cycles_opened(store) if e["subject_uri"] == CYCLE2]
    assert opening["at"][:10] == closed["at"][:10] == "2026-11-23"  # the day the previous one closed
    assert opening["payload"]["attrs"]["number"] == 2 and opening["payload"]["attrs"]["coach"] == K7
    assert (STEP_OBSERVE, CYCLE2) in due_ids(store, datetime(2026, 11, 23, tzinfo=timezone.utc).replace(hour=9))
    before = log(store)
    app.do_run(store, now=datetime(2026, 11, 24, 8, tzinfo=timezone.utc))
    assert log(store) == before  # one open cycle at a time: nothing more opens


def test_an_instructor_is_never_without_an_open_cycle(fictional_store, example_roster):
    ops = (*BASIC, ("cycle", P3, 1, "2026-01-01", "2026-02-01", K7, (LF,), "standard"))
    store = world(fictional_store, example_roster, ops)  # closed 267 days before: the next opens at once
    assert [e["subject_uri"] for e in cycles_opened(store) if e["payload"]["opened_by"] == flows.coaching.STEP_OPEN] == [CYCLE2]


def test_a_cycle_closed_today_is_followed_today(fictional_store, example_roster):
    closed = T0.date().isoformat()
    store = world(fictional_store, example_roster,
                  (*BASIC, ("cycle", P3, 1, (T0.date() - timedelta(days=30)).isoformat(), closed, K7, (LF,), "standard")))
    assert CYCLE2 in {e["subject_uri"] for e in cycles_opened(store)}


def test_a_trigger_from_before_the_last_cycle_opened_does_not_intensify_the_next(fictional_store, example_roster):
    ops = (*BASIC, ("trigger", P3, "tr-old", PK),
           ("cycle", P3, 1, "2026-09-01", "2026-09-30", K7, (LF,), "standard"))  # the trigger precedes the cycle in the log
    store = world(fictional_store, example_roster, ops)
    assert intensity(store, CYCLE2) == "standard"


def test_a_trigger_since_the_last_cycle_opened_makes_the_next_one_triggered_on_the_trigger_domain(fictional_store, example_roster):
    ops = (*BASIC, ("cycle", P3, 1, "2026-09-01", "2026-09-30", K7, (LF,), "standard"), ("trigger", P3, "tr-17", PK))
    store = world(fictional_store, example_roster, ops)
    (found,) = [e for e in cycles_opened(store) if e["subject_uri"] == CYCLE2]
    attrs = found["payload"]["attrs"]
    assert attrs["intensity"] == "triggered" and attrs["trigger"] == "tr-17" and attrs["focus"] == [PK]


# --- due dates inside the period ----------------------------------------------------------------------------------


def test_a_standard_cycle_is_due_to_finish_within_91_days_of_opening(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    seen = walk(store)
    day = lambda n: OPENED + timedelta(days=n)  # noqa: E731
    assert seen[STEP_OBSERVE] == day(23)                      # a quarter of the period
    assert seen[STEP_FEEDBACK] == date(2026, 11, 3)           # five working days after the session of 2026-10-27
    assert seen[STEP_PRACTICE] == day(55) and seen[STEP_REOBSERVE] == day(82)
    assert seen[STEP_CLOSE] == day(91)
    assert max(seen.values()) <= day(91)


def test_a_triggered_cycle_is_due_to_finish_within_30_days_of_opening(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (*BASIC, ("trigger", P3, "tr-17", PK)))
    assert intensity(store) == "triggered"
    seen = walk(store, reobserve="2026-11-10")
    day = lambda n: OPENED + timedelta(days=n)  # noqa: E731
    assert seen[STEP_OBSERVE] == day(8) and seen[STEP_PRACTICE] == day(18) and seen[STEP_REOBSERVE] == day(27)
    assert seen[STEP_CLOSE] == day(30) and max(seen.values()) <= day(30)


def test_an_overdue_cycle_step_shows_overdue_in_next(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    assert dues(store, today=OPENED + timedelta(days=23))[STEP_OBSERVE].overdue is False
    assert dues(store, today=OPENED + timedelta(days=24))[STEP_OBSERVE].overdue is True
    queue = app.queue_document(app.due_steps(app.load_state(store), OPENED + timedelta(days=24)), T0)
    item = [i for i in queue["items"] if i["subject"] == CYCLE and i["step"] == STEP_OBSERVE][0]
    assert item["overdue"] is True


# --- a trigger during an open standard cycle ---------------------------------------------------------------------


def test_a_trigger_during_a_standard_cycle_switches_it_to_triggered(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    assert intensity(store) == "standard"
    add_trigger(store, P3, "tr-9", RI, at="2026-10-30T07:00:00+00:00")
    app.do_run(store, now=T0 + timedelta(days=5))
    phases = phase_events(store, cycle=CYCLE)
    assert [e["payload"]["phase"] for e in phases] == ["opened", "opened"]
    switch = phases[-1]["payload"]
    assert (switch["intensity"], switch["focus"]) == ("triggered", [RI])
    assert phases[-1]["at"][:10] == (T0 + timedelta(days=5)).date().isoformat()
    st = app.load_state(store)
    assert st.subjects[CYCLE]["intensity"] == "triggered" and st.subjects[CYCLE]["focus"] == [RI]
    assert st.subjects[CYCLE]["period_days"] == 30
    assert dues(store)[STEP_OBSERVE].due == OPENED + timedelta(days=8)  # the 30-day plan, from the day it opened
    before = log(store)
    app.do_run(store, now=T0 + timedelta(days=6))
    assert log(store) == before  # the trigger is consumed: running again changes nothing


def test_the_switch_event_carries_the_phase_the_cycle_is_in(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-27"), at="2026-10-28T09:00:00+00:00")
    sign(store, STEP_FEEDBACK, CYCLE, K7, feedback_fields([LF, PK]), at="2026-10-29T09:00:00+00:00")
    add_trigger(store, P3, "tr-9", None, at="2026-10-30T07:00:00+00:00")
    app.do_run(store, now=T0 + timedelta(days=5))
    last = phase_events(store, cycle=CYCLE)[-1]["payload"]
    assert (last["phase"], last["intensity"], last["focus"]) == ("feedback", "triggered", [LF, PK])  # no domain: two lowest


def test_a_trigger_does_not_switch_a_cycle_that_is_already_triggered_and_the_next_cycle_takes_it(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (*BASIC, ("trigger", P3, "tr-17", PK)))
    assert intensity(store) == "triggered"
    add_trigger(store, P3, "tr-18", RI, at="2026-10-30T07:00:00+00:00")
    app.do_run(store, now=T0 + timedelta(days=5))
    assert len(phase_events(store, cycle=CYCLE)) == 1  # nothing written for the cycle
    drive_cycle(store, CYCLE, first={PK: 2}, second={PK: 3})
    assert intensity(store, CYCLE2) == "triggered"  # the second trigger was not used by the first cycle


def test_a_trigger_the_switch_used_does_not_make_the_next_cycle_triggered(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    add_trigger(store, P3, "tr-9", RI, at="2026-10-30T07:00:00+00:00")
    app.do_run(store, now=T0 + timedelta(days=5))
    drive_cycle(store, CYCLE, first={RI: 2}, second={RI: 3})
    assert CYCLE2 in {e["subject_uri"] for e in cycles_opened(store)}
    assert intensity(store, CYCLE2) == "standard"


def test_the_phase_events_after_a_switch_carry_the_new_intensity_and_focus(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    add_trigger(store, P3, "tr-9", RI, at="2026-10-30T07:00:00+00:00")
    app.do_run(store, now=T0 + timedelta(days=5))
    drive_cycle(store, CYCLE, first={RI: 2}, second={RI: 3})
    closed = phase_events(store, "closed", CYCLE)[0]["payload"]
    assert (closed["intensity"], closed["focus"], closed["change"]) == ("triggered", [RI], {RI: 1})


# --- a stalled cycle ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("days_ago,next_opens", [(91, False), (92, True)])
def test_a_cycle_that_has_run_past_the_standard_period_no_longer_holds_back_the_next(fictional_store, example_roster, days_ago, next_opens):
    opened = (T0.date() - timedelta(days=days_ago)).isoformat()
    store = world(fictional_store, example_roster, (*BASIC, ("cycle", P3, 1, opened, None, K7, (LF,), "standard")))
    assert (CYCLE2 in {e["subject_uri"] for e in cycles_opened(store)}) is next_opens
    # the stalled cycle itself is still open and overdue in next
    assert dues(store)[STEP_OBSERVE].overdue is True


def test_a_stalled_cycle_is_not_replaced_more_than_once_a_period(fictional_store, example_roster):
    opened = (T0.date() - timedelta(days=100)).isoformat()
    store = world(fictional_store, example_roster, (*BASIC, ("cycle", P3, 1, opened, None, K7, (LF,), "standard")))
    app.do_run(store, now=T0 + timedelta(days=60))
    app.do_run(store, now=T0 + timedelta(days=120))
    numbers = sorted(e["payload"]["attrs"]["number"] for e in cycles_opened(store) if e["payload"]["opened_by"] == flows.coaching.STEP_OPEN)
    assert numbers == [2, 3]  # cycle 2 opened at T0 and ran past 91 days by T0+120, so cycle 3; not before


# --- finding 18: the re-observation date ---------------------------------------------------------------------------


def reobserve_reasons(store, day, signed_at="2026-11-12T09:00:00+00:00"):
    return flows.content_reasons(app.load_state(store), doc_for(STEP_REOBSERVE, K7, observe_cycle_fields(3, day), signed_at))


@pytest.fixture
def after_practice(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-30"), at="2026-10-31T09:00:00+00:00")
    sign(store, STEP_FEEDBACK, CYCLE, K7, feedback_fields([LF, PK]), at="2026-11-02T09:00:00+00:00")
    sign(store, STEP_PRACTICE, CYCLE, K7, practice_fields([LF, PK]), at="2026-11-03T09:00:00+00:00")
    return store


def test_a_reobservation_before_the_first_observation_is_refused(after_practice):
    found = reobserve_reasons(after_practice, "2026-10-29")
    assert any("date" in r and "first observation" in r for r in found), found


def test_a_reobservation_before_the_practice_task_was_set_is_refused(after_practice):
    found = reobserve_reasons(after_practice, "2026-11-02")  # after the first observation, the day before the task was set
    assert any("date" in r and "practice task" in r for r in found), found
    assert not any("first observation" in r for r in found)


def test_a_reobservation_on_the_day_the_practice_task_was_set_or_later_is_accepted(after_practice):
    assert reobserve_reasons(after_practice, "2026-11-03") == []
    assert reobserve_reasons(after_practice, "2026-11-10") == []


def test_the_first_observation_is_not_held_to_those_dates(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    assert flows.content_reasons(app.load_state(store), doc_for(STEP_OBSERVE, K7, observe_cycle_fields(3, "2026-10-26"))) == []


def test_a_sign_off_with_such_a_date_writes_no_observation(after_practice):
    before = len(of_kind(after_practice, "observation"))
    sign(after_practice, STEP_REOBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-29"), at="2026-11-12T09:00:00+00:00")
    assert len(of_kind(after_practice, "observation")) == before  # the hook refuses what ingest would have refused
