"""Integration review findings 6, 20 and 7: the quarterly audit sample.

6.  A quarter's sample is drawn once, after the quarter has closed, over all its live observations; it is not topped up as
    observations arrive.
20. The population is read by the date of the observation, so one dated in the quarter but released after it ended is in it
    (when it was released by the run that draws).
7.  The second observer is never any observer of the sampled observation's delivery_ref.
Fictional people only (the example roster).
"""

from datetime import datetime, timedelta, timezone

from clearer_helpers import calibrate
from test_audit import (
    C5,
    INSTRUCTOR,
    K7,
    Q4,
    R8,
    STD,
    STEP_DRAW,
    add,
    audit,
    log,
    many,
    obs_event,
    of_kind,
    run,
    samples,
    store,
)

from teachermodel import app, records, rules

CLOSED = datetime(2026, 12, 31, 8, 0, tzinfo=timezone.utc)   # the last day of 2026Q4
AFTER = datetime(2027, 1, 4, 8, 0, tzinfo=timezone.utc)      # the first run after it closed
Q1 = "2027Q1"


def population(private, quarter=Q4):
    live = [o for o in records.observations(log(private)) if audit.quarter_id(o.at) == quarter]
    return set(rules.audit_sample(live, quarter, STD["rules"]))


def drawn(private):
    return {e["payload"]["attrs"]["observation"] for e in samples(private)}


def draw_steps(private):
    return [e for e in of_kind(private, "step") if e["payload"].get("step") == STEP_DRAW and e["payload"].get("drawn") is True]


def audit_events(private):
    """What the audit workflow wrote: the samples, the draw steps and the draw checks (other steps write on later days too)."""
    return [e for e in log(private) if (e["kind"] == "subject" and e["payload"]["subject_kind"] == "sample")
            or (e["kind"] in ("step", "check") and e["payload"].get("step") == STEP_DRAW)]


# --- finding 6: drawn once, after the quarter closes --------------------------------------------------------------


def test_previous_quarter_is_the_quarter_that_just_closed():
    from datetime import date

    assert audit.previous_quarter(date(2027, 1, 4)) == "2026Q4"
    assert audit.previous_quarter(date(2026, 10, 1)) == "2026Q3"
    assert audit.previous_quarter(date(2026, 12, 31)) == "2026Q3"
    assert audit.previous_quarter(date(2026, 4, 1)) == "2026Q1"


def test_nothing_is_drawn_while_the_quarter_is_open(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store, q3=0)
    run(fictional_store, datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc))
    run(fictional_store, CLOSED)
    assert samples(fictional_store) == []
    steps = [e for e in of_kind(fictional_store, "step") if e["payload"].get("step") == STEP_DRAW]
    assert len(steps) == 1 and steps[0]["payload"]["opened"] == []  # the step is done, nothing drawn


def test_the_first_run_after_the_quarter_closes_draws_it_over_all_its_live_observations(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store)
    run(fictional_store, AFTER)
    want = population(fictional_store)
    assert len(want) == 6 and drawn(fictional_store) == want
    assert {e["payload"]["attrs"]["quarter"] for e in samples(fictional_store)} == {Q4}  # the earlier quarter is not drawn late
    (draw,) = [e for e in of_kind(fictional_store, "step")
               if e["payload"].get("step") == STEP_DRAW and e["payload"].get("drawn") is True]
    assert draw["payload"]["quarter"] == Q4 and draw["payload"]["opened"] == sorted(e["subject_uri"] for e in samples(fictional_store))


def test_a_run_later_in_the_next_quarter_still_draws_the_quarter_that_closed(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store)
    run(fictional_store, datetime(2027, 2, 20, 8, 0, tzinfo=timezone.utc))
    assert drawn(fictional_store) == population(fictional_store) and drawn(fictional_store)


def test_a_quarter_older_than_the_one_that_just_closed_is_not_drawn_late(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store, q4=0, q3=12)
    run(fictional_store, AFTER)  # 2026Q3 closed a quarter ago
    assert samples(fictional_store) == []


def test_the_sample_is_not_topped_up_by_observations_released_after_the_draw(fictional_store, example_roster):
    store(fictional_store, example_roster)
    add(fictional_store, obs_event(1, K7, INSTRUCTOR, "2026-10-05"))
    run(fictional_store, AFTER)
    assert len(samples(fictional_store)) == 1  # one observation, one pick
    add(fictional_store, obs_event(2, K7, C5, "2026-10-12"), obs_event(3, K7, R8, "2026-10-13"))  # released late, dated in Q4
    run(fictional_store, AFTER + timedelta(days=2))
    run(fictional_store, AFTER + timedelta(days=30))
    assert len(samples(fictional_store)) == 1  # the quarter was drawn once
    assert len(draw_steps(fictional_store)) == 1


def test_the_next_quarter_is_drawn_when_it_closes(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store)
    run(fictional_store, AFTER)
    first = {e["subject_uri"] for e in samples(fictional_store)}
    calibrate(fictional_store, K7, C5, R8, at="2027-02-15T09:00:00+00:00")  # the September passes lapse after six months
    add(fictional_store, obs_event(500, K7, INSTRUCTOR, "2027-01-10"), obs_event(501, C5, INSTRUCTOR, "2027-01-11"))
    run(fictional_store, datetime(2027, 3, 31, 8, 0, tzinfo=timezone.utc))
    assert {e["subject_uri"] for e in samples(fictional_store)} == first  # 2027Q1 is still open
    run(fictional_store, datetime(2027, 4, 5, 8, 0, tzinfo=timezone.utc))
    found = samples(fictional_store)
    assert {e["subject_uri"] for e in found if e["payload"]["attrs"]["quarter"] == Q4} == first
    assert sum(1 for e in found if e["subject_uri"].startswith(f"tm:sample/{Q1}--")) == 2


def test_a_second_run_changes_nothing(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store)
    run(fictional_store, AFTER)
    before = audit_events(fictional_store)
    assert before
    run(fictional_store, AFTER)
    run(fictional_store, AFTER + timedelta(days=3))
    assert audit_events(fictional_store) == before


# --- finding 20: read by the date of the observation ----------------------------------------------------------------


def test_an_observation_dated_in_the_quarter_but_released_after_it_ended_is_in_the_population(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store)
    late = [obs_event(700 + n, [K7, C5, R8][n % 3], INSTRUCTOR if n % 3 else C5, f"2026-12-{20 + n % 10:02d}") for n in range(90)]
    add(fictional_store, *late)  # in the log after the quarter ended, dated inside it
    run(fictional_store, AFTER)
    want = population(fictional_store)
    assert drawn(fictional_store) == want
    assert len(want) > 6  # the late ones count towards the share: 114 observations are not 24
    assert drawn(fictional_store) & {e["id"] for e in late}
    assert {o.id for o in records.observations(log(fictional_store))} >= {e["id"] for e in late}


# --- finding 7: the second observer ------------------------------------------------------------------------------


def test_choose_second_observer_leaves_out_the_other_observers_of_the_delivery():
    pool = [f"tm:instructor/o{n}" for n in range(5)]
    sample = "tm:sample/2026Q4--0123456789abcdef"
    for n in range(20):
        s = f"tm:sample/2026Q4--{n:016x}"
        got = audit.choose_second_observer(s, pool[0], pool[1], pool, set(), co_observers={pool[2], pool[3]})
        assert got == pool[4]
    assert audit.choose_second_observer(sample, pool[0], pool[1], pool, {pool[2]}, co_observers={pool[3], pool[4]}) is None


def test_no_second_observer_is_any_observer_of_the_delivery(fictional_store, example_roster):
    store(fictional_store, example_roster)
    both = []
    for n in range(60):  # k7 and c5 observe the same delivery of the instructor
        both.append(obs_event(900 + 2 * n, K7, INSTRUCTOR, f"2026-10-{1 + n % 28:02d}", delivery_ref=f"d-{n}"))
        both.append(obs_event(901 + 2 * n, C5, INSTRUCTOR, f"2026-10-{1 + n % 28:02d}", delivery_ref=f"d-{n}"))
    add(fictional_store, *both)
    run(fictional_store, AFTER)
    found = samples(fictional_store)
    assert len(found) >= 8
    by_id = {e["id"]: e for e in both}
    for e in found:
        attrs = e["payload"]["attrs"]
        assert attrs["second_observer"] == R8, attrs  # the only clearer who observed neither (k7 and c5 shared the delivery)
        assert by_id[attrs["observation"]]["payload"]["delivery_ref"].startswith("d-")


def test_a_delivery_without_a_reference_excludes_only_its_own_observer(fictional_store, example_roster):
    store(fictional_store, example_roster)
    add(fictional_store, obs_event(1, K7, INSTRUCTOR, "2026-10-05"), obs_event(2, C5, INSTRUCTOR, "2026-10-05"))
    run(fictional_store, AFTER)
    for e in samples(fictional_store):
        a = e["payload"]["attrs"]
        assert a["second_observer"] != a["observer"]


def test_a_second_observer_who_has_since_observed_the_same_delivery_is_no_longer_eligible(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("k7m2q", "c5w1t", "r8n4h"))
    add(fictional_store, obs_event(1, K7, INSTRUCTOR, "2026-10-05", delivery_ref="d-1"))
    run(fictional_store, AFTER)
    (sample,) = samples(fictional_store)
    info = sample["payload"]["attrs"]
    st = app.load_state(fictional_store)
    assert audit.second_observer_reasons(st, info, AFTER.date()) == []
    add(fictional_store, obs_event(2, info["second_observer"], INSTRUCTOR, "2026-10-05", delivery_ref="d-1"))
    reasons = audit.second_observer_reasons(app.load_state(fictional_store), info, AFTER.date())
    assert any("delivery" in r for r in reasons), reasons
