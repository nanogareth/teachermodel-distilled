"""W7 coaching (standards/workflows/coaching.yaml, flows/coaching.py, records/cycles.py).

open-cycles (auto, programme, refresh) opens cycle n+1 for every instructor at lead-observed or above whose previous cycle is
closed and overdue (rules.coaching_overdue: 91 days, or 30 when a quality trigger came after the last cycle opened); the cycle's
steps are the coach's: observe, feedback (due 5 working days after the observation), practice task, re-observe; close (auto)
records the change in each focus domain. Fictional people only.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from ingest_helpers import email_of, ingest, signoff, signoff_events
from test_coaching_support import (
    BASIC,
    C5,
    CQ,
    DOMAINS,
    K7,
    LF,
    LOW,
    P3,
    PK,
    R8,
    RI,
    STEP_CLOSE,
    STEP_FEEDBACK,
    STEP_OBSERVE,
    STEP_OPEN,
    STEP_PRACTICE,
    STEP_REOBSERVE,
    T0,
    TASK,
    TD,
    FEEDBACK,
    UNIT,
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
from test_observation import NOTE, of_kind, sign

from teachermodel import app, due, flows, records, rules
from teachermodel.flows import coaching, observation
from teachermodel.standards import ROOT, check_standards, load_standards

CYCLE = cycle_uri(P3)
RULES = load_standards()["rules"]
ORDER = DOMAINS


def wf():
    return {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/coaching"]


# --- the workflow file -------------------------------------------------------------------------------------------


def test_the_workflow_file_defines_the_coaching_steps():
    steps = {s["id"]: s for s in wf()["steps"]}
    assert set(steps) == {STEP_OPEN, STEP_OBSERVE, STEP_FEEDBACK, STEP_PRACTICE, STEP_REOBSERVE, STEP_CLOSE}
    shape = {sid: (s["type"], s["role"], s["subject"]) for sid, s in steps.items()}
    assert shape == {
        STEP_OPEN: ("auto", "coordinator", "programme"),
        STEP_OBSERVE: ("human", "coach", "cycle"),
        STEP_FEEDBACK: ("human", "coach", "cycle"),
        STEP_PRACTICE: ("human", "coach", "cycle"),
        STEP_REOBSERVE: ("human", "coach", "cycle"),
        STEP_CLOSE: ("auto", "coordinator", "cycle"),
    }
    assert steps[STEP_FEEDBACK]["needs"] == [STEP_OBSERVE] and steps[STEP_PRACTICE]["needs"] == [STEP_FEEDBACK]
    assert steps[STEP_REOBSERVE]["needs"] == [STEP_PRACTICE] and steps[STEP_CLOSE]["needs"] == [STEP_REOBSERVE]
    assert steps[STEP_FEEDBACK]["due"] == "feedback_window" and "feedback_window" in due.names()
    assert set(wf()["event_kinds"]) >= {"step", "signoff", "subject", "observation", "coaching_cycle"}


def test_standards_validate_with_the_coaching_file():
    assert check_standards(ROOT) == []


def test_every_step_has_its_runner_or_builder():
    assert flows.AUTO_STEPS[STEP_OPEN].per == "programme" and flows.AUTO_STEPS[STEP_OPEN].refresh is True
    assert flows.AUTO_STEPS[STEP_CLOSE].per == "cycle"
    assert {STEP_OBSERVE, STEP_FEEDBACK, STEP_PRACTICE, STEP_REOBSERVE} <= set(flows.PAGE_SPECS)
    assert all(s in flows.SIGNOFF_HOOKS for s in (STEP_OBSERVE, STEP_FEEDBACK, STEP_PRACTICE, STEP_REOBSERVE))


# --- pure helpers ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("start,n,want", [
    (date(2026, 10, 28), 5, date(2026, 11, 4)),   # Wednesday + 5 working days = next Wednesday
    (date(2026, 10, 30), 1, date(2026, 11, 2)),   # Friday + 1 = Monday
    (date(2026, 10, 31), 1, date(2026, 11, 2)),   # Saturday + 1 = Monday
    (date(2026, 11, 1), 5, date(2026, 11, 6)),    # Sunday + 5 = Friday
    (date(2026, 10, 30), 5, date(2026, 11, 6)),   # Friday + 5 = next Friday
    (date(2026, 10, 28), 0, date(2026, 10, 28)),
])
def test_working_days_skip_weekends(start, n, want):
    assert coaching.add_working_days(start, n) == want


def test_cycle_uri_is_the_instructor_slug_and_the_number():
    assert coaching.cycle_uri(P3, 3) == "tm:cycle/p3x9d--3"


def test_the_coach_is_the_first_by_hash_rank_and_does_not_depend_on_the_order():
    pool = {K7, C5, R8}
    first = min(pool, key=lambda c: observation.rank(P3, c))
    assert coaching.pick_coach(P3, pool) == first == coaching.pick_coach(P3, sorted(pool, reverse=True))
    assert coaching.pick_coach(P3, set()) is None


def test_choose_focus_takes_the_trigger_domains_else_the_two_lowest():
    avg = {TD: 4.0, PK: 2.0, CQ: 3.0, LF: 1.0, RI: 3.0}
    assert coaching.choose_focus(avg, ORDER, []) == [LF, PK]
    assert coaching.choose_focus(avg, ORDER, [PK]) == [PK]
    assert coaching.choose_focus(avg, ORDER, [RI, PK]) == [PK, RI]            # by average, then framework order
    assert coaching.choose_focus(avg, ORDER, [TD, RI, PK]) == [PK, RI]        # at most two: the lowest of them
    assert coaching.choose_focus(avg, ORDER, ["no-such-domain"]) == [LF, PK]  # an unknown domain names nothing
    assert coaching.choose_focus({}, ORDER, []) == []                          # nothing observed: nothing to focus on
    tied = {d: 3.0 for d in ORDER}
    assert coaching.choose_focus(tied, ORDER, []) == ORDER[:2]                 # ties by framework order


def test_domain_averages_use_the_last_180_days_inclusive():
    from teachermodel.flows import cpd

    today = date(2026, 10, 26)

    def obs(n, days_ago, score):
        return rules.Observation(f"o{n}", P3, UNIT, R8, today - timedelta(days=days_ago), "full", True,
                                 {d: score for d in ORDER})

    found = [obs(1, 180, 1), obs(2, 181, 4), obs(3, 10, 3), obs(4, 0, 4)]
    assert cpd.domain_averages(found, P3, today) == {d: (1 + 3 + 4) / 3 for d in ORDER}
    assert cpd.domain_averages(found, "tm:instructor/zzzzz", today) == {}
    assert cpd.domain_averages(found, P3, today, days=10)[TD] == 3.5


# --- records.cycles ----------------------------------------------------------------------------------------------


def test_records_cycles_is_empty_on_no_events():
    assert records.cycles([]) == []


def test_records_cycles_reads_the_subject_and_the_phase_events(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (
        ("cycle", P3, 1, "2026-05-01", "2026-06-10", K7, (LF, PK), "standard"),
        ("cycle", P3, 2, "2026-08-01", None, K7, (PK,), "triggered"),
        ("cycle", C5, 1, "2026-07-01", "2026-07-20", K7, (TD,), "standard")), run=False)
    found = records.cycles(log(store))
    assert [(c["instructor"], c["number"]) for c in found] == [(C5, 1), (P3, 1), (P3, 2)]  # by instructor, then number
    one = found[1]
    assert one == {"cycle": cycle_uri(P3, 1), "instructor": P3, "coach": K7, "number": 1, "intensity": "standard",
                   "focus": [LF, PK], "trigger": None, "phase": "closed", "opened": date(2026, 5, 1),
                   "closed": date(2026, 6, 10), "change": {LF: 1, PK: 1}}
    two = found[2]
    assert (two["phase"], two["closed"], two["change"], two["opened"]) == ("opened", None, None, date(2026, 8, 1))
    assert two["intensity"] == "triggered"


def test_records_cycles_reports_the_latest_phase_whatever_the_log_order():
    base = {"instructor": P3, "coach": K7, "number": 1, "intensity": "standard", "focus": [LF], "cycle": CYCLE}

    def ev(n, phase, day):
        return {"id": f"e{n}", "at": f"{day}T07:00:00+00:00", "kind": "coaching_cycle", "subject_uri": CYCLE,
                "actor": "tm:system/teachermodel", "payload": {**base, "phase": phase}}

    opened = {"id": "s", "at": "2026-05-01T07:00:00+00:00", "kind": "subject", "subject_uri": CYCLE,
              "actor": "tm:system/teachermodel",
              "payload": {"subject_kind": "cycle", "opened_by": STEP_OPEN, "attrs": {k: v for k, v in base.items() if k != "cycle"}}}
    found = records.cycles([ev(2, "practice", "2026-05-20"), opened, ev(1, "feedback", "2026-05-10"),
                            {**ev(9, "closed", "2026-06-01"), "payload": {**base, "phase": "closed", "change": {LF: 2}}},
                            {"id": "x", "at": "2026-05-01T07:00:00+00:00", "kind": "check", "subject_uri": P3,
                             "actor": "tm:system/teachermodel", "payload": {}}])
    assert len(found) == 1 and found[0]["phase"] == "closed" and found[0]["change"] == {LF: 2}
    assert found[0]["closed"] == date(2026, 6, 1) and found[0]["opened"] == date(2026, 5, 1)
    assert records.cycles([opened, ev(1, "feedback", "2026-05-10")])[0]["phase"] == "feedback"
    assert records.cycles([opened])[0]["phase"] == "opened"


# --- open-cycles -------------------------------------------------------------------------------------------------


def test_a_cycle_opens_for_a_covered_instructor_with_the_two_lowest_domains_as_focus(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    (opened,) = cycles_opened(store)
    assert opened["subject_uri"] == CYCLE and opened["payload"]["opened_by"] == STEP_OPEN
    assert opened["payload"]["attrs"] == {"instructor": P3, "coach": K7, "number": 1, "intensity": "standard",
                                          "focus": [LF, PK]}
    (phase,) = phase_events(store)
    assert phase["subject_uri"] == CYCLE
    assert phase["payload"] == {"cycle": CYCLE, "instructor": P3, "coach": K7, "number": 1, "intensity": "standard",
                                "focus": [LF, PK], "phase": "opened"}
    assert app.load_state(store).subjects[CYCLE]["focus"] == [LF, PK]
    assert (STEP_OBSERVE, CYCLE) in due_ids(store)


def test_only_instructors_at_lead_observed_or_above_are_covered(fictional_store, example_roster):
    ops = (("coach", "k7m2q", [P3, R8]), ("coach", "c5w1t", [K7]), ("obs", P3, "2026-09-15", LOW),
           ("obs", R8, "2026-09-15", LOW), ("obs", K7, "2026-09-15", LOW))
    store = world(fictional_store, example_roster, ops)
    assert {e["payload"]["attrs"]["instructor"] for e in cycles_opened(store)} == {P3}  # not k7m2q (co-deliver), not r8n4h (shadow)
    assert not [e for e in of_kind(store, "check") if e["subject_uri"] in (K7, R8)]


def test_open_cycles_changes_nothing_when_run_again(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    before = log(store)
    app.do_run(store, now=T0 + timedelta(hours=2))
    app.do_run(store, now=T0 + timedelta(days=1))
    assert log(store) == before


def test_the_step_is_done_after_the_first_run_and_refreshes(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    steps = [e for e in of_kind(store, "step") if e["payload"].get("step") == STEP_OPEN]
    assert len(steps) == 1 and steps[0]["payload"]["opened"] == [CYCLE]
    assert (STEP_OPEN, "tm:programme/teachermodel") not in due_ids(store)


def test_no_coach_assigned_is_a_blocked_check_and_no_cycle(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("obs", P3, "2026-09-15", LOW),))
    assert cycles_opened(store) == []
    blocked = [e for e in of_kind(store, "check") if e["payload"].get("step") == STEP_OPEN and e["subject_uri"] == P3]
    assert len(blocked) == 1 and blocked[0]["payload"]["result"] == "blocked"
    assert blocked[0]["payload"]["reasons"] == ["no coach assigned"]
    before = log(store)
    app.do_run(store, now=T0 + timedelta(days=1))
    assert log(store) == before  # the same block is not written twice


def test_a_coach_of_someone_else_is_not_a_coach_here(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("coach", "k7m2q", [C5]), ("obs", P3, "2026-09-15", LOW)))
    assert P3 not in {e["payload"]["attrs"]["instructor"] for e in cycles_opened(store)}
    assert any(e["subject_uri"] == P3 and e["payload"]["reasons"] == ["no coach assigned"] for e in of_kind(store, "check"))


def test_two_coaches_rank_by_hash_and_the_instructor_keeps_the_same_one(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("coach", "k7m2q", [P3]), ("coach", "r8n4h", [P3]),
                                                    ("obs", P3, "2026-09-15", LOW)))
    (opened,) = cycles_opened(store)
    assert opened["payload"]["attrs"]["coach"] == min((K7, R8), key=lambda c: observation.rank(P3, c))


def test_an_instructor_with_no_observation_has_no_focus_and_no_cycle(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("coach", "k7m2q", [P3]),))
    assert cycles_opened(store) == []
    (blocked,) = [e for e in of_kind(store, "check") if e["subject_uri"] == P3 and e["payload"].get("step") == STEP_OPEN]
    assert "no observation" in blocked["payload"]["reasons"][0]


def test_an_instructor_who_delivers_no_unit_cannot_be_observed(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (("coach", "k7m2q", [C5]), ("obs", C5, "2026-09-15", LOW)))
    assert C5 not in {e["payload"]["attrs"]["instructor"] for e in cycles_opened(store)}
    (blocked,) = [e for e in of_kind(store, "check") if e["subject_uri"] == C5 and e["payload"].get("step") == STEP_OPEN]
    assert "no unit" in blocked["payload"]["reasons"][0]


def cadence(days_ago, *extra, closed_cycle=True):
    """BASIC plus a cycle of p3x9d that closed `days_ago` days before T0 (opened a month before that), plus `extra` ops
    (applied after the cycle, so they come later in the log)."""
    closed = (T0.date() - timedelta(days=days_ago)).isoformat()
    opened = (T0.date() - timedelta(days=days_ago + 30)).isoformat()
    cycle = ("cycle", P3, 1, opened, closed if closed_cycle else None, K7, (LF,), "standard")
    return (*BASIC, cycle, *extra)


def opened_numbers(store, instructor=P3):
    return sorted(e["payload"]["attrs"]["number"] for e in cycles_opened(store) if e["payload"]["attrs"]["instructor"] == instructor
                  and e["payload"]["opened_by"] == STEP_OPEN)


@pytest.mark.parametrize("days_ago", [0, 31, 91, 92, 200])
def test_the_next_cycle_follows_the_close_whenever_the_previous_one_closed(fictional_store, example_roster, days_ago):
    # finding 10: the cadence is the cycle's own period; nothing waits 91 days after a close any more
    store = world(fictional_store, example_roster, cadence(days_ago))
    found = [e for e in cycles_opened(store) if e["subject_uri"] == cycle_uri(P3, 2)]
    assert len(found) == 1
    assert found[0]["payload"]["attrs"]["intensity"] == "standard" and "trigger" not in found[0]["payload"]["attrs"]
    assert rules.coaching_overdue(T0.date() - timedelta(days=days_ago), False, T0.date(), RULES) is (days_ago > 91)  # the rule is unchanged


def test_an_unused_trigger_makes_the_next_cycle_triggered_on_the_trigger_domain(fictional_store, example_roster):
    store = world(fictional_store, example_roster, cadence(5, ("trigger", P3, "tr-17", PK)))
    found = [e for e in cycles_opened(store) if e["subject_uri"] == cycle_uri(P3, 2)]
    attrs = found[0]["payload"]["attrs"]
    assert attrs["intensity"] == "triggered" and attrs["trigger"] == "tr-17" and attrs["focus"] == [PK]  # the trigger domain
    assert attrs["number"] == 2 and attrs["coach"] == K7
    (phase,) = phase_events(store, "opened", cycle_uri(P3, 2))
    assert phase["payload"]["intensity"] == "triggered" and phase["payload"]["focus"] == [PK]


def test_a_trigger_without_a_domain_makes_the_cycle_triggered_with_the_two_lowest_domains(fictional_store, example_roster):
    store = world(fictional_store, example_roster, cadence(40, ("trigger", P3, "tr-scores")))
    (found,) = [e for e in cycles_opened(store) if e["subject_uri"] == cycle_uri(P3, 2)]
    attrs = found["payload"]["attrs"]
    assert attrs["intensity"] == "triggered" and attrs["focus"] == [LF, PK] and attrs["trigger"] == "tr-scores"


def test_several_triggers_name_their_domains_and_the_latest_trigger_is_recorded(fictional_store, example_roster):
    store = world(fictional_store, example_roster, cadence(40, ("trigger", P3, "tr-1", RI), ("trigger", P3, "tr-2", PK)))
    (found,) = [e for e in cycles_opened(store) if e["subject_uri"] == cycle_uri(P3, 2)]
    assert found["payload"]["attrs"]["focus"] == [PK, RI] and found["payload"]["attrs"]["trigger"] == "tr-2"


def test_a_trigger_of_another_instructor_does_not_count(fictional_store, example_roster):
    store = world(fictional_store, example_roster, cadence(40, ("trigger", C5, "tr-other", PK)))
    (found,) = [e for e in cycles_opened(store) if e["subject_uri"] == cycle_uri(P3, 2)]
    assert found["payload"]["attrs"]["intensity"] == "standard"


def test_an_unclosed_cycle_within_its_period_is_not_followed_by_another(fictional_store, example_roster):
    store = world(fictional_store, example_roster, cadence(61, closed_cycle=False))  # opened 91 days ago: still its period
    assert opened_numbers(store) == []
    assert [c["number"] for c in records.cycles(log(store)) if c["instructor"] == P3] == [1]


def test_the_next_number_follows_the_highest_on_record(fictional_store, example_roster):
    ops = (*BASIC, ("cycle", P3, 1, "2026-01-01", "2026-02-01", K7, (LF,), "standard"),
           ("cycle", P3, 2, "2026-03-01", "2026-04-01", K7, (LF,), "standard"))
    store = world(fictional_store, example_roster, ops)
    assert opened_numbers(store) == [3]


# --- the cycle ---------------------------------------------------------------------------------------------------


def test_the_coach_alone_is_asked_to_observe_and_the_page_names_the_cycle(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (*BASIC, ("coach", "r8n4h", [C5])))
    st = app.load_state(store)
    (spec,) = app._page_specs(st, STEP_OBSERVE, CYCLE)
    assert spec["signer"] == K7 and spec["role"] == "coach" and spec["template"] == "approve"
    assert spec["inputs"]["cycle"] == CYCLE and spec["inputs"]["focus"] == [LF, PK] and spec["inputs"]["instructor"] == P3
    names = {f["name"] for f in spec["fields"]}
    assert set(DOMAINS) <= names and {"date", "length", "lead", "mode", "unit"} <= names
    unit_field = [f for f in spec["fields"] if f["name"] == "unit"][0]
    assert unit_field["options"] == [UNIT]


def test_observing_records_an_observation_by_the_coach_and_keeps_the_notes_private(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-27", {LF: 1, PK: 2}), at="2026-10-28T09:00:00+00:00")
    (obs,) = [o for o in records.observations(log(store)) if o.observer == K7]
    assert (obs.instructor, obs.unit, obs.length, obs.lead, obs.mode) == (P3, UNIT, "full", True, "remote")
    assert obs.scores[LF] == 1 and obs.scores[PK] == 2 and obs.scores[TD] == 3 and obs.at == date(2026, 10, 27)
    (event,) = [e for e in of_kind(store, "observation") if e["payload"]["observer"] == K7]
    assert event["payload"]["delivery_ref"] == "p3x9d--1-observe" and event["actor"] == K7
    assert (store / event["payload"]["evidence_ref"]).is_file()
    assert NOTE.split()[0] not in (store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert (STEP_OBSERVE, CYCLE) not in due_ids(store) and (STEP_FEEDBACK, CYCLE) in due_ids(store)


def test_feedback_falls_due_five_working_days_after_the_observation(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-28"), at="2026-10-28T09:00:00+00:00")  # a Wednesday
    (feedback,) = [d for d in app.due_steps(app.load_state(store), T0.date()) if d.step == STEP_FEEDBACK]
    assert feedback.due == date(2026, 11, 4) and feedback.overdue is False and feedback.role == "coach"
    late = [d for d in app.due_steps(app.load_state(store), date(2026, 11, 5)) if d.step == STEP_FEEDBACK]
    assert late[0].overdue is True


def test_feedback_and_the_practice_task_are_private_and_write_phase_events(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-27"), at="2026-10-28T09:00:00+00:00")
    sign(store, STEP_FEEDBACK, CYCLE, K7, feedback_fields([LF, PK]), at="2026-10-29T09:00:00+00:00")
    (fb,) = phase_events(store, "feedback")
    assert fb["payload"]["cycle"] == CYCLE and fb["payload"]["focus"] == [LF, PK] and fb["payload"]["signoff_id"]
    assert (STEP_PRACTICE, CYCLE) in due_ids(store) and (STEP_FEEDBACK, CYCLE) not in due_ids(store)
    sign(store, STEP_PRACTICE, CYCLE, K7, practice_fields([LF, PK]), at="2026-10-30T09:00:00+00:00")
    (pr,) = phase_events(store, "practice")
    assert pr["payload"]["signoff_id"] and (STEP_REOBSERVE, CYCLE) in due_ids(store)
    text = (store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert FEEDBACK.split()[0] not in text and TASK.split()[0] not in text and "evidence for" not in text
    private = "".join(p.read_text(encoding="utf-8") for p in (store / "coaching").rglob("*.json"))
    assert FEEDBACK in private and TASK in private


def test_closing_records_the_change_in_each_focus_domain(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 3, PK: 2, TD: 1})
    (closed,) = phase_events(store, "closed")
    assert closed["payload"]["change"] == {LF: 2, PK: 0}       # re-observation minus first, the focus domains only
    assert closed["subject_uri"] == CYCLE and closed["payload"]["focus"] == [LF, PK]
    (cycle,) = [c for c in records.cycles(log(store)) if c["instructor"] == P3 and c["number"] == 1]
    assert cycle["phase"] == "closed" and cycle["change"] == {LF: 2, PK: 0} and cycle["closed"] == date(2026, 11, 23)
    assert [e["payload"]["phase"] for e in phase_events(store, cycle=CYCLE)] == ["opened", "feedback", "practice", "closed"]
    assert (STEP_CLOSE, CYCLE) not in due_ids(store, datetime(2026, 11, 23, tzinfo=timezone.utc))
    before = log(store)
    app.do_run(store, now=datetime(2026, 11, 24, 8, tzinfo=timezone.utc))
    assert log(store) == before                                   # not closed twice, and the next cycle is already open


def test_the_next_cycle_opens_with_the_close_and_sets_its_focus_from_the_observations_so_far(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    drive_cycle(store, CYCLE, first={LF: 1, PK: 2}, second={LF: 2, PK: 2})
    assert opened_numbers(store) == [1, 2]  # the same run that closed cycle 1
    (second,) = [e for e in cycles_opened(store) if e["subject_uri"] == cycle_uri(P3, 2)]
    assert second["payload"]["attrs"]["focus"] == [LF, PK]  # the lowest two over the last 180 days, now including the coach's


def test_a_cycle_that_closes_without_both_observations_does_not_close(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    runner = flows.AUTO_STEPS[STEP_CLOSE].run
    assert runner(app.load_state(store), CYCLE, T0) == []


# --- who may sign, and when ---------------------------------------------------------------------------------------


def doc_for(step, signer, fields, signed_at="2026-10-28T09:00:00+00:00", sid="abc0123456789abc"):
    return {"id": sid, "step": step, "subject_uri": CYCLE, "decision": "approve", "signer": signer, "signed_at": signed_at,
            "fields": fields}


def test_only_the_cycles_coach_can_sign_its_steps(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (*BASIC, ("coach", "r8n4h", [C5])))
    st = app.load_state(store)
    good = doc_for(STEP_OBSERVE, K7, observe_cycle_fields(3, "2026-10-27"))
    assert flows.content_reasons(st, good) == []
    bad = flows.content_reasons(st, {**good, "signer": R8})  # a coach, but of someone else
    assert bad and any("coach" in r or "observer" in r for r in bad)
    assert flows.content_reasons(st, doc_for(STEP_FEEDBACK, K7, feedback_fields([LF, PK]))) == []
    assert flows.content_reasons(st, doc_for(STEP_FEEDBACK, R8, feedback_fields([LF, PK])))
    assert flows.content_reasons(st, doc_for(STEP_PRACTICE, R8, practice_fields([LF, PK])))


def test_feedback_needs_a_note_and_feedback_for_each_focus_domain(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    st = app.load_state(store)
    full = feedback_fields([LF, PK])
    for missing in full:
        fields = {k: v for k, v in full.items() if k != missing}
        assert flows.content_reasons(st, doc_for(STEP_FEEDBACK, K7, fields)), missing
        assert flows.content_reasons(st, doc_for(STEP_FEEDBACK, K7, {**full, missing: "  "})), missing
    plan = practice_fields([LF, PK])
    for missing in plan:
        assert flows.content_reasons(st, doc_for(STEP_PRACTICE, K7, {k: v for k, v in plan.items() if k != missing})), missing
    # the reasons name the field and never quote an answer
    reasons = flows.content_reasons(st, doc_for(STEP_FEEDBACK, K7, {**full, f"feedback-{LF}": ""}))
    assert all(FEEDBACK not in r for r in reasons)


def test_a_session_dated_before_the_cycle_opened_is_refused(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    st = app.load_state(store)
    reasons = flows.content_reasons(st, doc_for(STEP_OBSERVE, K7, observe_cycle_fields(3, "2026-10-25")))
    assert any("before" in r for r in reasons)


def test_an_observation_needs_a_unit_the_instructor_delivers_and_every_score(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    st = app.load_state(store)
    fields = observe_cycle_fields(3, "2026-10-27")
    assert flows.content_reasons(st, doc_for(STEP_OBSERVE, K7, {**fields, "unit": "sl:unit/other@1"}))
    assert flows.content_reasons(st, doc_for(STEP_OBSERVE, K7, {k: v for k, v in fields.items() if k != "unit"}))
    assert flows.content_reasons(st, doc_for(STEP_OBSERVE, K7, {k: v for k, v in fields.items() if k != LF}))


def test_the_coach_signs_observe_through_the_real_mail_round_trip(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    app.do_tick(store, now=T0)
    fields = observe_cycle_fields(3, "2026-10-26")
    doc, sender = signoff(store, STEP_OBSERVE, CYCLE, K7, fields, now=T0)
    assert sender == "coach.k7m2q@example.com"
    rep = ingest(store, [(doc, sender)], now=T0)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    assert [o.observer for o in records.observations(log(store))].count(K7) == 1
    assert len(signoff_events(store, STEP_OBSERVE, CYCLE)) == 1
    app.do_tick(store, now=T0 + timedelta(hours=3))
    assert (STEP_FEEDBACK, CYCLE) in due_ids(store, T0 + timedelta(hours=3))


def test_another_coach_cannot_sign_the_cycles_observation_through_ingest(fictional_store, example_roster):
    store = world(fictional_store, example_roster, (*BASIC, ("coach", "r8n4h", [C5])))
    app.do_tick(store, now=T0)
    doc, _ = signoff(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-26"), now=T0)
    doc["signer"] = R8
    rep = ingest(store, [(doc, email_of(store, R8))], now=T0)
    assert "1 rejected" in rep.summary, rep.all_lines()
    assert [e for e in of_kind(store, "observation") if e["payload"].get("delivery_ref")] == []  # none by the cycle's flow


def test_a_whole_cycle_runs_through_the_real_mail_round_trip(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)

    def step(at, step_id, fields, name):
        app.do_tick(store, now=at)
        doc, sender = signoff(store, step_id, CYCLE, K7, fields, now=at)
        rep = ingest(store, [(doc, sender)], now=at, name=name)
        assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
        app.do_run(store, now=at + timedelta(hours=3))

    step(T0, STEP_OBSERVE, observe_cycle_fields(3, "2026-10-26", {LF: 1, PK: 2}), "r1")
    step(T0 + timedelta(days=1), STEP_FEEDBACK, feedback_fields([LF, PK]), "r2")
    step(T0 + timedelta(days=2), STEP_PRACTICE, practice_fields([LF, PK]), "r3")
    assert phase_events(store, "closed") == []
    step(T0 + timedelta(days=20), STEP_REOBSERVE, observe_cycle_fields(3, "2026-11-14", {LF: 2, PK: 4}), "r4")
    (closed,) = phase_events(store, "closed")
    assert closed["payload"]["change"] == {LF: 1, PK: 2}
    assert [e["payload"]["phase"] for e in phase_events(store, cycle=CYCLE)] == ["opened", "feedback", "practice", "closed"]
    assert len(signoff_events(store)) == 4


# --- the coach's observations can be scored from a recording (W11, decision 0015, appended 2026-10-25) --------------

import json  # noqa: E402

from teachermodel import events  # noqa: E402


def first_observation(store):
    (event,) = [e for e in of_kind(store, "observation") if e["payload"]["observer"] == K7
                and not e["payload"].get("delivery_ref", "").endswith("-reobserve")]
    return event


def test_the_coach_observation_pages_offer_the_from_recording_field(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    field = next(f for f in app._page_specs(app.load_state(store), STEP_OBSERVE, CYCLE)[0]["fields"]
                 if f["name"] == "from_recording")
    assert field["kind"] == "bool" and field["required"] is False
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-27"), at="2026-10-28T09:00:00+00:00")
    sign(store, STEP_FEEDBACK, CYCLE, K7, feedback_fields([LF, PK]), at="2026-10-29T09:00:00+00:00")
    sign(store, STEP_PRACTICE, CYCLE, K7, practice_fields([LF, PK]), at="2026-10-30T09:00:00+00:00")
    field = next(f for f in app._page_specs(app.load_state(store), STEP_REOBSERVE, CYCLE)[0]["fields"]
                 if f["name"] == "from_recording")
    assert field["kind"] == "bool" and field["required"] is False


@pytest.mark.parametrize("answer", [True, False])
def test_a_coach_observation_carries_from_recording_into_the_observation_event(fictional_store, example_roster, answer):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, {**observe_cycle_fields(3, "2026-10-27"), "from_recording": answer},
         at="2026-10-28T09:00:00+00:00")
    event = first_observation(store)
    assert event["payload"]["from_recording"] is answer and events.check_event(event) == []
    assert json.loads((store / event["payload"]["evidence_ref"]).read_text(encoding="utf-8"))["from_recording"] is answer


def test_a_coach_observation_without_the_field_has_no_from_recording(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-27"), at="2026-10-28T09:00:00+00:00")
    assert "from_recording" not in first_observation(store)["payload"]


def test_a_re_observation_carries_from_recording_too(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, observe_cycle_fields(3, "2026-10-27"), at="2026-10-28T09:00:00+00:00")
    sign(store, STEP_FEEDBACK, CYCLE, K7, feedback_fields([LF, PK]), at="2026-10-29T09:00:00+00:00")
    sign(store, STEP_PRACTICE, CYCLE, K7, practice_fields([LF, PK]), at="2026-10-30T09:00:00+00:00")
    sign(store, STEP_REOBSERVE, CYCLE, K7, {**observe_cycle_fields(3, "2026-11-10"), "from_recording": True},
         at="2026-11-11T09:00:00+00:00")
    later = [e for e in of_kind(store, "observation") if e["payload"].get("delivery_ref", "").endswith("-reobserve")]
    assert len(later) == 1 and later[0]["payload"]["from_recording"] is True
    assert "from_recording" not in first_observation(store)["payload"]  # the first one did not say


def test_a_from_recording_answer_that_is_not_yes_or_no_is_refused(fictional_store, example_roster):
    store = world(fictional_store, example_roster, BASIC)
    found = flows.content_reasons(app.load_state(store), doc_for(
        STEP_OBSERVE, K7, {**observe_cycle_fields(3, "2026-10-27"), "from_recording": "yes"}))
    assert any("from_recording" in r for r in found), found


def test_a_coach_observation_scored_from_a_recording_is_recorded_for_the_clearance_check(fictional_store, example_roster):
    # W4 reads the same payload field as W2's release writes (flows/clearance.py `_recorded`), so a partner's coach counts
    from teachermodel.flows import clearance

    store = world(fictional_store, example_roster, BASIC)
    sign(store, STEP_OBSERVE, CYCLE, K7, {**observe_cycle_fields(3, "2026-10-27"), "from_recording": True},
         at="2026-10-28T09:00:00+00:00")
    assert clearance._recorded(first_observation(store)) is True


def test_records_cycles_reports_the_current_intensity_and_focus_of_a_switched_cycle():
    """A mid-cycle switch to triggered writes a coaching_cycle event with the new intensity and focus; records.cycles reports
    them as app.derive_cycles does, so the bench evidence pack shows the cycle as it is now."""
    base = {"instructor": P3, "coach": K7, "number": 1, "cycle": CYCLE}
    attrs = {**{k: v for k, v in base.items() if k != "cycle"}, "intensity": "standard", "focus": [LF]}

    def ev(n, phase, day, **more):
        return {"id": f"e{n}", "at": f"{day}T07:00:00+00:00", "kind": "coaching_cycle", "subject_uri": CYCLE,
                "actor": "tm:system/teachermodel", "payload": {**base, "phase": phase, "intensity": "standard", "focus": [LF], **more}}

    opened = {"id": "s", "at": "2026-05-01T07:00:00+00:00", "kind": "subject", "subject_uri": CYCLE,
              "actor": "tm:system/teachermodel", "payload": {"subject_kind": "cycle", "opened_by": STEP_OPEN, "attrs": attrs}}
    switched = ev(2, "opened", "2026-05-08", intensity="triggered", focus=[PK])
    (found,) = records.cycles([opened, ev(1, "opened", "2026-05-01"), switched])
    assert (found["intensity"], found["focus"]) == ("triggered", [PK])
    assert found["opened"] == date(2026, 5, 1)  # the opening day stays that of the subject event
    (later,) = records.cycles([opened, ev(1, "opened", "2026-05-01"), switched, ev(3, "feedback", "2026-05-10", intensity="triggered", focus=[PK])])
    assert (later["intensity"], later["focus"], later["phase"]) == ("triggered", [PK], "feedback")
    assert records.cycles([opened])[0]["intensity"] == "standard"
