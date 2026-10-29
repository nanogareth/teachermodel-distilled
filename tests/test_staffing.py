"""W4 records and the staffing check: `records.clearances`, `staffing.check` (the pure function the hub calls), the
`teachermodel staffing-check` command, and the gap list reading the clearances (carry-over 15). Fictional data only."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from privacy_helpers import import_roster_ungated

from teachermodel import app, cli, events, records, rules, staffing
from teachermodel.flows import AUTO_STEPS
from teachermodel.standards import load_standards

UNIT = "sl:unit/example-agent-loop@1"
SME = "tm:instructor/k7m2q"  # delivers the example unit in-person and hybrid
CAND = "tm:candidate/k7m2q--example-agent-loop-1--in-person"
T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
CLEARERS = ["tm:instructor/p3x9d", "tm:instructor/c5w1t"]


def clearance_event(cid="0123456789abcdef", *, outcome="cleared", issued="2026-10-20", expires="2027-10-20",
                    recheck=None, conditions=(), modes=("in-person",), at="2026-10-20T10:00:00+00:00",
                    framework_version="0.2.0"):
    payload = {
        "clearance": f"tm:clearance/{cid}", "candidate": CAND, "instructor": SME, "unit": UNIT, "modes": list(modes),
        "outcome": outcome, "conditions": list(conditions), "recheck": recheck, "clearers": CLEARERS,
        "observations": ["obs00001", "obs00002"], "issued": issued, "expires": expires, "framework_version": framework_version,
    }
    event = events.make_event("clearance", CAND, "tm:system/teachermodel", payload, at=at)
    assert events.check_event(event) == []
    return event


# --- records.clearances ---------------------------------------------------------------------------------------------


def test_records_turn_clearance_events_into_rules_clearances():
    (c,) = records.clearances([clearance_event(recheck=None)])
    assert c == rules.Clearance(id="tm:clearance/0123456789abcdef", instructor=SME, unit=UNIT, modes=("in-person",),
                                outcome="cleared", issued=date(2026, 10, 20), expires=date(2027, 10, 20), recheck=None,
                                framework_version="0.2.0")


def test_a_later_event_for_the_same_clearance_supersedes_the_earlier_one():
    first = clearance_event(outcome="cleared_with_conditions", recheck="2026-12-01", conditions=["clearances/x#1"])
    lapsed = clearance_event(outcome="not_yet", recheck="2026-12-01", conditions=["clearances/x#1"],
                             at="2026-12-02T08:00:00+00:00")
    other = clearance_event("fedcba9876543210", issued="2026-10-01", expires="2027-10-01")
    found = records.clearances([first, other, lapsed])
    assert [c.id for c in found] == ["tm:clearance/fedcba9876543210", "tm:clearance/0123456789abcdef"]  # by issued
    assert found[1].outcome == "not_yet" and found[1].recheck == date(2026, 12, 1)


def test_records_ignore_other_kinds_and_incomplete_payloads():
    broken = clearance_event()
    broken = {**broken, "payload": {k: v for k, v in broken["payload"].items() if k != "expires"}}
    other = events.make_event("check", CAND, "tm:system/teachermodel", {"step": None, "result": "x"})
    assert records.clearances([broken, other]) == []


# --- staffing.check: the pure function ------------------------------------------------------------------------------


def request(mode="in-person", on="2026-11-01"):
    return {"instructor": SME, "unit": UNIT, "mode": mode, "date": on}


def test_staffing_check_ok_warn_and_block_from_the_events(rules):
    log = [clearance_event()]
    assert staffing.check(log, request(), rules) == {"verdict": "ok", "reasons": [],
                                                       "clearance": "tm:clearance/0123456789abcdef"}
    assert staffing.check(log, request("hybrid"), rules)["verdict"] == "block"  # another mode
    assert staffing.check([], request(), rules)["verdict"] == "block"
    warn = staffing.check(log, request(on="2027-09-20"), rules, detail=True)  # 30 days before expiry
    assert warn["verdict"] == "warn" and warn["reasons"] == ["clearance expires in 30 days"]
    assert staffing.check(log, request(on="2027-09-19"), rules)["verdict"] == "ok"  # 31 days: no warning yet


def test_staffing_check_honours_a_superseding_event(rules):
    cond = clearance_event(outcome="cleared_with_conditions", recheck="2026-12-01", conditions=["clearances/x#1"])
    assert staffing.check([cond], request(), rules)["verdict"] == "warn"  # the recheck is 30 days away
    lapsed = clearance_event(outcome="not_yet", recheck="2026-12-01", conditions=["clearances/x#1"],
                             at="2026-12-02T08:00:00+00:00")
    assert staffing.check([cond, lapsed], request(), rules)["verdict"] == "block"


def test_a_clearance_of_an_earlier_framework_major_blocks(rules):
    log = [clearance_event(framework_version="2.0.0")]
    res = staffing.check(log, request(), rules, detail=True)
    assert res["verdict"] == "block" and any("framework 2.0.0" in r for r in res["reasons"])


def test_staffing_check_warns_ahead_of_the_recheck(rules):
    cond = clearance_event(outcome="cleared_with_conditions", recheck="2026-12-01", conditions=["clearances/x#1"])
    assert staffing.check([cond], request(on="2026-10-31"), rules)["verdict"] == "ok"
    warn = staffing.check([cond], request(on="2026-11-01"), rules, detail=True)
    assert warn["verdict"] == "warn" and warn["reasons"] == ["conditional clearance recheck due in 30 days"]


def test_staffing_check_refuses_a_request_outside_the_contract(rules):
    with pytest.raises(staffing.RequestError, match="mode"):
        staffing.check([], request(mode="satellite"), rules)
    with pytest.raises(staffing.RequestError, match="date"):
        staffing.check([], request(on="next week"), rules)
    with pytest.raises(staffing.RequestError):
        staffing.check([], {**request(), "extra": 1}, rules)


def test_every_response_fits_the_contract(rules):
    from teachermodel.standards import load_schema
    from jsonschema import Draft202012Validator

    schema = load_schema("staffing-check.schema.json")
    validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/response"})
    log = [clearance_event()]
    for req in (request(), request("hybrid"), request(on="2027-09-20")):
        assert list(validator.iter_errors(staffing.check(log, req, rules))) == []


# --- the command ----------------------------------------------------------------------------------------------------


def store_with(private, *evs):
    for e in evs:
        events.append(private / app.EVENT_LOG, e)
    return private


@pytest.mark.parametrize("mode,on,verdict,code", [
    ("in-person", "2026-11-01", "ok", 0),
    ("in-person", "2027-09-20", "warn", 3),
    ("hybrid", "2026-11-01", "block", 2),
    ("in-person", "2027-10-20", "block", 2),  # the expiry day itself is no longer covered
])
def test_staffing_check_command_prints_the_response_and_exits_by_verdict(
        fictional_store, capsys, mode, on, verdict, code):
    store_with(fictional_store, clearance_event())
    rc = cli.main(["staffing-check", "--private-dir", str(fictional_store), "--instructor", SME, "--unit", UNIT,
                   "--mode", mode, "--date", on])
    out = json.loads(capsys.readouterr().out)
    assert rc == code and out["verdict"] == verdict


def test_the_exit_codes_are_documented_in_the_help(capsys):
    assert staffing.EXIT_CODES == {"ok": 0, "warn": 3, "block": 2}
    with pytest.raises(SystemExit):
        cli.main(["staffing-check", "--help"])
    text = " ".join(capsys.readouterr().out.split())
    assert "0 ok" in text and "3 warn" in text and "2 block" in text and "1" in text


def test_staffing_check_command_with_an_empty_store_blocks(fictional_store, capsys):
    rc = cli.main(["staffing-check", "--private-dir", str(fictional_store), "--instructor", SME, "--unit", UNIT,
                   "--mode", "in-person", "--date", "2026-11-01"])
    assert rc == 2 and json.loads(capsys.readouterr().out)["verdict"] == "block"


def test_staffing_check_command_refuses_a_bad_request(fictional_store, capsys):
    rc = cli.main(["staffing-check", "--private-dir", str(fictional_store), "--instructor", SME, "--unit", "not-a-unit",
                   "--mode", "in-person", "--date", "2026-11-01"])
    assert rc == 1 and "unit" in capsys.readouterr().err


# --- the gap list reads the clearances ------------------------------------------------------------------------------


def gap_rows(private):
    return {r["key"] for r in json.loads((private / "generated" / "gap-list.json").read_text(encoding="utf-8"))["rows"]}


def test_the_gap_list_drops_a_cleared_delivery_on_the_next_run(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    app.do_run(fictional_store, now=T0)
    key = f"{SME} {UNIT} in-person"
    assert key in gap_rows(fictional_store)
    store_with(fictional_store, clearance_event())
    app.do_run(fictional_store, now=T0.replace(day=27))
    rows = gap_rows(fictional_store)
    assert key not in rows and f"{SME} {UNIT} hybrid" in rows  # only the cleared mode leaves the list


def test_the_gap_list_step_refreshes():
    assert AUTO_STEPS["tm:step/gap-list"].refresh


def test_the_gap_list_runner_passes_the_recorded_clearances(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    store_with(fictional_store, clearance_event())
    st = app.load_state(fictional_store)
    AUTO_STEPS["tm:step/gap-list"].run(st, "tm:programme/teachermodel", T0)
    assert f"{SME} {UNIT} in-person" not in gap_rows(fictional_store)
    assert load_standards()["rules"]["staffing"]["warn_expiry_days"] == 30


def test_the_gap_list_names_a_recheck_warning_as_a_recheck(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    near = (T0 + timedelta(days=10)).date().isoformat()
    store_with(fictional_store, clearance_event(outcome="cleared_with_conditions", recheck=near,
                                                conditions=["clearances/x#1"]))
    st = app.load_state(fictional_store)
    AUTO_STEPS["tm:step/gap-list"].run(st, "tm:programme/teachermodel", T0)
    doc = json.loads((fictional_store / "generated" / "gap-list.json").read_text(encoding="utf-8"))
    (row,) = [r for r in doc["rows"] if r["key"] == f"{SME} {UNIT} in-person"]
    assert "conditional recheck due within 30 days" in row["summary"]
    assert "expires" not in row["summary"]


# --- a bench outcome stops staffing (decision 0015, appended 2026-10-25) -----------------------------------------------

HOT = "tm:person/hot-1"


def bench_events(decision, *, decided="2026-10-25", n=1, instructor=SME):
    """A bench review of `instructor` (subject event) and its `bench_decision`, decided on `decided`."""
    uri = f"tm:bench/{instructor.split('/')[1]}--{n}"
    opened = events.make_event(
        "subject", uri, "tm:system/teachermodel",
        {"subject_kind": "bench", "attrs": {"instructor": instructor, "reason": "requested"}, "opened_by": "tm:cli/request-bench"},
        id=f"bench-open-{n}", at="2026-10-21T09:00:00+00:00")
    decision_event = events.make_event(
        "bench_decision", uri, HOT,
        {"bench": uri, "instructor": instructor, "decision": decision, "rationale_key": f"bench/{n}.json",
         "evidence_pack_sha256": "ab" * 32, "decided_by": HOT, "signoff_id": "cd" * 8},
        id=f"bench-decision-{n}", at=f"{decided}T09:00:00+00:00")
    assert events.check_event(opened) == [] and events.check_event(decision_event) == []
    return [opened, decision_event]


@pytest.mark.parametrize("decision,reason", [
    ("exit", "bench decision: exit"),
    ("return-to-co-teaching", "bench decision: returned to co-teaching"),
])
def test_an_exit_or_a_return_to_co_teaching_blocks_staffing(rules, decision, reason):
    log = [clearance_event(), *bench_events(decision)]
    res = staffing.check(log, request(on="2026-11-01"), rules, detail=True)
    assert res["verdict"] == "block" and res["reasons"] == [reason] and "clearance" not in res


@pytest.mark.parametrize("decision", ["renew", "convert"])
def test_a_renew_or_convert_leaves_staffing_alone(rules, decision):
    log = [clearance_event(), *bench_events(decision)]
    assert staffing.check(log, request(on="2026-11-01"), rules)["verdict"] == "ok"


def test_a_bench_decision_blocks_from_its_day_and_not_before(rules):
    log = [clearance_event(), *bench_events("exit", decided="2026-10-25")]
    assert staffing.check(log, request(on="2026-10-24"), rules)["verdict"] == "ok"  # a delivery before the decision
    assert staffing.check(log, request(on="2026-10-25"), rules)["verdict"] == "block"


def test_a_clearance_issued_after_the_decision_lifts_the_block_and_one_issued_on_the_day_does_not(rules):
    old = clearance_event(issued="2026-10-20")
    same_day = clearance_event("fedcba9876543210", issued="2026-10-25", at="2026-10-25T10:00:00+00:00")
    later = clearance_event("00112233445566aa", issued="2026-10-26", at="2026-10-26T10:00:00+00:00")
    bench = bench_events("exit", decided="2026-10-25")
    assert staffing.check([old, same_day, *bench], request(on="2026-11-01"), rules)["verdict"] == "block"
    res = staffing.check([old, same_day, later, *bench], request(on="2026-11-01"), rules)
    assert res["verdict"] == "ok" and res["clearance"] == "tm:clearance/00112233445566aa"  # the new one, not the old


def test_only_a_clearance_for_the_requested_unit_and_mode_lifts_the_block(rules):
    old = clearance_event(issued="2026-10-20", modes=("in-person", "hybrid"))
    other_mode = clearance_event("fedcba9876543210", issued="2026-10-26", modes=("remote",), at="2026-10-26T10:00:00+00:00")
    log = [old, other_mode, *bench_events("return-to-co-teaching")]
    assert staffing.check(log, request("hybrid", on="2026-11-01"), rules)["verdict"] == "block"
    assert staffing.check(log, request("remote", on="2026-11-01"), rules)["verdict"] == "ok"


def test_a_later_renew_or_convert_does_not_lift_a_blocking_decision(rules):
    """Integration review finding 2: only a clearance issued after the exit lifts it; a later renew or convert does not."""
    exit_ = bench_events("exit", decided="2026-10-25")
    renewed = bench_events("renew", decided="2026-10-30", n=2)
    converted = bench_events("convert", decided="2026-10-31", n=3)
    res = staffing.check([clearance_event(), *exit_, *renewed, *converted], request(on="2026-11-02"), rules, detail=True)
    assert res["verdict"] == "block" and res["reasons"] == ["bench decision: exit"]
    later = clearance_event("00112233445566aa", issued="2026-11-01", at="2026-11-01T10:00:00+00:00")
    assert staffing.check([clearance_event(), *exit_, *renewed, later], request(on="2026-11-02"), rules)["verdict"] == "ok"


def test_the_latest_blocking_decision_decides_which_clearances_are_stale(rules):
    exit_ = bench_events("exit", decided="2026-10-25")
    later = clearance_event("00112233445566aa", issued="2026-10-28", at="2026-10-28T10:00:00+00:00")
    rtc = bench_events("return-to-co-teaching", decided="2026-11-01", n=2)
    res = staffing.check([clearance_event(), *exit_, later, *rtc], request(on="2026-11-02"), rules, detail=True)
    assert res["verdict"] == "block" and res["reasons"] == ["bench decision: returned to co-teaching"]
    assert staffing.check([clearance_event(), *exit_, later, *rtc], request(on="2026-10-30"), rules)["verdict"] == "ok"


def test_records_bench_blocks_finds_the_blocking_decision_and_its_supersession(rules):
    from teachermodel.records import bench_blocks

    exit_ = bench_events("exit", decided="2026-10-25")
    renewed = bench_events("renew", decided="2026-10-30", n=2)
    log = [clearance_event(), *exit_, *renewed]
    assert bench_blocks.blocking_decision(log, SME, date(2026, 10, 24)) is None  # before the decision
    found = bench_blocks.blocking_decision(log, SME, date(2026, 10, 25))
    assert found["decision"] == "exit" and found["at"] == date(2026, 10, 25) and found["bench"] == "tm:bench/k7m2q--1"
    assert bench_blocks.blocking_decision(log, SME, date(2026, 11, 5))["decision"] == "exit"  # renew changes nothing
    assert bench_blocks.blocking_decision(log, "tm:instructor/p3x9d", date(2026, 11, 5)) is None
    same_day = clearance_event("fedcba9876543210", issued="2026-10-25", at="2026-10-25T10:00:00+00:00")
    assert bench_blocks.blocking_decision([*log, same_day], SME, date(2026, 11, 5)) is not None
    later = clearance_event("00112233445566aa", issued="2026-11-01", at="2026-11-01T10:00:00+00:00")
    assert bench_blocks.blocking_decision([*log, later], SME, date(2026, 10, 31)) is not None  # not yet issued then
    assert bench_blocks.blocking_decision([*log, later], SME, date(2026, 11, 1)) is None  # superseded by it
    assert bench_blocks.latest_blocking([*log, later], SME, date(2026, 11, 1))["decision"] == "exit"  # whatever followed
    assert bench_blocks.is_exited([*log], SME, date(2026, 11, 5))
    rtc = bench_events("return-to-co-teaching", decided="2026-10-25")
    assert bench_blocks.blocking_decision(rtc, SME, date(2026, 11, 5))["decision"] == "return-to-co-teaching"
    assert not bench_blocks.is_exited(rtc, SME, date(2026, 11, 5))


def test_another_instructors_bench_decision_does_not_block(rules):
    log = [clearance_event(), *bench_events("exit", instructor="tm:instructor/p3x9d")]
    assert staffing.check(log, request(on="2026-11-01"), rules)["verdict"] == "ok"


def test_an_exit_with_no_clearance_names_both_reasons(rules):
    res = staffing.check(bench_events("exit"), request(on="2026-11-01"), rules, detail=True)
    assert res["verdict"] == "block" and res["reasons"][0] == "bench decision: exit" and len(res["reasons"]) == 2


def test_a_bench_block_reaches_the_command_as_not_cleared_and_in_detail_only_with_the_flag(fictional_store, capsys):
    store_with(fictional_store, clearance_event(), *bench_events("exit"))
    argv = ["staffing-check", "--private-dir", str(fictional_store), "--instructor", SME, "--unit", UNIT,
            "--mode", "in-person", "--date", "2026-11-01"]
    rc = cli.main(argv)
    assert rc == 2 and json.loads(capsys.readouterr().out)["reasons"] == ["not cleared"]
    rc = cli.main([*argv, "--detail"])
    assert rc == 2 and "bench decision: exit" in json.loads(capsys.readouterr().out)["reasons"]


# --- what delivery scheduling receives (decision 0005, integration review finding 12) ------------------------------------


def test_the_outbound_response_says_only_not_cleared_for_a_block(rules):
    for log in ([], [clearance_event(framework_version="2.0.0")], [clearance_event(), *bench_events("exit")]):
        res = staffing.check(log, request(on="2026-11-01"), rules)
        assert res == {"verdict": "block", "reasons": ["not cleared"]}


def test_the_outbound_response_names_an_expiry_or_a_recheck_but_no_day_count(rules):
    warn = staffing.check([clearance_event()], request(on="2027-09-20"), rules)
    assert warn == {"verdict": "warn", "reasons": ["clearance expiring"], "clearance": "tm:clearance/0123456789abcdef"}
    cond = clearance_event(outcome="cleared_with_conditions", recheck="2026-12-01", conditions=["clearances/x#1"])
    assert staffing.check([cond], request(on="2026-11-01"), rules)["reasons"] == ["recheck due"]
    assert staffing.check([cond], request(on="2026-11-01"), rules, detail=True)["reasons"] == [
        "conditional clearance recheck due in 30 days"]


def test_the_outbound_reasons_are_drawn_from_a_fixed_vocabulary(rules):
    import re

    allowed = re.compile(r"^(not cleared|clearance expiring|recheck due|override tm:override/[0-9a-f]{16})\Z")
    logs = [[], [clearance_event()], [clearance_event(), *bench_events("return-to-co-teaching")],
            [clearance_event(outcome="cleared_with_conditions", recheck="2026-11-15", conditions=["clearances/x#1"])]]
    for log in logs:
        for on in ("2026-11-01", "2027-09-25", "2027-10-21"):
            for mode in ("in-person", "hybrid"):
                for reason in staffing.check(log, request(mode, on=on), rules)["reasons"]:
                    assert allowed.match(reason), reason


# --- the gap list approval is bound to the list it was given (carried item, decision 0015) -------------------------------


def test_the_gap_list_approval_is_bound_to_its_inputs():
    steps = {s["id"]: s for w in load_standards()["workflows"]["workflows"] for s in w["steps"]}
    assert steps["tm:step/gap-list-approved"]["done_when"]["bind"] == "input"


def test_a_refreshed_gap_list_that_changes_reopens_its_approval_and_one_that_does_not_leaves_it_closed(
        fictional_store, example_roster):
    from test_observation import sign

    from teachermodel.workflow import PROGRAMME

    step = "tm:step/gap-list-approved"
    import_roster_ungated(fictional_store, example_roster, T0)
    app.do_run(fictional_store, now=T0)

    def due(now=T0):
        return (step, PROGRAMME) in {(d.step, d.subject) for d in app.due_steps(app.load_state(fictional_store), now.date())}

    def approve():
        rows = json.loads((fictional_store / "generated" / "gap-list.json").read_text(encoding="utf-8"))["rows"]
        sign(fictional_store, step, PROGRAMME, "tm:person/owner-1", {"rows": {r["key"]: "approve" for r in rows}})

    assert due()
    approve()
    assert not due()
    app.do_run(fictional_store, now=T0 + timedelta(days=1))  # the same list: the approval stands
    assert not due()
    store_with(fictional_store, clearance_event())  # a clearance issued: one row leaves the list
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    assert due(T0 + timedelta(days=2)), "the approval did not reopen for the changed list"
    approve()
    assert not due(T0 + timedelta(days=2))
