"""W8 quality review (standards/workflows/quality.yaml, flows/quality.py): outcome summaries against the cohort baseline.

quality-review (auto, per instructor, refresh) runs `rules.quality_triggers` over `records.outcomes` and
`records.observations` and writes one trigger `check` event per NEW trigger, `{step, instructor, result: "trigger",
trigger: <reason id>, domain?}`, with an id derived from (instructor, reason, the delivery or observation that completed it),
so a re-run adds nothing. It also writes generated/quality/<slug>.json for the views: aggregates only, the score hidden below
the minimum learner count. It never opens a bench. Outcomes are written as events directly (the import has its own tests in
test_quality_import.py). Fictional data only.
"""

import hashlib
import json
from datetime import date, datetime, timezone

import pytest
from conftest import make_fictional_store
from privacy_helpers import import_roster_ungated

from teachermodel import app, events, flows, records, rules
from teachermodel.flows import quality
from teachermodel.standards import ROOT, check_standards, load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
UNIT = "sl:unit/example-agent-loop@1"
K7, P3 = "tm:instructor/k7m2q", "tm:instructor/p3x9d"
STEP = "tm:step/quality-review"
DOMAINS = [d["id"] for d in load_standards()["framework"]["domains"]]
RULES = load_standards()["rules"]


def _build(base, roster_bytes, run, notices=True):
    private = make_fictional_store(base)
    roster = base / "roster-in.yaml"
    roster.write_bytes(roster_bytes)
    import_roster_ungated(private, roster, T0)
    for who in (K7, P3) if notices else ():  # the notice of the base profile has gone to these two (quality-review waits)
        events.append(private / app.EVENT_LOG, events.make_event(
            "notice", who, "tm:system/teachermodel",
            {"step": "tm:step/notice-sent", "notice_variant": "2026-11"}, at="2026-10-26T07:30:00+00:00"))
    if run:
        app.do_run(private, now=T0)


@pytest.fixture
def store(fictional_store, example_roster, cached_world):
    """The roster imported and one run (quality-review is done for every instructor), built once per session."""
    data = example_roster.read_bytes()
    key = ("quality_store", hashlib.sha256(data).hexdigest())
    cached_world(key, lambda base: _build(base, data, True))
    return fictional_store


@pytest.fixture
def fresh(fictional_store, example_roster, cached_world):
    """The roster imported, no notice sent and no run yet."""
    data = example_roster.read_bytes()
    cached_world(("quality_fresh", hashlib.sha256(data).hexdigest()), lambda base: _build(base, data, False, False))
    return fictional_store


def outcome_event(n, score, baseline, *, learners=20, instructor=K7, feedback=None, median=None, day=None, ref=None):
    payload = {"delivery_ref": ref or f"delivery-{n}", "instructor": instructor, "unit": UNIT, "mode": "remote",
               "delivered_on": day or f"2026-10-{n:02d}", "learners_assessed": learners, "score": score,
               "baseline": baseline, "source": "lms-export"}
    if feedback is not None:
        payload["feedback"] = feedback
    if median is not None:
        payload["feedback_median"] = median
    return events.make_event("outcome", instructor, "tm:system/teachermodel", payload,
                             id=hashlib.sha256(f"outcome|{payload['delivery_ref']}".encode()).hexdigest()[:32],
                             at=f"{payload['delivered_on']}T12:00:00+00:00")


def observation_event(instructor, observer, domain, score, day, n):
    scores = {d: 3 for d in DOMAINS}
    scores[domain] = score
    return events.make_event(
        "observation", instructor, observer,
        {"instructor": instructor, "unit": UNIT, "observer": observer, "length": "full", "lead": True,
         "rubric_version": "0.2.0", "scores": scores}, id=f"obs-{n:04d}", at=f"{day}T10:00:00+00:00")


def add(private, *evs):
    app.append_new(private, evs)


def run(private, now=T0):
    return app.do_run(private, now=now)


def triggers(private, instructor=K7):
    return [e for e in app.read_events(private) if e["kind"] == "check" and e["subject_uri"] == instructor
            and e["payload"].get("step") == STEP and e["payload"].get("result") == "trigger"]


def reasons(private, instructor=K7):
    return sorted((e["payload"]["trigger"], e["payload"].get("domain")) for e in triggers(private, instructor))


def summary(private, slug="k7m2q"):
    return json.loads((private / "generated" / "quality" / f"{slug}.json").read_text(encoding="utf-8"))


# --- the workflow file and the registrations ----------------------------------------------------------------------


def test_the_workflow_file_defines_quality_review():
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/quality"]
    (step,) = wf["steps"]
    assert (step["id"], step["type"], step["subject"]) == (STEP, "auto", "instructor")
    assert step["done_when"] == {"kind": "step", "match": {"step": STEP}}
    assert {"step", "check"} <= set(wf["event_kinds"])
    assert check_standards(ROOT) == []


def test_quality_review_waits_for_the_notice_of_the_instructor(fresh):
    due = {(d.step, d.subject) for d in app.due_steps(app.load_state(fresh), T0.date())}
    assert (STEP, K7) not in due  # no notice sent yet
    for who in (K7, P3):
        add(fresh, events.make_event("notice", who, "tm:system/teachermodel",
                                     {"step": "tm:step/notice-sent", "notice_variant": "2026-11"}))
    due = {(d.step, d.subject) for d in app.due_steps(app.load_state(fresh), T0.date())}
    assert (STEP, K7) in due and (STEP, P3) in due


def test_the_runner_is_registered_per_instructor_and_refreshes():
    auto = flows.AUTO_STEPS[STEP]
    assert auto.per == "instructor" and auto.refresh is True


# --- records.outcomes ---------------------------------------------------------------------------------------------


def test_records_outcomes_reads_outcome_events_oldest_delivery_first_and_ignores_the_rest():
    late, early = outcome_event(20, 70, 80), outcome_event(5, 75, 80, feedback=4.0, median=4.2)
    other = events.make_event("check", K7, "tm:system/teachermodel", {"step": "x"})
    got = records.outcomes([late, other, early])
    assert [o.delivery for o in got] == ["delivery-5", "delivery-20"]
    assert got[0] == rules.Outcome(delivery="delivery-5", instructor=K7, at=date(2026, 10, 5), learners_assessed=20,
                                   score=75, baseline=80, feedback=4.0, feedback_median=4.2)
    assert got[1].feedback is None and got[1].feedback_median is None
    assert records.outcomes([]) == []


def test_records_outcomes_the_same_delivery_twice_appears_once_the_later_event_wins():
    first = outcome_event(5, 75, 80, ref="d-1")
    second = outcome_event(5, 60, 80, ref="d-1")
    second["id"] = "later"
    got = records.outcomes([first, second])
    assert [(o.delivery, o.score) for o in got] == [("d-1", 60)]


# --- the score trigger: 10 points, two consecutive deliveries, 15 learners -----------------------------------------


def test_ten_points_below_baseline_on_two_consecutive_deliveries_triggers(store):
    add(store, outcome_event(5, 70, 80), outcome_event(12, 70, 80))
    run(store)
    (found,) = triggers(store)
    assert found["payload"] == {"step": STEP, "instructor": K7, "result": "trigger", "trigger": "score-drop"}
    assert found["actor"] == "tm:system/teachermodel"
    assert events.check_event(found) == []


def test_nine_points_below_baseline_does_not_trigger(store):
    add(store, outcome_event(5, 71, 80), outcome_event(12, 71, 80))
    run(store)
    assert triggers(store) == []


def test_one_delivery_below_does_not_trigger(store):
    add(store, outcome_event(5, 60, 80))
    run(store)
    assert triggers(store) == []


def test_a_good_delivery_between_two_bad_ones_breaks_the_run(store):
    add(store, outcome_event(5, 60, 80), outcome_event(12, 79, 80), outcome_event(19, 60, 80))
    run(store)
    assert triggers(store) == []


def test_fourteen_learners_never_trigger_and_fifteen_count(store):
    add(store, outcome_event(5, 60, 80, learners=14), outcome_event(12, 60, 80, learners=14))
    run(store)
    assert triggers(store) == []
    add(store, outcome_event(19, 60, 80, learners=15), outcome_event(20, 60, 80, learners=15))
    run(store)
    assert reasons(store) == [("score-drop", None)]


def test_the_threshold_is_read_from_the_rules_not_hard_coded():
    assert RULES["quality"]["min_learners_for_metric"] == 15 and RULES["quality"]["score_drop_points"] == 10


# --- the feedback trigger -----------------------------------------------------------------------------------------


def test_feedback_below_the_median_on_two_consecutive_deliveries_triggers(store):
    add(store, outcome_event(5, 80, 80, feedback=3.9, median=4.2), outcome_event(12, 80, 80, feedback=4.0, median=4.2))
    run(store)
    (found,) = triggers(store)
    assert found["payload"] == {"step": STEP, "instructor": K7, "result": "trigger",
                                "trigger": "feedback-below-median"}


def test_feedback_at_the_median_or_on_one_delivery_does_not_trigger(store):
    add(store, outcome_event(5, 80, 80, feedback=3.9, median=4.2), outcome_event(12, 80, 80, feedback=4.2, median=4.2))
    run(store)
    assert triggers(store) == []


def test_feedback_from_a_delivery_below_the_minimum_learner_count_never_triggers(store):
    add(store, outcome_event(5, 80, 80, learners=14, feedback=1.0, median=4.2),
        outcome_event(12, 80, 80, learners=14, feedback=1.0, median=4.2))
    run(store)
    assert triggers(store) == []


# --- a domain at 1 confirmed by a second observer ------------------------------------------------------------------


def test_a_domain_scored_1_by_two_observers_triggers_with_the_domain(store):
    d = DOMAINS[0]
    add(store, observation_event(K7, "tm:instructor/obs-a", d, 1, "2026-10-01", 1),
        observation_event(K7, "tm:instructor/obs-b", d, 1, "2026-10-10", 2))
    run(store)
    (found,) = triggers(store)
    assert found["payload"] == {"step": STEP, "instructor": K7, "result": "trigger", "trigger": "domain-one-confirmed",
                                "domain": d}
    assert events.check_event(found) == []


def test_a_domain_scored_1_by_one_observer_or_twice_by_the_same_one_does_not_trigger(store):
    d = DOMAINS[0]
    add(store, observation_event(K7, "tm:instructor/obs-a", d, 1, "2026-10-01", 1),
        observation_event(K7, "tm:instructor/obs-a", d, 1, "2026-10-10", 2))
    run(store)
    assert triggers(store) == []


def test_a_confirmation_outside_the_window_does_not_trigger(store):
    d = DOMAINS[0]
    window = RULES["quality"]["confirmation_window_days"]
    assert window == 90
    add(store, observation_event(K7, "tm:instructor/obs-a", d, 1, "2026-07-01", 1),
        observation_event(K7, "tm:instructor/obs-b", d, 1, "2026-10-10", 2))
    run(store)
    assert triggers(store) == []


def test_each_confirmed_domain_gets_its_own_trigger(store):
    a, b = DOMAINS[0], DOMAINS[1]
    add(store, observation_event(K7, "tm:instructor/obs-a", a, 1, "2026-10-01", 1),
        observation_event(K7, "tm:instructor/obs-b", a, 1, "2026-10-02", 2),
        observation_event(K7, "tm:instructor/obs-a", b, 1, "2026-10-03", 3),
        observation_event(K7, "tm:instructor/obs-b", b, 1, "2026-10-04", 4))
    run(store)
    assert reasons(store) == sorted([("domain-one-confirmed", a), ("domain-one-confirmed", b)])


# --- one trigger per new trigger; idempotent ----------------------------------------------------------------------


def test_a_second_run_adds_nothing(store):
    add(store, outcome_event(5, 70, 80), outcome_event(12, 70, 80, feedback=1.0, median=4.0),
        outcome_event(13, 70, 80, feedback=1.0, median=4.0))
    run(store)
    before = app.read_events(store)
    assert len(triggers(store)) == 2
    again = run(store)
    assert app.read_events(store) == before
    assert "quality-review" not in "\n".join(again.lines)


def test_a_later_delivery_that_extends_the_run_is_a_new_trigger(store):
    add(store, outcome_event(5, 70, 80), outcome_event(12, 70, 80))
    run(store)
    add(store, outcome_event(19, 70, 80))
    run(store)
    found = triggers(store)
    assert len(found) == 2 and len({e["id"] for e in found}) == 2


def test_a_delivery_below_the_minimum_after_a_trigger_does_not_repeat_it(store):
    add(store, outcome_event(5, 70, 80), outcome_event(12, 70, 80))
    run(store)
    add(store, outcome_event(19, 70, 80, learners=3))
    run(store)
    assert len(triggers(store)) == 1


def test_the_trigger_id_comes_from_instructor_reason_and_latest_delivery():
    ids = {quality.trigger_id(K7, "score-drop", "d-2"), quality.trigger_id(K7, "score-drop", "d-3"),
           quality.trigger_id(P3, "score-drop", "d-2"), quality.trigger_id(K7, "feedback-below-median", "d-2")}
    assert len(ids) == 4 and quality.trigger_id(K7, "score-drop", "d-2") == quality.trigger_id(K7, "score-drop", "d-2")


def test_triggers_are_per_instructor(store):
    add(store, outcome_event(5, 70, 80), outcome_event(12, 70, 80),
        outcome_event(6, 79, 80, instructor=P3), outcome_event(13, 79, 80, instructor=P3))
    run(store)
    assert reasons(store, K7) == [("score-drop", None)] and triggers(store, P3) == []


def test_the_first_run_after_an_import_writes_the_triggers_too(fresh):
    add(fresh, events.make_event("notice", K7, "tm:system/teachermodel",
                                 {"step": "tm:step/notice-sent", "notice_variant": "2026-11"}))
    add(fresh, outcome_event(5, 70, 80), outcome_event(12, 70, 80))
    run(fresh)
    assert reasons(fresh) == [("score-drop", None)]
    assert any(e["kind"] == "step" and e["subject_uri"] == K7 and e["payload"]["step"] == STEP
               for e in app.read_events(fresh))


def test_an_unmapped_rule_reason_is_an_error_not_silence():
    with pytest.raises(ValueError, match="unknown quality trigger"):
        quality.reason_id("a reason the rules module invented")


def test_each_reason_the_rules_module_gives_maps_to_an_id():
    ids = {"performance-task score 10+ below baseline on 2 deliveries": ("score-drop", None),
           "feedback below median on 2 deliveries": ("feedback-below-median", None),
           "domain technical-depth scored 1 by 2 observers": ("domain-one-confirmed", "technical-depth")}
    for text, want in ids.items():
        assert quality.reason_id(text) == want


# --- a trigger never opens a bench --------------------------------------------------------------------------------


def test_no_trigger_opens_a_bench_subject(store):
    d = DOMAINS[0]
    add(store, outcome_event(5, 50, 80), outcome_event(12, 50, 80), outcome_event(19, 50, 80),
        outcome_event(26, 50, 80, feedback=1.0, median=4.0), outcome_event(27, 50, 80, feedback=1.0, median=4.0),
        observation_event(K7, "tm:instructor/obs-a", d, 1, "2026-10-01", 1),
        observation_event(K7, "tm:instructor/obs-b", d, 1, "2026-10-10", 2))
    run(store)
    assert len(triggers(store)) == 3
    log = app.read_events(store)
    assert not [e for e in log if e["kind"] == "bench_decision"]
    assert not [e for e in log if e["kind"] == "subject" and e["payload"]["subject_kind"] == "bench"]
    assert not [u for u in app.load_state(store).subjects if u.startswith("tm:bench/")]


# --- the summary for the views ------------------------------------------------------------------------------------


def test_the_summary_shows_the_score_against_the_baseline_per_delivery(store):
    add(store, outcome_event(5, 72.5, 80, feedback=4.1, median=4.4), outcome_event(12, 78, 80))
    run(store)
    doc = summary(store)
    assert doc["instructor"] == K7 and doc["minimum_learners"] == 15
    first, second = doc["deliveries"]
    assert first["delivery_ref"] == "delivery-5" and first["delivered_on"] == "2026-10-05"
    assert (first["score"], first["baseline"], first["gap"], first["status"]) == (72.5, 80, -7.5, "ok")
    assert (first["feedback"], first["feedback_median"]) == (4.1, 4.4)
    assert (second["score"], second["gap"], second["feedback"]) == (78, -2, None)


def test_the_summary_hides_a_delivery_below_the_minimum_learner_count(store):
    add(store, outcome_event(5, 61, 80, learners=14, feedback=2.0, median=4.0), outcome_event(12, 61, 80, learners=15))
    run(store)
    small, enough = summary(store)["deliveries"]
    assert (small["score"], small["baseline"], small["gap"], small["feedback"], small["feedback_median"]) == (
        None, None, None, None, None)
    assert small["status"] == "insufficient data" and small["learners_assessed"] == 14
    assert enough["score"] == 61 and enough["status"] == "ok"
    text = (store / "generated" / "quality" / "k7m2q.json").read_text(encoding="utf-8")
    assert "61" in text and "2.0" not in text  # the small delivery's numbers appear nowhere


def test_the_summary_lists_the_open_triggers_and_is_aggregates_only(store):
    add(store, outcome_event(5, 70, 80), outcome_event(12, 70, 80))
    run(store)
    doc = summary(store)
    assert [t["trigger"] for t in doc["triggers"]] == ["score-drop"]
    assert set(doc) == {"schema", "instructor", "minimum_learners", "deliveries", "triggers"}
    assert set(doc["deliveries"][0]) == {"delivery_ref", "unit", "mode", "delivered_on", "learners_assessed", "score",
                                         "baseline", "gap", "feedback", "feedback_median", "status"}


def test_the_summary_is_rewritten_only_when_it_changes(store):
    add(store, outcome_event(5, 70, 80))
    run(store)
    path = store / "generated" / "quality" / "k7m2q.json"
    first = path.stat().st_mtime_ns
    run(store)
    assert path.stat().st_mtime_ns == first
    add(store, outcome_event(12, 70, 80))
    run(store)
    assert len(summary(store)["deliveries"]) == 2


def test_an_instructor_without_outcomes_gets_an_empty_summary(store):
    run(store)
    doc = summary(store, "p3x9d")
    assert doc["deliveries"] == [] and doc["triggers"] == []


def test_the_log_stays_valid_after_a_review(store):
    add(store, outcome_event(5, 70, 80), outcome_event(12, 70, 80))
    run(store)
    assert events.verify(store / app.EVENT_LOG) == []
