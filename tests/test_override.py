"""The staffing override (spec v0.2 Rules: "Only the head of training can override a block, and every override
records a reason"; increment 3 plan section J; decision 0015).

    teachermodel request-override      an `override` subject (subject@2): instructor, unit, mode, date, request_ref (a private key)
    override-decision (head of training, never the instructor)
                                       approve or reject with a reason; a hook writes a `check` {result: granted | declined}
                                       and keeps the reason in the private store
    staffing.check                     an approved override turns a block into ok for exactly that instructor, unit, mode and date

Fictional people only.
"""

import json
from datetime import date, datetime, timezone

import pytest
import yaml
from conftest import make_fictional_store  # noqa: F401 - the fixtures come from conftest
from ingest_helpers import ingest, signoff
from privacy_helpers import import_roster_ungated
from test_clearance import AT, decide, of_kind, reasons, signers

from teachermodel import app, cli, events, flows, records, rules, staffing, workflow
from teachermodel.flows import override as flow
from teachermodel.standards import load_standards

K7 = "tm:instructor/k7m2q"
P3 = "tm:instructor/p3x9d"
UNIT = "sl:unit/example-agent-loop@1"
OTHER_UNIT = "sl:unit/example-other@1"
HOT = "tm:person/hot-1"
STEP = "tm:step/override-decision"
T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
DAY = "2026-11-03"
NOTE = "SECRET-REQUEST-NOTE we are short of leads"
REASON = "SECRET-REASON the cleared lead is ill"
RULES = load_standards()["rules"]


@pytest.fixture
def bare(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    return fictional_store


def log(private):
    return app.read_events(private)


def open_override(private, *, note=NOTE, day=DAY, mode="in-person", unit=UNIT, instructor=K7):
    return flow.request_override(private, instructor=instructor, unit=unit, mode=mode, date=day, note=note, now=T0)


def decisions(private):
    return [e for e in of_kind(private, "check") if e["payload"].get("step") == STEP
            and e["payload"].get("result") in ("granted", "declined")]


def check(private, *, on=DAY, mode="in-person", unit=UNIT, instructor=K7, detail=True):
    return staffing.check(log(private), {"instructor": instructor, "unit": unit, "mode": mode, "date": on}, RULES,
                          detail=detail)


def fields(decision="approve", reason=REASON):
    return {"decision": decision, "reason": reason}


# --- the workflow file -----------------------------------------------------------------------------------------------


def test_the_override_workflow_defines_its_step():
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/override"]
    (step,) = wf["steps"]
    assert (step["id"], step["type"], step["role"], step["subject"], step["page"]) == (STEP, "human", "head-of-training", "override", "approve")
    assert step["needs"] == [] and step["done_when"] == {"kind": "signoff", "match": {"step": STEP}}
    assert STEP in flows.PAGE_SPECS and STEP in flows.CONTENT_CHECKS and STEP in flows.SIGNOFF_HOOKS


# --- request-override ------------------------------------------------------------------------------------------------


def test_request_override_opens_an_override_subject_whose_note_stays_private(bare):
    opened = open_override(bare)
    assert opened.created and opened.override.startswith("tm:override/") and len(opened.override) == len("tm:override/") + 16
    (e,) = [x for x in log(bare) if x["kind"] == "subject" and x["payload"]["subject_kind"] == "override"]
    assert events.check_event(e) == [] and e["subject_uri"] == opened.override and e["actor"] == workflow.SYSTEM_ACTOR
    attrs = e["payload"]["attrs"]
    assert {k: attrs[k] for k in ("instructor", "unit", "mode", "date")} == {
        "instructor": K7, "unit": UNIT, "mode": "in-person", "date": DAY}
    assert e["payload"]["opened_by"] == "tm:cli/request-override"
    note = json.loads((bare / attrs["request_ref"]).read_text(encoding="utf-8"))
    assert note["note"] == NOTE and note["override"] == opened.override
    assert "SECRET-REQUEST-NOTE" not in (bare / "events" / "events.jsonl").read_text(encoding="utf-8")


def test_request_override_without_a_note_still_gives_a_private_key(bare):
    opened = open_override(bare, note=None)
    (e,) = [x for x in log(bare) if x["subject_uri"] == opened.override]
    assert json.loads((bare / e["payload"]["attrs"]["request_ref"]).read_text(encoding="utf-8"))["note"] is None


def test_request_override_is_idempotent_while_the_request_is_open(bare):
    first = open_override(bare)
    again = open_override(bare)
    assert not again.created and again.override == first.override
    assert len([e for e in log(bare) if e["kind"] == "subject"
                and e["payload"]["subject_kind"] == "override"]) == 1


def test_different_requests_get_different_overrides(bare):
    uris = {open_override(bare).override, open_override(bare, day="2026-11-04").override,
            open_override(bare, mode="hybrid").override, open_override(bare, instructor=P3).override}
    assert len(uris) == 4


@pytest.mark.parametrize("kw,match", [
    ({"instructor": "tm:instructor/zz9top"}, "registered"),
    ({"instructor": "not an instructor"}, "registered"),
    ({"mode": "satellite"}, "mode"),
    ({"unit": "not-a-unit"}, "unit"),
    ({"day": "next week"}, "date"),
    ({"day": "2026-02-30"}, "date"),
    ({"day": "2026-10-25"}, "past"),  # integration review finding 21: the day before today
])
def test_request_override_refuses_a_request_outside_the_contract(bare, kw, match):
    with pytest.raises(flow.OverrideError, match=match):
        open_override(bare, **kw)
    assert not [e for e in log(bare) if e["kind"] == "subject" and e["payload"]["subject_kind"] == "override"]


def test_request_override_takes_a_bare_slug(bare):
    assert open_override(bare, instructor="k7m2q").created


def test_the_request_override_command(bare, capsys):
    argv = ["request-override", "--private-dir", str(bare), "--instructor", K7, "--unit", UNIT, "--mode", "in-person",
            "--date", DAY, "--note", NOTE]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "tm:override/" in out and "opened" in out and "already open" not in out
    assert cli.main(argv) == 0
    assert "already open" in capsys.readouterr().out
    assert cli.main([*argv[:-4], "--date", "soon"]) == 1
    assert "date" in capsys.readouterr().err


# --- the decision page and its content checks ------------------------------------------------------------------------


def test_the_head_of_training_gets_the_decision_page_and_not_the_instructor(bare):
    o = open_override(bare).override
    assert signers(bare, STEP, o) == [HOT]
    spec = app._page_specs(app.load_state(bare), STEP, o)[0]
    assert spec["role"] == "head-of-training" and spec["template"] == "approve"
    assert {k: spec["inputs"][k] for k in ("instructor", "unit", "mode", "date")} == {
        "instructor": K7, "unit": UNIT, "mode": "in-person", "date": DAY}
    names = {f["name"]: f for f in spec["fields"]}
    assert names["decision"]["options"] == ["approve", "reject"] and names["decision"]["required"] is True
    assert "value" not in names["decision"]  # no default: the head chooses
    assert names["reason"]["kind"] == "textarea" and names["reason"]["required"] is True
    assert NOTE not in json.dumps(spec)  # the page names the private key, not the requester's words


def test_the_head_who_is_the_instructor_gets_no_page_and_cannot_decide(bare):
    o = open_override(bare).override
    path = bare / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/hot-k7", "name": "Head Who Instructs", "email": "head.k7@example.com",
                          "roles": ["head-of-training"], "instructor": K7})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert signers(bare, STEP, o) == [HOT]
    assert any("instructor" in r for r in reasons(bare, STEP, "tm:person/hot-k7", fields(), subject=o))


def test_a_decision_needs_the_head_a_known_decision_and_a_reason(bare):
    o = open_override(bare).override
    assert reasons(bare, STEP, HOT, fields(), subject=o) == []
    assert reasons(bare, STEP, HOT, fields("reject"), subject=o) == []
    assert any("head of training" in r for r in reasons(bare, STEP, "tm:person/coord-1", fields(), subject=o))
    assert any("decision" in r for r in reasons(bare, STEP, HOT, fields("maybe"), subject=o))
    assert any("decision" in r for r in reasons(bare, STEP, HOT, {"reason": "x"}, subject=o))
    assert any("reason" in r for r in reasons(bare, STEP, HOT, fields(reason="   "), subject=o))
    assert any("reason" in r for r in reasons(bare, STEP, HOT, {"decision": "approve"}, subject=o))
    assert any("reason" in r for r in reasons(bare, STEP, HOT, fields(reason=7), subject=o))


def test_a_decision_on_a_subject_that_is_not_an_override_is_refused(bare):
    st = app.load_state(bare)
    doc = {"decision": "approve", "step": STEP, "subject_uri": "tm:programme/teachermodel", "signer": HOT,
           "fields": fields(), "signed_at": AT}
    assert flows.content_reasons(st, doc) == ["the subject is not an override"]


# --- the decision: approve and reject --------------------------------------------------------------------------------


def test_an_approval_writes_a_check_event_and_keeps_the_reason_private(bare):
    o = open_override(bare).override
    signed = decide(bare, STEP, HOT, fields(), subject=o)
    (e,) = decisions(bare)
    assert events.check_event(e) == [] and e["subject_uri"] == o and e["actor"] == HOT
    p = e["payload"]
    assert p["result"] == "granted" and p["override"] == o and p["decided_by"] == HOT
    assert p["signoff_id"] == signed["payload"]["signoff_id"]
    private = json.loads((bare / p["reason_key"]).read_text(encoding="utf-8"))
    assert private["reason"] == REASON and private["decision"] == "approve" and private["override"] == o
    text = (bare / "events" / "events.jsonl").read_text(encoding="utf-8")
    assert "SECRET-REASON" not in text and "SECRET-REQUEST-NOTE" not in text
    assert (STEP, o) not in {(d.step, d.subject) for d in app.due_steps(app.load_state(bare), T0.date())}


def test_records_overrides_joins_the_request_and_its_decision(bare):
    o = open_override(bare).override
    (mine,) = records.overrides(log(bare))
    assert mine["override"] == o and mine["decision"] is None and mine["instructor"] == K7
    assert mine["date"] == date(2026, 11, 3) and mine["mode"] == "in-person" and mine["unit"] == UNIT
    decide(bare, STEP, HOT, fields(), subject=o)
    assert records.overrides(log(bare))[0]["decision"] == "approved"


def test_records_overrides_ignores_a_decision_for_an_unopened_override_and_other_checks():
    stray = events.make_event("check", "tm:override/0123456789abcdef", HOT,
                              {"step": STEP, "result": "granted", "override": "tm:override/0123456789abcdef"})
    other = events.make_event("check", "tm:programme/teachermodel", HOT, {"step": "tm:step/x", "result": "approved"})
    assert records.overrides([stray, other]) == []


# --- the staffing check ----------------------------------------------------------------------------------------------


def approved(private, **kw):
    o = open_override(private, **kw).override
    decide(private, STEP, HOT, fields(), subject=o)
    return o


def test_without_an_override_the_request_blocks(bare):
    assert check(bare)["verdict"] == "block"


def test_an_undecided_override_changes_nothing(bare):
    open_override(bare)
    assert check(bare)["verdict"] == "block"


def test_a_rejected_override_changes_nothing(bare):
    o = open_override(bare).override
    decide(bare, STEP, HOT, fields("reject", "Not enough reason"), subject=o)
    (e,) = decisions(bare)
    assert e["payload"]["result"] == "declined"
    assert check(bare)["verdict"] == "block"


def test_an_approved_override_turns_the_block_into_ok_for_exactly_that_instructor_unit_mode_and_date(bare):
    o = approved(bare)
    res = check(bare)
    assert res["verdict"] == "ok" and f"override {o}" in res["reasons"] and "clearance" not in res
    assert any(r.startswith("overridden: no valid clearance") for r in res["reasons"])  # what was overridden stays visible
    assert check(bare, on="2026-11-04")["verdict"] == "block"  # the next day
    assert check(bare, on="2026-11-02")["verdict"] == "block"  # the day before
    assert check(bare, mode="hybrid")["verdict"] == "block"  # another mode
    assert check(bare, unit=OTHER_UNIT)["verdict"] == "block"  # another unit
    assert check(bare, instructor=P3)["verdict"] == "block"  # another instructor


def test_the_response_of_an_override_fits_the_contract(bare):
    from jsonschema import Draft202012Validator

    from teachermodel.standards import load_schema

    approved(bare)
    schema = load_schema("staffing-check.schema.json")
    validator = Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/response"})
    assert list(validator.iter_errors(check(bare))) == []


def test_an_override_does_not_change_a_verdict_that_was_not_a_block(bare):
    from test_staffing import clearance_event

    approved(bare)
    events.append(bare / app.EVENT_LOG, clearance_event())
    res = check(bare, on="2026-11-03")
    assert res["verdict"] == "ok" and res["clearance"] == "tm:clearance/0123456789abcdef" and res["reasons"] == []


def test_an_approved_override_also_overrides_a_bench_block(bare):
    from test_staffing import bench_events, clearance_event

    events.append(bare / app.EVENT_LOG, clearance_event())
    for e in bench_events("exit"):
        events.append(bare / app.EVENT_LOG, e)
    assert check(bare)["verdict"] == "block"
    o = approved(bare)
    res = check(bare)
    assert res["verdict"] == "ok" and f"override {o}" in res["reasons"] and "overridden: bench decision: exit" in res["reasons"]


def test_a_rejected_request_can_be_asked_again_and_an_approved_one_is_not_asked_twice(bare):
    first = open_override(bare).override
    decide(bare, STEP, HOT, fields("reject"), subject=first)
    second = open_override(bare)
    assert second.created and second.override != first
    decide(bare, STEP, HOT, fields("approve", "Second look"), subject=second.override)
    assert check(bare)["verdict"] == "ok"
    third = open_override(bare)
    assert not third.created and third.override == second.override


def test_two_approved_overrides_for_one_request_name_one_of_them_deterministically(bare):
    first = approved(bare)
    # a request for the same thing after an approval is not opened; a second, different date is a different override
    approved(bare, day="2026-11-04")
    res = check(bare)
    assert res["reasons"][0] == f"override {first}"


def test_rules_staffing_check_takes_overrides_directly():
    block = (f"no valid clearance for {UNIT} in in-person mode on 2026-11-03",)
    o = rules.Override("tm:override/0123456789abcdef", K7, UNIT, "in-person", date(2026, 11, 3), True, block,
                       date(2026, 10, 27))
    res = rules.staffing_check([], K7, UNIT, "in-person", date(2026, 11, 3), RULES, overrides=[o])
    assert res["verdict"] == "ok" and res["reasons"][0] == "override tm:override/0123456789abcdef"
    declined = rules.Override("tm:override/0123456789abcdef", K7, UNIT, "in-person", date(2026, 11, 3), False, block,
                              date(2026, 10, 27))
    assert rules.staffing_check([], K7, UNIT, "in-person", date(2026, 11, 3), RULES, overrides=[declined])["verdict"] == "block"
    unbound = rules.Override("tm:override/0123456789abcdef", K7, UNIT, "in-person", date(2026, 11, 3), True)
    assert rules.staffing_check([], K7, UNIT, "in-person", date(2026, 11, 3), RULES, overrides=[unbound])["verdict"] == "block"


# --- an override is bound to the block it overrode (integration review finding 5) ------------------------------------


def test_the_decision_page_shows_the_block_the_override_would_lift(bare):
    o = open_override(bare).override
    spec = app._page_specs(app.load_state(bare), STEP, o)[0]
    assert spec["inputs"]["block"] == [f"no valid clearance for {UNIT} in in-person mode on {DAY}"]


def test_the_decision_check_records_the_block_it_was_decided_on(bare):
    o = approved(bare)
    (e,) = decisions(bare)
    assert e["payload"]["block"] == [f"no valid clearance for {UNIT} in in-person mode on {DAY}"]
    (mine,) = records.overrides(log(bare))
    assert mine["block"] == (f"no valid clearance for {UNIT} in in-person mode on {DAY}",) and mine["override"] == o


def test_an_override_does_not_lift_a_block_whose_reasons_changed_since(bare):
    from test_staffing import bench_events

    approved(bare)  # decided on "no valid clearance"
    assert check(bare)["verdict"] == "ok"
    for e in bench_events("exit", decided="2026-10-28"):
        events.append(bare / app.EVENT_LOG, e)
    res = check(bare)
    assert res["verdict"] == "block" and res["reasons"][0] == "bench decision: exit"


def test_an_override_decided_before_the_latest_bench_decision_is_ignored(bare):
    from test_staffing import bench_events, clearance_event

    events.append(bare / app.EVENT_LOG, clearance_event())
    for e in bench_events("exit", decided="2026-10-25"):
        events.append(bare / app.EVENT_LOG, e)
    approved(bare)  # decided on 2026-10-27 on "bench decision: exit"
    assert check(bare)["verdict"] == "ok"
    for e in bench_events("exit", decided="2026-10-30", n=2):  # a second exit: the same reasons, a new decision
        events.append(bare / app.EVENT_LOG, e)
    assert check(bare)["verdict"] == "block"


def test_an_approval_of_a_request_the_check_does_not_block_is_refused(bare):
    from test_staffing import clearance_event

    events.append(bare / app.EVENT_LOG, clearance_event())
    o = open_override(bare).override
    assert app._page_specs(app.load_state(bare), STEP, o)[0]["inputs"]["block"] == []
    assert any("does not block" in r for r in reasons(bare, STEP, HOT, fields(), subject=o))
    assert reasons(bare, STEP, HOT, fields("reject"), subject=o) == []


def test_the_outbound_response_of_an_override_names_only_the_override(bare):
    o = approved(bare)
    assert check(bare, detail=False) == {"verdict": "ok", "reasons": [f"override {o}"]}


# --- the real mail round trip ----------------------------------------------------------------------------------------


def test_a_decision_through_the_real_mail_round_trip(bare):
    o = open_override(bare).override
    app.do_tick(bare, now=T0)
    page = bare / "pages" / f"{app.page_stem(STEP, o, HOT)}.html"
    assert page.is_file()
    doc = signoff(bare, STEP, o, HOT, fields("approve", "Round trip reason"), now=T0)
    rep = ingest(bare, [doc], now=T0, name="override")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    (e,) = decisions(bare)
    assert e["payload"]["result"] == "granted" and check(bare)["verdict"] == "ok"
    assert "Round trip reason" not in (bare / "events" / "events.jsonl").read_text(encoding="utf-8")
    assert "Round trip reason" in (bare / e["payload"]["reason_key"]).read_text(encoding="utf-8")


def test_a_decision_with_no_reason_is_refused_by_ingest(bare):
    o = open_override(bare).override
    app.do_tick(bare, now=T0)
    doc = signoff(bare, STEP, o, HOT, {"decision": "approve", "reason": ""}, now=T0)
    rep = ingest(bare, [doc], now=T0, name="override")
    assert "1 rejected" in rep.summary and not decisions(bare) and check(bare)["verdict"] == "block"


# --- one decision per override (integration review finding 16) ---------------------------------------------------------


def add_second_head(private):
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/hot-2", "name": "Second Head", "email": "head.two@example.com",
                          "roles": ["head-of-training"]})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_two_approving_decisions_in_one_receipt_keep_the_first(bare):
    add_second_head(bare)
    o = open_override(bare).override
    app.do_tick(bare, now=T0)
    first = signoff(bare, STEP, o, HOT, fields("approve", "First reason"), now=T0)
    second = signoff(bare, STEP, o, "tm:person/hot-2", fields("approve", "Second reason"), now=T0)
    rep = ingest(bare, [first, second], now=T0, name="two-heads")
    assert "1 signoff" in rep.summary and "1 rejected" in rep.summary, rep.all_lines()
    assert any("already decided" in line for line in rep.lines)
    (e,) = decisions(bare)
    assert e["actor"] == HOT


def test_a_later_approving_decision_on_the_same_inputs_is_refused(bare):
    add_second_head(bare)
    o = open_override(bare).override
    decide(bare, STEP, HOT, fields(), subject=o)
    assert any("already decided" in r for r in reasons(bare, STEP, "tm:person/hot-2", fields(), subject=o))


# --- partner and region name the occasion (decision 0018) ------------------------------------------------------------

ORG = "tm:org/example-partner"
OTHER_ORG = "tm:org/example-other"


def open_for(private, **kw):
    return flow.request_override(private, instructor=K7, unit=UNIT, mode="in-person", date=DAY, note=NOTE, now=T0, **kw)


def approved_for(private, **kw):
    o = open_for(private, **kw).override
    decide(private, STEP, HOT, fields(), subject=o)
    return o


def check_for(private, **extra):
    req = {"instructor": K7, "unit": UNIT, "mode": "in-person", "date": DAY, **extra}
    return staffing.check(log(private), req, RULES, detail=True)


def scoped_clearance(private):
    from test_partner import clearance_event as scoped

    events.append(private / app.EVENT_LOG, scoped(instructor=K7, unit=UNIT, modes=("in-person",),
                                                  scope={"partner": ORG, "regions": ["IE"]}))


def test_request_override_records_partner_and_region_and_keeps_the_old_uri_without_them(bare):
    plain = open_override(bare).override
    assert plain == flow.override_uri(K7, UNIT, "in-person", DAY, 1)
    named = open_for(bare, partner=ORG, region="US-CA")
    assert named.created and named.override != plain
    (subject,) = [e for e in log(bare) if e["kind"] == "subject" and e["subject_uri"] == named.override]
    assert subject["payload"]["attrs"]["partner"] == ORG and subject["payload"]["attrs"]["region"] == "US-CA"
    assert events.check_event(subject) == []
    assert "partner" not in [e for e in log(bare) if e["subject_uri"] == plain][0]["payload"]["attrs"]
    mine = {o["override"]: o for o in records.overrides(log(bare))}
    assert (mine[named.override]["partner"], mine[named.override]["region"]) == (ORG, "US-CA")
    assert (mine[plain]["partner"], mine[plain]["region"]) == (None, None)


def test_request_override_is_idempotent_per_partner_and_region(bare):
    first = open_for(bare, partner=ORG)
    assert not open_for(bare, partner=ORG).created
    assert open_for(bare, partner=OTHER_ORG).created
    assert open_for(bare, partner=ORG, region="IE").override != first.override


@pytest.mark.parametrize("kw, match", [
    ({"partner": "example-partner"}, "partner"),
    ({"partner": "tm:org/Bad"}, "partner"),
    ({"region": "ie"}, "region"),
    ({"region": "Ireland"}, "region"),
])
def test_request_override_refuses_a_partner_or_region_outside_the_contract(bare, kw, match):
    with pytest.raises(flow.OverrideError, match=match):
        open_for(bare, **kw)
    assert not [e for e in log(bare) if e["kind"] == "subject" and e["payload"]["subject_kind"] == "override"]


def test_an_override_without_partner_or_region_does_not_lift_a_request_that_names_one(bare):
    approved(bare)
    assert check_for(bare)["verdict"] == "ok"
    assert check_for(bare, partner=ORG)["verdict"] == "block"
    assert check_for(bare, region="IE")["verdict"] == "block"


def test_an_override_for_a_partner_and_region_lifts_exactly_that_occasion(bare):
    o = approved_for(bare, partner=ORG, region="IE")
    res = check_for(bare, partner=ORG, region="IE")
    assert res["verdict"] == "ok" and res["reasons"][0] == f"override {o}"
    assert check_for(bare)["verdict"] == "block"  # no partner named
    assert check_for(bare, partner=ORG)["verdict"] == "block"  # no region named
    assert check_for(bare, partner=OTHER_ORG, region="IE")["verdict"] == "block"  # another partner
    assert check_for(bare, partner=ORG, region="US-CA")["verdict"] == "block"  # another region


def test_a_scope_block_can_be_overridden_for_the_partner_it_names(bare):
    scoped_clearance(bare)
    assert check_for(bare, partner=ORG, region="IE")["verdict"] == "ok"  # the clearance covers this
    blocked = check_for(bare, partner=OTHER_ORG, region="IE")
    assert blocked["verdict"] == "block" and any("(scope)" in r for r in blocked["reasons"])
    o = open_for(bare, partner=OTHER_ORG, region="IE").override
    spec = app._page_specs(app.load_state(bare), STEP, o)[0]
    assert spec["inputs"]["partner"] == OTHER_ORG and spec["inputs"]["region"] == "IE"
    assert spec["inputs"]["block"] == blocked["reasons"]
    assert f"partner {OTHER_ORG}, region IE" in spec["intro"]
    decide(bare, STEP, HOT, fields(), subject=o)
    res = check_for(bare, partner=OTHER_ORG, region="IE")
    assert res["verdict"] == "ok" and res["reasons"][0] == f"override {o}"


def test_the_page_inputs_of_a_request_without_partner_or_region_are_unchanged(bare):
    o = open_override(bare).override
    spec = app._page_specs(app.load_state(bare), STEP, o)[0]
    assert list(spec["inputs"]) == ["override", "instructor", "unit", "mode", "date", "request_ref", "block"]


def test_rules_staffing_check_matches_the_override_partner_and_region():
    on = date(2026, 11, 3)
    block = (f"no valid clearance for {UNIT} in in-person mode on 2026-11-03",)
    o = rules.Override("tm:override/0123456789abcdef", K7, UNIT, "in-person", on, True, block, date(2026, 10, 27),
                       partner=ORG, region="IE")
    run = lambda **kw: rules.staffing_check([], K7, UNIT, "in-person", on, RULES, overrides=[o], **kw)["verdict"]  # noqa: E731
    assert run(partner=ORG, region="IE") == "ok"
    assert run() == "block"
    assert run(partner=ORG) == "block"
    assert run(region="IE") == "block"


def test_the_request_override_command_takes_partner_and_region(bare, capsys):
    argv = ["request-override", "--private-dir", str(bare), "--instructor", K7, "--unit", UNIT, "--mode", "in-person",
            "--date", DAY, "--partner", ORG, "--region", "IE"]
    assert cli.main(argv) == 0
    assert "opened" in capsys.readouterr().out
    (o,) = records.overrides(log(bare))
    assert (o["partner"], o["region"]) == (ORG, "IE")
    assert cli.main([*argv[:-2], "--region", "Ireland"]) == 1
    assert "region" in capsys.readouterr().err
