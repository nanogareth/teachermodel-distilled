"""W10 bench decision (standards/workflows/bench.yaml, flows/bench.py, records/bench.py; spec v0.2 W10 and Rules, "Bench
evidence"; decisions 0005 and 0014).

    open-bench (auto, programme)   a bench subject per occasion: engagement end within 30 days, two quality triggers on a
                                   triggered cycle, or `teachermodel request-bench`
    evidence-pack (auto, per bench)  generated/bench/<slug>.html, a self-contained pack; its sha256 goes in a step event
    bench-ready (auto, per bench)  rules.bench_ready: an evidence pack and two current observers
    bench-decision (head of training, bind: input)  the decision and a private rationale; a hook writes the bench_decision
                                   event and, for return-to-co-teaching, a level change

Most pack tests fake the records of the other streams (cycles, cpd, outcomes, audits) to pin the pack's filtering;
test_the_pack_shows_the_real_records_of_the_quality_loop reads them from real events. Fictional people only.
"""

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from conftest import EXAMPLE_ROSTER_PATH, make_fictional_store
from clearer_helpers import set_level
from ingest_helpers import ingest, signoff
from privacy_helpers import import_roster_ungated
from test_clearance import (
    AT, C5, DOMAINS, K7, P3, R8, RUBRIC, STD, T0, UNIT, decide, hold, of_kind, put, reasons, signers,
)

from teachermodel import app, cli, events, records, rules, signoff as tm_signoff, workflow
from teachermodel.flows import bench, clearance, quality
from teachermodel.standards import ROOT

HOT = "tm:person/hot-1"
BENCH = "tm:bench/k7m2q--1"
OPEN, PACK, READY, DECISION = (f"tm:step/{s}" for s in ("open-bench", "evidence-pack", "bench-ready", "bench-decision"))
QR = "tm:step/quality-review"
NOTE = "SECRET-NOTE-about-the-delivery"


# --- the world -------------------------------------------------------------------------------------------------------


def log(private):
    return app.read_events(private)


def obs(private, observer, day, *, instructor=K7, score=3, note=True, n=None):
    """An `observation` event, with its notes in the private store under evidence_ref (never in the event)."""
    n = len(of_kind(private, "observation")) if n is None else n
    key = f"evidence/test-{n}.json"
    path = private / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"notes": NOTE}), encoding="utf-8")
    payload = {"instructor": instructor, "unit": UNIT, "observer": observer, "length": "full", "lead": True,
               "mode": "in-person", "rubric_version": RUBRIC, "scores": {d: score for d in DOMAINS}}
    if note:
        payload["evidence_ref"] = key
    return put(private, events.make_event(
        "observation", instructor, observer, payload,
        id=tm_signoff.input_sha256(["bench-obs", observer, instructor, day, n])[:32], at=f"{day}T10:00:00+00:00"))


def build_world(base):
    """The example roster; the SME (K7) at level cleared with two observations in the last two months, from two
    observers, and a clearance; P3 and C5 clearers."""
    private = make_fictional_store(base)
    roster = base / "roster-in.yaml"
    roster.write_text(EXAMPLE_ROSTER_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    import_roster_ungated(private, roster, T0)
    set_level(private, K7, "cleared")
    for c in (P3, C5):
        set_level(private, c, "clearer")
    obs(private, P3, "2026-09-12")
    obs(private, C5, "2026-10-02")
    hold(private, K7)


@pytest.fixture
def world(fictional_store, cached_world):
    cached_world("bench_world", build_world)
    return fictional_store


@pytest.fixture
def bare(fictional_store, example_roster):
    """The example roster imported and nothing else."""
    import_roster_ungated(fictional_store, example_roster, T0)
    return fictional_store


def run(private, now=T0):
    return app.do_run(private, now=now)


def benches(private):
    return [e for e in log(private) if e["kind"] == "subject" and e["payload"]["subject_kind"] == "bench"]


def bench_uris(private):
    return [e["subject_uri"] for e in benches(private)]


def steps(private, step, subject=BENCH):
    return [e for e in of_kind(private, "step", subject) if e["payload"].get("step") == step]


def decision_event(bench_uri, instructor, decision="renew", *, at="2026-11-01T09:00:00+00:00"):
    payload = {"bench": bench_uri, "instructor": instructor, "decision": decision, "rationale_key": "bench/x.json",
               "evidence_pack_sha256": "ab" * 32, "decided_by": HOT, "signoff_id": "cd" * 8}
    return events.make_event("bench_decision", bench_uri, HOT, payload, at=at)


def cycle(private, instructor=K7, number=1, intensity="triggered", at="2026-10-01T09:00:00+00:00"):
    slug = instructor.split("/")[1]
    attrs = {"instructor": instructor, "coach": P3, "number": number, "intensity": intensity,
             "focus": ["technical-depth"]}
    if intensity == "triggered":
        attrs["trigger"] = "score-drop"
    return put(private, events.make_event(
        "subject", f"tm:cycle/{slug}--{number}", workflow.SYSTEM_ACTOR,
        {"subject_kind": "cycle", "attrs": attrs, "opened_by": "tm:step/open-cycles"}, at=at))


def outcome(private, delivery, instructor=K7, day="2026-10-05"):
    """The outcome summary of a delivery, on record once; its numbers trigger nothing (the score is the baseline)."""
    if any(e["kind"] == "outcome" and e["payload"]["delivery_ref"] == delivery for e in log(private)):
        return None
    return put(private, events.make_event(
        "outcome", instructor, workflow.SYSTEM_ACTOR,
        {"delivery_ref": delivery, "instructor": instructor, "unit": UNIT, "mode": "in-person", "delivered_on": day,
         "learners_assessed": 40, "score": 80.0, "baseline": 80.0, "source": "tm:test/bench"},
        id=quality.outcome_id(delivery), at=f"{day}T18:00:00+00:00"))


def trigger(private, n, instructor=K7, at="2026-10-10T09:00:00+00:00", *, reason=quality.SCORE_DROP, delivery=None):
    """An outcome-based trigger `check` as quality-review writes it: its id derives from (instructor, reason, the delivery
    that completed it), and that delivery's outcome is on record (`d<n>` unless named)."""
    delivery = delivery or f"d{n}"
    outcome(private, delivery, instructor)
    return put(private, events.make_event(
        "check", instructor, workflow.SYSTEM_ACTOR,
        {"step": QR, "instructor": instructor, "result": "trigger", "trigger": reason},
        id=quality.trigger_id(instructor, reason, delivery), at=at))


def observed_trigger(private, which=0, instructor=K7, at="2026-10-12T09:00:00+00:00", domain="technical-depth"):
    """A `domain-one-confirmed` trigger (a domain scored 1, confirmed by a second observer): the teaching evidence an outcome
    trigger alone lacks. Its id derives from the observation that completed it, the `which`-th of the instructor's."""
    mine = [e for e in of_kind(private, "observation") if e["payload"]["instructor"] == instructor]
    key = f"{mine[which]['id']}|{domain}"
    return put(private, events.make_event(
        "check", instructor, workflow.SYSTEM_ACTOR,
        {"step": QR, "instructor": instructor, "result": "trigger", "trigger": quality.DOMAIN_ONE, "domain": domain},
        id=quality.trigger_id(instructor, quality.DOMAIN_ONE, key), at=at))


def closed(private, number=1, change=0, instructor=K7, at="2026-09-28T09:00:00+00:00"):
    """The `closed` phase of the instructor's cycle `number` (as `cycle` opens it, triggered), with the change in its focus
    domain: 0 or less is a cycle that did not improve it."""
    slug = instructor.split("/")[1]
    uri = f"tm:cycle/{slug}--{number}"
    return put(private, events.make_event(
        "coaching_cycle", uri, workflow.SYSTEM_ACTOR,
        {"cycle": uri, "instructor": instructor, "coach": P3, "number": number, "intensity": "triggered",
         "focus": ["technical-depth"], "phase": "closed", "change": {"technical-depth": change}},
        id=tm_signoff.input_sha256(["closed", uri])[:32], at=at))


# --- the workflow file and the record ----------------------------------------------------------------------------------


def test_the_bench_workflow_defines_its_steps():
    wf = {w["id"]: w for w in STD["workflows"]["workflows"]}["tm:workflow/bench"]
    shape = {s["id"]: (s["type"], s["role"], s["subject"], tuple(s["needs"])) for s in wf["steps"]}
    assert shape == {
        OPEN: ("auto", "head-of-training", "programme", ("tm:step/roster-import",)),
        PACK: ("auto", "head-of-training", "bench", ()),
        READY: ("auto", "head-of-training", "bench", (PACK,)),
        DECISION: ("human", "head-of-training", "bench", (READY,)),
    }
    decision = next(s for s in wf["steps"] if s["id"] == DECISION)
    assert decision["done_when"]["bind"] == "input" and decision["page"] == "approve"
    assert set(wf["event_kinds"]) >= {"step", "signoff", "subject", "check", "level_change", "bench_decision"}


def test_every_bench_step_has_its_runner_or_builder():
    from teachermodel import flows

    assert flows.AUTO_STEPS[OPEN].per == "programme" and flows.AUTO_STEPS[OPEN].refresh
    assert flows.AUTO_STEPS[PACK].per == "bench" and flows.AUTO_STEPS[PACK].refresh
    assert flows.AUTO_STEPS[READY].per == "bench"
    assert DECISION in flows.PAGE_SPECS and DECISION in flows.CONTENT_CHECKS and DECISION in flows.SIGNOFF_HOOKS


def test_records_bench_joins_the_review_and_its_decision():
    opened = events.make_event(
        "subject", BENCH, workflow.SYSTEM_ACTOR,
        {"subject_kind": "bench", "attrs": {"instructor": K7, "reason": "requested"}, "opened_by": "tm:cli/request-bench"},
        at="2026-10-26T08:00:00+00:00")
    later = events.make_event(
        "subject", "tm:bench/k7m2q--2", workflow.SYSTEM_ACTOR,
        {"subject_kind": "bench", "attrs": {"instructor": K7, "reason": "contract-end"}, "opened_by": OPEN},
        at="2027-01-05T08:00:00+00:00")
    other = events.make_event("check", K7, workflow.SYSTEM_ACTOR, {"step": None, "result": "x"})
    decided = decision_event(BENCH, K7, "exit")
    found = records.bench([later, other, decided, opened])
    assert [b["bench"] for b in found] == [BENCH, "tm:bench/k7m2q--2"]
    first, second = found
    assert first["instructor"] == K7 and first["reason"] == "requested" and first["opened"] == date(2026, 10, 26)
    assert first["decision"]["decision"] == "exit" and first["decision"]["at"] == date(2026, 11, 1)
    assert first["decision"]["rationale_key"] == "bench/x.json"
    assert second["decision"] is None and second["reason"] == "contract-end"


def test_records_bench_takes_the_latest_decision_of_a_bench():
    opened = events.make_event(
        "subject", BENCH, workflow.SYSTEM_ACTOR,
        {"subject_kind": "bench", "attrs": {"instructor": K7, "reason": "requested"}, "opened_by": "tm:cli/request-bench"},
        at="2026-10-26T08:00:00+00:00")
    first = decision_event(BENCH, K7, "renew", at="2026-11-01T09:00:00+00:00")
    second = decision_event(BENCH, K7, "exit", at="2026-11-02T09:00:00+00:00")
    assert records.bench([opened, first, second])[0]["decision"]["decision"] == "exit"
    assert records.bench([]) == []


# --- open-bench: the three ways a review starts -----------------------------------------------------------------------


C5_END = date(2026, 12, 31)  # the example roster's contractor engagement ends on this day


@pytest.mark.parametrize("days_before,opens", [(30, True), (31, False), (1, True), (0, True)])
def test_an_engagement_ending_within_30_days_opens_a_bench(bare, days_before, opens):
    run(bare, datetime.combine(C5_END - timedelta(days=days_before), datetime.min.time(), tzinfo=timezone.utc))
    assert bench_uris(bare) == (["tm:bench/c5w1t--1"] if opens else [])
    if opens:
        (e,) = benches(bare)
        assert e["payload"]["attrs"] == {"instructor": C5, "reason": "contract-end"}
        assert e["payload"]["opened_by"] == OPEN


def test_an_engagement_that_has_ended_in_the_roster_opens_nothing(bare, tmp_path):
    doc = yaml.safe_load(EXAMPLE_ROSTER_PATH.read_text(encoding="utf-8"))
    for row in doc["instructors"]:
        if row["instructor"] == C5:
            row["engagement"]["status"] = "ended"
    roster = tmp_path / "ended.yaml"
    roster.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    private = make_fictional_store(other)
    import_roster_ungated(private, roster, T0)
    run(private, datetime(2026, 12, 10, 8, 0, tzinfo=timezone.utc))
    assert bench_uris(private) == []


def test_running_again_does_not_open_a_second_bench(bare):
    day = datetime(2026, 12, 5, 8, 0, tzinfo=timezone.utc)
    run(bare, day)
    run(bare, day + timedelta(days=1))
    assert bench_uris(bare) == ["tm:bench/c5w1t--1"]


def test_a_decided_contract_end_bench_is_not_opened_again_for_the_same_engagement(bare):
    day = datetime(2026, 12, 5, 8, 0, tzinfo=timezone.utc)
    run(bare, day)
    app.append_new(bare, [decision_event("tm:bench/c5w1t--1", C5, "renew", at="2026-12-06T09:00:00+00:00")])
    run(bare, day + timedelta(days=10))
    assert bench_uris(bare) == ["tm:bench/c5w1t--1"]


def test_an_undecided_review_blocks_a_second_one_and_a_decided_one_does_not(bare):
    first = bench.request_bench(bare, instructor=K7, now=T0)
    assert first == bench.Opened("tm:bench/k7m2q--1", True)
    again = bench.request_bench(bare, instructor=K7, now=T0 + timedelta(days=1))
    assert again == bench.Opened("tm:bench/k7m2q--1", False) and len(bench_uris(bare)) == 1
    app.append_new(bare, [decision_event("tm:bench/k7m2q--1", K7, "renew")])
    second = bench.request_bench(bare, instructor=K7, now=T0 + timedelta(days=30))
    assert second == bench.Opened("tm:bench/k7m2q--2", True)  # n increments with each occasion


def test_an_outcome_trigger_and_an_observation_trigger_on_a_triggered_cycle_open_a_bench(world):
    cycle(world)
    trigger(world, 1)
    run(world)
    assert bench_uris(world) == []
    observed_trigger(world, at="2026-10-15T09:00:00+00:00")
    run(world)
    (e,) = benches(world)
    assert e["subject_uri"] == BENCH and e["payload"]["attrs"] == {"instructor": K7, "reason": "repeated-trigger"}


def test_a_closed_triggered_cycle_that_did_not_improve_is_teaching_evidence(world):
    """Integration review finding 1: two outcome triggers open a review only with teaching evidence; a triggered cycle that
    closed with no gain in its focus domains is one kind of it."""
    cycle(world, number=1, at="2026-09-01T09:00:00+00:00")
    closed(world, 1, change=0)
    cycle(world, number=2, at="2026-10-01T09:00:00+00:00")
    trigger(world, 1)
    trigger(world, 2, at="2026-10-15T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == [BENCH]


@pytest.mark.parametrize("change", [1, 0.5])
def test_a_closed_cycle_that_improved_its_focus_is_not_teaching_evidence(world, change):
    cycle(world, number=1, at="2026-09-01T09:00:00+00:00")
    closed(world, 1, change=change)
    cycle(world, number=2, at="2026-10-01T09:00:00+00:00")
    trigger(world, 1)
    trigger(world, 2, at="2026-10-15T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == []


def test_an_outcome_alone_never_opens_a_bench(world):
    """Integration review finding 1. The latest cycle is triggered and two outcome triggers came after it, on two
    deliveries: the old rule opened a review here. With no observation trigger and no triggered cycle that closed without a
    gain, none opens (pinned by mutation: dropping the teaching-evidence condition from `_repeated_trigger` fails this test)."""
    cycle(world)
    trigger(world, 1)
    trigger(world, 2, at="2026-10-15T09:00:00+00:00", reason=quality.FEEDBACK)
    trigger(world, 3, at="2026-10-16T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == []


def test_two_outcome_triggers_of_one_delivery_are_not_repeated(world):
    cycle(world, number=1, at="2026-09-01T09:00:00+00:00")
    closed(world, 1, change=0)
    cycle(world, number=2, at="2026-10-01T09:00:00+00:00")
    trigger(world, 1, delivery="d-same")
    trigger(world, 2, delivery="d-same", reason=quality.FEEDBACK, at="2026-10-15T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == []  # two trigger events, one delivery
    trigger(world, 3, at="2026-10-16T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == [BENCH]


def test_a_trigger_whose_delivery_cannot_be_traced_does_not_count(world):
    cycle(world)
    observed_trigger(world)
    put(world, events.make_event(
        "check", K7, workflow.SYSTEM_ACTOR, {"step": QR, "instructor": K7, "result": "trigger", "trigger": quality.SCORE_DROP},
        id=tm_signoff.input_sha256(["untraced"])[:32], at="2026-10-15T09:00:00+00:00"))
    run(world)
    assert bench_uris(world) == []


def test_triggers_on_a_standard_cycle_do_not_open_a_bench(world):
    cycle(world, intensity="standard")
    trigger(world, 1)
    observed_trigger(world, at="2026-10-15T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == []


def test_only_the_latest_cycle_counts(world):
    cycle(world, number=1, intensity="triggered", at="2026-09-01T09:00:00+00:00")
    trigger(world, 1, at="2026-09-05T09:00:00+00:00")
    observed_trigger(world, at="2026-09-10T09:00:00+00:00")
    cycle(world, number=2, intensity="standard", at="2026-10-01T09:00:00+00:00")  # the trigger cycle closed; a standard one
    run(world)
    assert bench_uris(world) == []


def test_triggers_before_the_cycle_opened_do_not_count(world):
    trigger(world, 1, at="2026-09-01T09:00:00+00:00")
    observed_trigger(world, at="2026-09-02T09:00:00+00:00")
    cycle(world)  # triggered, but opened after both
    trigger(world, 3, at="2026-10-15T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == []


def test_triggers_of_another_instructor_or_another_kind_do_not_count(world):
    cycle(world)
    observed_trigger(world)
    trigger(world, 2, instructor=P3)
    put(world, events.make_event("check", K7, workflow.SYSTEM_ACTOR,
                                 {"step": QR, "instructor": K7, "result": "clear"}, at="2026-10-12T09:00:00+00:00"))
    put(world, events.make_event("check", K7, workflow.SYSTEM_ACTOR,
                                 {"step": "tm:step/other", "result": "trigger"}, at="2026-10-12T09:00:00+00:00"))
    run(world)
    assert bench_uris(world) == []


def test_triggers_already_answered_by_an_earlier_bench_do_not_count_again(world):
    cycle(world)
    observed_trigger(world, 0)
    trigger(world, 2, at="2026-10-15T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == [BENCH]
    app.append_new(world, [decision_event(BENCH, K7, "renew", at="2026-10-27T09:00:00+00:00")])
    run(world, T0 + timedelta(days=2))
    assert bench_uris(world) == [BENCH]  # the same two triggers
    trigger(world, 3, at="2026-11-02T09:00:00+00:00")
    run(world, T0 + timedelta(days=8))
    assert bench_uris(world) == [BENCH]  # one new trigger is not two
    observed_trigger(world, 1, at="2026-11-03T09:00:00+00:00")
    run(world, T0 + timedelta(days=9))
    assert bench_uris(world) == [BENCH, "tm:bench/k7m2q--2"]


def test_a_cycle_that_closed_before_the_latest_review_is_not_new_teaching_evidence(world):
    cycle(world, number=1, at="2026-09-01T09:00:00+00:00")
    closed(world, 1, change=0)
    cycle(world, number=2, at="2026-10-01T09:00:00+00:00")
    trigger(world, 1)
    trigger(world, 2, at="2026-10-15T09:00:00+00:00")
    run(world)
    assert bench_uris(world) == [BENCH]
    app.append_new(world, [decision_event(BENCH, K7, "renew", at="2026-10-27T09:00:00+00:00")])
    trigger(world, 3, at="2026-11-02T09:00:00+00:00")
    trigger(world, 4, at="2026-11-03T09:00:00+00:00")
    run(world, T0 + timedelta(days=9))
    assert bench_uris(world) == [BENCH]  # the unimproved cycle was the evidence of the first review


def test_an_exited_instructor_gets_no_new_review(bare):
    """Integration review finding 2: open-bench skips an instructor whose latest blocking decision is an exit."""
    app.append_new(bare, [*_requested_and_decided(C5, "exit", at="2026-11-20T09:00:00+00:00")])
    run(bare, datetime(2026, 12, 5, 8, 0, tzinfo=timezone.utc))  # C5's engagement ends within 30 days
    assert bench_uris(bare) == ["tm:bench/c5w1t--1"]


def test_a_returned_instructor_still_gets_a_contract_end_review(bare):
    app.append_new(bare, [*_requested_and_decided(C5, "return-to-co-teaching", at="2026-11-20T09:00:00+00:00")])
    run(bare, datetime(2026, 12, 5, 8, 0, tzinfo=timezone.utc))
    assert bench_uris(bare) == ["tm:bench/c5w1t--1", "tm:bench/c5w1t--2"]


def _requested_and_decided(instructor, decision, *, at):
    uri = bench.bench_uri(instructor, 1)
    opened = events.make_event(
        "subject", uri, workflow.SYSTEM_ACTOR,
        {"subject_kind": "bench", "attrs": {"instructor": instructor, "reason": "requested"}, "opened_by": bench.OPENED_BY_CLI},
        at="2026-11-01T09:00:00+00:00")
    return [opened, decision_event(uri, instructor, decision, at=at)]


# --- ids derive from the content (integration review finding 15) ---------------------------------------------------------


def test_blocked_checks_get_the_same_id_from_the_same_log(bare, tmp_path):
    import shutil

    bench.request_bench(bare, instructor=K7, now=T0)
    copy = tmp_path / "copy"
    shutil.copytree(bare, copy)
    run(bare)
    run(copy)

    def blocked_ids(private):
        return sorted(e["id"] for e in log(private) if e["kind"] == "check" and e["payload"].get("result") == "blocked"
                      and e["payload"].get("step") in (READY, "tm:step/open-cycles"))

    assert len(blocked_ids(bare)) >= 2 and blocked_ids(bare) == blocked_ids(copy)  # bench-ready and open-cycles
    ready = [e for e in log(bare) if e["kind"] == "check" and e["payload"].get("step") == READY]
    assert len(ready) == 1 and ready[0]["subject_uri"] == BENCH


def test_a_blocked_check_that_returns_to_earlier_reasons_is_written_again(world):
    from teachermodel import signoff
    from teachermodel.flows.common import blocked_check

    def blocked(st, reasons):
        return blocked_check(st, READY, BENCH, reasons, T0, seed="bench_blocked")

    st = app.load_state(world)
    first = blocked(st, ["a"])
    st = app.advance_state(st, first)
    second = blocked(st, ["b"])
    st = app.advance_state(st, second)
    third = blocked(st, ["a"])
    assert len({first[0]["id"], second[0]["id"], third[0]["id"]}) == 3
    assert blocked(app.advance_state(st, third), ["a"]) == []
    again = blocked(app.load_state(world), ["a"])
    assert again[0]["id"] == first[0]["id"]  # the same log gives the same id
    # The seeds keep the ids each flow wrote before the helper was shared.
    assert first[0]["id"] == signoff.input_sha256({"bench_blocked": [BENCH, READY, ["a"], 0]})[:32]
    obs_first = blocked_check(app.load_state(world), "tm:step/release", BENCH, ["a"], T0)
    assert obs_first[0]["id"] == signoff.input_sha256({"blocked": [BENCH, "tm:step/release", ["a"], 0]})[:32]


# --- request-bench ---------------------------------------------------------------------------------------------------


def test_request_bench_opens_a_review_with_reason_requested(bare):
    opened = bench.request_bench(bare, instructor=K7, now=T0)
    assert opened.created and opened.bench == BENCH
    (e,) = benches(bare)
    assert e["payload"] == {"subject_kind": "bench", "attrs": {"instructor": K7, "reason": "requested"},
                            "opened_by": "tm:cli/request-bench"}
    assert events.check_event(e) == []


def test_request_bench_takes_a_bare_slug_and_refuses_an_unregistered_instructor(bare):
    assert bench.request_bench(bare, instructor="k7m2q", now=T0).bench == BENCH
    with pytest.raises(bench.BenchError, match="registered"):
        bench.request_bench(bare, instructor="tm:instructor/zz9top", now=T0)
    with pytest.raises(bench.BenchError, match="registered"):
        bench.request_bench(bare, instructor="not an instructor", now=T0)


def test_the_request_bench_command(bare, capsys):
    argv = ["request-bench", "--private-dir", str(bare), "--instructor", K7]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert BENCH in out and "opened" in out and "already open" not in out
    assert cli.main(argv) == 0
    assert "already open" in capsys.readouterr().out
    assert cli.main([*argv[:-1], "tm:instructor/zz9top"]) == 1
    assert "registered" in capsys.readouterr().err
    assert bench_uris(bare) == [BENCH]


# --- evidence-pack -------------------------------------------------------------------------------------------------------


def pack_file(private, slug="k7m2q--1"):
    return private / "generated" / "bench" / f"{slug}.html"


def requested(private):
    bench.request_bench(private, instructor=K7, now=T0)
    run(private)
    return private


def test_the_pack_is_one_self_contained_html_file_whose_sha_is_in_a_step_event(world):
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    for external in ("http://", "https://", "src=", "<link", "@import"):
        assert external not in html, external
    (done,) = steps(world, PACK)
    assert done["payload"]["output"] == "generated/bench/k7m2q--1.html"
    assert done["payload"]["evidence_pack_sha256"] == hashlib.sha256(pack_file(world).read_bytes()).hexdigest()
    assert events.check_event(done) == []


def test_the_pack_shows_clearances_and_observations_with_domain_scores(world):
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    (clearance_event,) = [e for e in of_kind(world, "clearance") if e["payload"]["instructor"] == K7]
    assert clearance_event["payload"]["clearance"] in html and UNIT in html
    for o in of_kind(world, "observation"):
        assert o["id"] in html and o["payload"]["observer"] in html
    for domain in DOMAINS:
        assert domain in html
    assert "2 distinct observers" in html


def test_the_pack_holds_references_to_notes_never_the_notes(world):
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    assert "evidence/test-0.json" in html and NOTE not in html
    assert NOTE not in (world / "events" / "events.jsonl").read_text(encoding="utf-8")


def test_the_pack_names_the_instructor_by_uri_only(world, fictional_names):
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    assert K7 in html
    for needle in fictional_names:
        assert needle not in html, needle


def test_the_pack_shows_only_the_observations_of_the_window_and_of_the_instructor(world):
    obs(world, R8, "2026-03-01")  # older than the 180-day window
    obs(world, R8, "2026-10-05", instructor=P3)  # somebody else's
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    ids = {o["id"]: o for o in of_kind(world, "observation")}
    inside = [i for i, o in ids.items() if o["payload"]["instructor"] == K7 and o["at"] >= "2026-04-29"]
    outside = [i for i in ids if i not in inside]
    assert len(inside) == 2 and len(outside) == 2
    assert all(i in html for i in inside) and not any(i in html for i in outside)


def test_the_pack_shows_the_real_records_of_the_quality_loop(world):
    # Increment 3 integration: every adapter is written, so the pack reads real events, not fakes. One of each kind for K7
    # (an outcome above the learner minimum, a closed coaching cycle, a CPD activity, an audit of a window observation)
    # and one for somebody else, which the pack leaves out.
    first = of_kind(world, "observation")[0]["id"]
    put(world, events.make_event(
        "outcome", K7, workflow.SYSTEM_ACTOR,
        {"delivery_ref": "delivery-real-1", "instructor": K7, "unit": UNIT, "mode": "in-person",
         "delivered_on": "2026-10-03", "learners_assessed": 22, "score": 68.25, "baseline": 70.0, "source": "lms-test"},
        at="2026-10-04T09:00:00+00:00"))
    put(world, events.make_event(
        "outcome", P3, workflow.SYSTEM_ACTOR,
        {"delivery_ref": "delivery-real-other", "instructor": P3, "unit": UNIT, "mode": "in-person",
         "delivered_on": "2026-10-03", "learners_assessed": 22, "score": 61.0, "baseline": 70.0, "source": "lms-test"},
        at="2026-10-04T09:00:00+00:00"))
    cycle(world, intensity="standard", at="2026-09-20T09:00:00+00:00")
    put(world, events.make_event(
        "coaching_cycle", "tm:cycle/k7m2q--1", workflow.SYSTEM_ACTOR,
        {"cycle": "tm:cycle/k7m2q--1", "instructor": K7, "coach": P3, "number": 1, "intensity": "standard",
         "focus": ["technical-depth"], "phase": "closed", "change": {"technical-depth": 1.5}},
        at="2026-10-15T09:00:00+00:00"))
    put(world, events.make_event(
        "cpd", K7, K7,
        {"instructor": K7, "activity_key": "cpd/activity-real.json", "domains": ["technical-depth"], "hours": 2.75,
         "logged_on": "2026-10-12", "signoff_id": "ab" * 8},
        at="2026-10-12T09:00:00+00:00"))
    put(world, events.make_event(
        "audit", "tm:sample/2026q4--real", workflow.SYSTEM_ACTOR,
        {"sample": "tm:sample/2026q4--real", "observation": first, "observer": P3, "second_observer": C5,
         "within_one_share": 0.875, "exact_share": 0.625, "agreed": True, "referred_to_calibration": False,
         "signoff_id": "ef" * 8},
        at="2026-10-20T09:00:00+00:00"))
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    assert "not available" not in html
    assert "delivery-real-1" in html and "68.25" in html and "delivery-real-other" not in html
    assert "tm:cycle/k7m2q--1" in html and "1.5" in html
    assert "cpd/activity-real.json" in html and "2.75" in html
    assert first in html and "0.875" in html and "0.625" in html


def test_the_pack_shows_outcome_summaries_above_the_minimum_learner_count_only(world, monkeypatch):
    minimum = STD["rules"]["quality"]["min_learners_for_metric"]
    shown = rules.Outcome("delivery-shown", K7, date(2026, 10, 1), minimum, 71.5, 70.0)
    hidden = rules.Outcome("delivery-hidden", K7, date(2026, 10, 8), minimum - 1, 12.5, 70.0)
    elsewhere = rules.Outcome("delivery-other", P3, date(2026, 10, 9), 40, 65.0, 70.0)
    monkeypatch.setattr(records, "outcomes", lambda ev: [shown, hidden, elsewhere])
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    assert "delivery-shown" in html and "71.5" in html
    assert "delivery-hidden" not in html and "12.5" not in html and "delivery-other" not in html
    assert f"1 delivery below the minimum of {minimum} learners" in html


def test_the_pack_shows_coaching_history_cpd_and_audits_of_the_instructor(world, monkeypatch):
    cycles = [{"cycle": "tm:cycle/k7m2q--1", "instructor": K7, "coach": P3, "number": 1, "intensity": "triggered",
               "focus": ["technical-depth"], "trigger": "score-drop", "phase": "closed", "opened": date(2026, 10, 1),
               "closed": date(2026, 10, 20), "change": {"technical-depth": 1}},
              {"cycle": "tm:cycle/p3x9d--1", "instructor": P3, "coach": C5, "number": 1, "intensity": "standard",
               "focus": ["prior-knowledge"], "trigger": None, "phase": "closed", "opened": date(2026, 10, 1),
               "closed": date(2026, 10, 20), "change": None}]
    cpd = [{"id": "cpd-1", "instructor": K7, "activity_key": "cpd/activity-777.json", "domains": ["technical-depth"],
            "hours": 3.5, "logged_on": date(2026, 10, 12), "signoff_id": "ab" * 8},
           {"id": "cpd-2", "instructor": P3, "activity_key": "cpd/activity-other.json", "domains": ["prior-knowledge"],
            "hours": 1.0, "logged_on": date(2026, 10, 12), "signoff_id": "cd" * 8}]
    first = of_kind(world, "observation")[0]["id"]
    audits = [{"id": "aud-1", "sample": "tm:sample/2026Q4--x", "observation": first, "observer": P3, "second_observer": C5,
               "within_one_share": 0.95, "exact_share": 0.7, "agreed": True, "referred_to_calibration": False,
               "signoff_id": "ef" * 8, "at": date(2026, 10, 20)},
              {"id": "aud-2", "sample": "tm:sample/2026Q4--y", "observation": "someone-elses-observation", "observer": R8,
               "second_observer": C5, "within_one_share": 0.5, "exact_share": 0.1, "agreed": False,
               "referred_to_calibration": True, "signoff_id": "01" * 8, "at": date(2026, 10, 20)}]
    monkeypatch.setattr(records, "cycles", lambda ev: cycles)
    monkeypatch.setattr(records, "cpd", lambda ev: cpd)
    monkeypatch.setattr(records, "audits", lambda ev: audits)
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8")
    assert "tm:cycle/k7m2q--1" in html and "tm:cycle/p3x9d--1" not in html
    assert "cpd/activity-777.json" in html and "3.5" in html and "cpd/activity-other.json" not in html
    assert "aud-1" in html and "aud-2" not in html


def test_the_pack_says_it_is_a_training_record_and_not_for_performance_review(world):
    requested(world)
    html = pack_file(world).read_text(encoding="utf-8").lower()
    assert "technical training function" in html and "performance review" in html


def test_a_second_run_with_the_same_evidence_changes_nothing(world):
    requested(world)
    before = pack_file(world).read_bytes()
    run(world, T0 + timedelta(days=1))
    assert pack_file(world).read_bytes() == before
    assert len(steps(world, PACK)) == 1 and len(steps(world, READY)) == 1


def test_new_evidence_makes_a_new_pack_until_the_bench_is_decided(world):
    requested(world)
    (first,) = steps(world, PACK)
    obs(world, R8, "2026-10-20")
    run(world, T0 + timedelta(hours=1))
    second = steps(world, PACK)[-1]
    assert len(steps(world, PACK)) == 2
    assert second["payload"]["evidence_pack_sha256"] != first["payload"]["evidence_pack_sha256"]
    assert second["payload"]["evidence_pack_sha256"] == hashlib.sha256(pack_file(world).read_bytes()).hexdigest()
    app.append_new(world, [decision_event(BENCH, K7, "renew", at="2026-10-26T12:00:00+00:00")])
    obs(world, R8, "2026-10-24")
    run(world, T0 + timedelta(hours=5))
    assert len(steps(world, PACK)) == 2  # the pack a decision rested on stays as it was


# --- bench-ready ------------------------------------------------------------------------------------------------------------


def test_bench_ready_waits_for_the_evidence_pack(world):
    bench.request_bench(world, instructor=K7, now=T0)
    st = app.load_state(world)
    assert workflow.unmet_needs(st.workflows, st.events, st.subjects, READY, BENCH) == [PACK]


def test_bench_ready_needs_two_current_observers(bare):
    obs(bare, P3, "2026-10-02")
    obs(bare, P3, "2026-10-09")  # one observer twice is one observer
    obs(bare, R8, "2026-03-01")  # the second observer's observation is older than the window
    bench.request_bench(bare, instructor=K7, now=T0)
    run(bare)
    assert steps(bare, PACK) and not steps(bare, READY)
    (check,) = [e for e in of_kind(bare, "check", BENCH) if e["payload"].get("step") == READY]
    assert check["payload"]["result"] == "blocked" and "1 current observers; need 2" in check["payload"]["reasons"][0]
    run(bare)
    assert len([e for e in of_kind(bare, "check", BENCH) if e["payload"].get("step") == READY]) == 1  # said once
    obs(bare, C5, "2026-10-12")
    run(bare, T0 + timedelta(hours=1))
    (ready,) = steps(bare, READY)
    assert ready["payload"]["evidence_pack_sha256"] == steps(bare, PACK)[-1]["payload"]["evidence_pack_sha256"]


def test_bench_ready_is_done_with_two_current_observers(world):
    requested(world)
    assert len(steps(world, READY)) == 1
    due = {(d.step, d.subject) for d in app.due_steps(app.load_state(world), T0.date())}
    assert (DECISION, BENCH) in due and (READY, BENCH) not in due


def test_a_bench_without_two_observers_has_no_decision_due(bare):
    obs(bare, P3, "2026-10-02")
    bench.request_bench(bare, instructor=K7, now=T0)
    run(bare)
    due = {(d.step, d.subject) for d in app.due_steps(app.load_state(bare), T0.date())}
    assert (DECISION, BENCH) not in due


# --- bench-decision -------------------------------------------------------------------------------------------------------


def decision_spec(private, bench_uri=BENCH):
    return app._page_specs(app.load_state(private), DECISION, bench_uri)[0]


def test_the_decision_page_defaults_to_return_to_co_teaching_for_a_teaching_quality_reason(world):
    cycle(world)
    trigger(world, 1)
    observed_trigger(world, at="2026-10-15T09:00:00+00:00")
    run(world)
    spec = decision_spec(world)
    field = next(f for f in spec["fields"] if f["name"] == "decision")
    assert field["options"] == ["renew", "convert", "return-to-co-teaching", "exit"]
    assert field["value"] == "return-to-co-teaching" and field["required"] is True
    assert spec["inputs"]["reason"] == "repeated-trigger"


def test_the_decision_page_has_no_default_for_a_contract_end_or_a_request(world):
    requested(world)
    spec = decision_spec(world)
    field = next(f for f in spec["fields"] if f["name"] == "decision")
    assert "value" not in field  # reason: requested
    assert "requested by the head of training" in spec["intro"]  # finding 19: the page says why it opened
    assert "concern" not in spec["inputs"]


@pytest.mark.parametrize("concern,default", [("teaching-quality", "return-to-co-teaching"), ("other", None)])
def test_a_request_with_a_concern_carries_it_and_teaching_quality_defaults_the_decision(world, concern, default):
    """Integration review finding 19: request-bench takes an optional concern; a teaching-quality concern defaults the decision
    to return to co-teaching (spec W10), any other has no default."""
    opened = bench.request_bench(world, instructor=K7, concern=concern, now=T0)
    (e,) = benches(world)
    assert e["payload"]["attrs"] == {"instructor": K7, "reason": "requested", "concern": concern}
    assert events.check_event(e) == [] and opened.bench == BENCH
    run(world)
    spec = decision_spec(world)
    field = next(f for f in spec["fields"] if f["name"] == "decision")
    assert field.get("value") == default
    assert spec["inputs"]["concern"] == concern and concern.replace("-", " ") in spec["intro"]


def test_request_bench_refuses_an_unknown_concern(bare, capsys):
    with pytest.raises(bench.BenchError, match="concern"):
        bench.request_bench(bare, instructor=K7, concern="performance", now=T0)
    assert bench_uris(bare) == []
    argv = ["request-bench", "--private-dir", str(bare), "--instructor", K7, "--concern", "teaching-quality"]
    assert cli.main(argv) == 0 and benches(bare)[0]["payload"]["attrs"]["concern"] == "teaching-quality"


def test_the_decision_page_carries_the_pack_hash_and_asks_for_a_private_rationale(world):
    requested(world)
    spec = decision_spec(world)
    assert spec["inputs"]["evidence_pack_sha256"] == steps(world, PACK)[-1]["payload"]["evidence_pack_sha256"]
    assert spec["inputs"]["evidence_pack"] == "generated/bench/k7m2q--1.html"
    rationale = next(f for f in spec["fields"] if f["name"] == "rationale")
    assert rationale["kind"] == "textarea" and rationale["required"] is True
    assert spec["role"] == "head-of-training" and spec["signer"] == HOT


def fields(decision="renew", rationale="The reasons, in private words"):
    return {"decision": decision, "rationale": rationale}


def test_a_decision_needs_a_known_decision_and_a_rationale(world):
    requested(world)
    assert reasons(world, DECISION, HOT, fields(), subject=BENCH) == []
    assert any("decision" in r for r in reasons(world, DECISION, HOT, fields("promote"), subject=BENCH))
    assert any("decision" in r for r in reasons(world, DECISION, HOT, {"rationale": "x"}, subject=BENCH))
    assert any("rationale" in r for r in reasons(world, DECISION, HOT, fields(rationale="   "), subject=BENCH))
    assert any("rationale" in r for r in reasons(world, DECISION, HOT, {"decision": "renew"}, subject=BENCH))


def test_only_the_head_of_training_decides_and_never_for_themselves(world):
    requested(world)
    assert signers(world, DECISION, BENCH) == [HOT]
    assert any("head of training" in r for r in reasons(world, DECISION, "tm:person/coord-1", fields(), subject=BENCH))
    path = world / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/hot-k7", "name": "Head Who Instructs", "email": "head.k7@example.com",
                          "roles": ["head-of-training"], "instructor": K7})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert signers(world, DECISION, BENCH) == [HOT]  # the head who is the instructor reviewed does not get the page
    assert any("instructor" in r for r in reasons(world, DECISION, "tm:person/hot-k7", fields(), subject=BENCH))


def test_the_evidence_must_still_be_ready_on_the_day_of_signing(world):
    requested(world)
    late = "2027-05-01T09:00:00+00:00"  # both observations are older than 180 days by then
    assert any("current observers" in r for r in reasons(world, DECISION, HOT, fields(), subject=BENCH, at=late))


def test_a_decision_writes_the_bench_decision_event_and_keeps_the_rationale_private(world):
    requested(world)
    signed = decide(world, DECISION, HOT, fields("renew", "Strong delivery; renew for a year"), subject=BENCH)
    (event,) = of_kind(world, "bench_decision", BENCH)
    p = event["payload"]
    assert events.check_event(event) == []
    assert p["bench"] == BENCH and p["instructor"] == K7 and p["decision"] == "renew"
    assert p["decided_by"] == HOT and p["signoff_id"] == signed["payload"]["signoff_id"]
    assert p["evidence_pack_sha256"] == steps(world, PACK)[-1]["payload"]["evidence_pack_sha256"]
    private_doc = json.loads((world / p["rationale_key"]).read_text(encoding="utf-8"))
    assert private_doc["rationale"] == "Strong delivery; renew for a year" and private_doc["decision"] == "renew"
    assert "Strong delivery" not in (world / "events" / "events.jsonl").read_text(encoding="utf-8")
    assert records.bench(log(world))[0]["decision"]["decision"] == "renew"


def level_changes(private, instructor=K7):
    return [e for e in of_kind(private, "level_change", instructor)]


def level_of(private, instructor=K7):
    return app.current_level(app.load_state(private), instructor)


def test_return_to_co_teaching_lowers_the_level_by_the_hook(world):
    requested(world)
    before = len(level_changes(world))
    assert level_of(world) == "cleared"
    signed = decide(world, DECISION, HOT, fields("return-to-co-teaching"), subject=BENCH)
    new = level_changes(world)[before:]
    assert len(new) == 1 and events.check_event(new[0]) == []
    assert new[0]["payload"]["from"] == "cleared" and new[0]["payload"]["to"] == "co-deliver"
    assert signed["payload"]["signoff_id"] in new[0]["payload"]["basis"] and new[0]["actor"] == HOT
    assert level_of(world) == "co-deliver"


def test_return_to_co_teaching_from_a_clearer_also_lowers_to_co_deliver(world):
    set_level(world, K7, "clearer", at="2026-10-26T07:30:00+00:00")
    requested(world)
    decide(world, DECISION, HOT, fields("return-to-co-teaching"), subject=BENCH)
    assert level_of(world) == "co-deliver"


@pytest.mark.parametrize("level", ["co-deliver", "shadow"])
def test_return_to_co_teaching_changes_nothing_for_an_instructor_already_there(world, level):
    set_level(world, K7, level, at="2026-10-26T07:30:00+00:00")
    requested(world)
    before = len(level_changes(world))
    decide(world, DECISION, HOT, fields("return-to-co-teaching"), subject=BENCH)
    assert len(level_changes(world)) == before and level_of(world) == level


@pytest.mark.parametrize("decision", ["renew", "convert"])
def test_renew_and_convert_change_no_level(world, decision):
    requested(world)
    before = len(level_changes(world))
    decide(world, DECISION, HOT, fields(decision), subject=BENCH)
    assert len(level_changes(world)) == before and level_of(world) == "cleared"
    assert of_kind(world, "bench_decision", BENCH)[0]["payload"]["decision"] == decision


def test_exit_writes_no_level_change_and_closes_the_instructors_candidates_by_a_check(world):
    requested(world)
    candidates = sorted(u for u, i in app.load_state(world).subjects.items()
                        if i["kind"] == "candidate" and i["instructor"] == K7)
    assert len(candidates) == 2  # in-person and hybrid
    before = len(level_changes(world))
    decide(world, DECISION, HOT, fields("exit"), subject=BENCH)
    assert len(level_changes(world)) == before and level_of(world) == "cleared"  # the spec has no 'exited' level
    closed = sorted(e["subject_uri"] for e in log(world)
                    if e["kind"] == "check" and e["payload"].get("step") == DECISION and e["payload"].get("result") == "closed")
    assert closed == candidates
    one = next(e for e in log(world) if e["kind"] == "check" and e["payload"].get("result") == "closed")
    assert one["payload"]["bench"] == BENCH and one["payload"]["decision"] == "exit"
    assert events.check_event(one) == []


def test_exit_closes_the_open_coaching_cycle_and_nothing_stays_due_for_the_instructor(world):
    """Decision 0015, integration review finding 3: the engine honours the closed check, so neither the candidates nor an open
    cycle of an exited instructor has a due step."""
    cycle(world)
    requested(world)
    state = app.load_state(world)
    mine = {u for u, i in state.subjects.items() if i.get("instructor") == K7 and i["kind"] in ("candidate", "cycle")}
    assert {d.subject for d in app.due_steps(state, T0.date())} & mine  # the control: something of theirs is due
    decide(world, DECISION, HOT, fields("exit"), subject=BENCH)
    closed_ones = {e["subject_uri"] for e in log(world) if e["kind"] == "check" and e["payload"].get("result") == "closed"}
    assert "tm:cycle/k7m2q--1" in closed_ones
    assert not {d.subject for d in app.due_steps(app.load_state(world), T0.date())} & mine


def test_other_decisions_close_no_candidates(world):
    requested(world)
    decide(world, DECISION, HOT, fields("convert"), subject=BENCH)
    assert not [e for e in log(world) if e["kind"] == "check" and e["payload"].get("result") == "closed"]


def test_a_decision_closes_the_step(world):
    requested(world)
    decide(world, DECISION, HOT, fields(), subject=BENCH)
    due = {(d.step, d.subject) for d in app.due_steps(app.load_state(world), T0.date())}
    assert (DECISION, BENCH) not in due


def test_new_evidence_before_the_decision_changes_the_page_inputs(world):
    requested(world)
    before = tm_signoff.input_sha256(decision_spec(world)["inputs"])
    obs(world, R8, "2026-10-20")
    run(world, T0 + timedelta(hours=1))
    assert tm_signoff.input_sha256(decision_spec(world)["inputs"]) != before  # a stale sign-off is refused by its hash


def test_the_decision_page_is_due_a_fortnight_after_the_bench_opened(world):
    requested(world)
    (due,) = [d for d in app.due_steps(app.load_state(world), T0.date()) if d.step == DECISION]
    assert due.due == T0.date() + timedelta(days=14)


def test_a_decision_through_the_real_mail_round_trip(world):
    requested(world)
    app.do_tick(world, now=T0)
    page = world / "pages" / f"{app.page_stem(DECISION, BENCH, HOT)}.html"
    assert page.is_file()
    doc = signoff(world, DECISION, BENCH, HOT, fields("return-to-co-teaching", "Round trip rationale"), now=T0)
    rep = ingest(world, [doc], now=T0, name="bench")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    (event,) = of_kind(world, "bench_decision", BENCH)
    assert event["payload"]["decision"] == "return-to-co-teaching"
    assert level_of(world) == "co-deliver"
    assert "Round trip rationale" not in (world / "events" / "events.jsonl").read_text(encoding="utf-8")
    assert "Round trip rationale" in (world / event["payload"]["rationale_key"]).read_text(encoding="utf-8")


def test_a_decision_with_no_rationale_is_refused_by_ingest(world):
    requested(world)
    app.do_tick(world, now=T0)
    doc = signoff(world, DECISION, BENCH, HOT, {"decision": "exit", "rationale": ""}, now=T0)
    rep = ingest(world, [doc], now=T0, name="bench")
    assert "1 rejected" in rep.summary and not of_kind(world, "bench_decision", BENCH)


def test_nothing_in_the_queue_or_the_pages_exports_the_pack_to_performance_review(world):
    requested(world)
    app.do_tick(world, now=T0)
    queue = json.dumps(app.queue_document(app.due_steps(app.load_state(world), T0.date()), T0))
    assert "evidence_pack" not in queue and "rationale" not in queue


# --- one decision per review (integration review finding 16) --------------------------------------------------------------


def test_two_approving_bench_decisions_in_one_receipt_keep_the_first(world):
    path = world / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/hot-2", "name": "Second Head", "email": "head.two@example.com",
                          "roles": ["head-of-training"]})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    requested(world)
    app.do_tick(world, now=T0)
    first = signoff(world, DECISION, BENCH, HOT, fields("renew", "First"), now=T0)
    second = signoff(world, DECISION, BENCH, "tm:person/hot-2", fields("exit", "Second"), now=T0)
    rep = ingest(world, [first, second], now=T0, name="two-heads")
    assert "1 signoff" in rep.summary and "1 rejected" in rep.summary, rep.all_lines()
    (event,) = of_kind(world, "bench_decision", BENCH)
    assert event["payload"]["decision"] == "renew"
    assert any("already decided" in r for r in reasons(world, DECISION, "tm:person/hot-2", fields("exit"), subject=BENCH))
