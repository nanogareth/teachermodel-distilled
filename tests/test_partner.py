"""W11 partner instructor clearance (spec v0.2 W11; increment 3 plan, stream I).

A partner candidate (registration type partner) is cleared on recordings only: every counted observation says
`from_recording` and the dry run's checklist says the run was done from a recording. The clearance carries
`scope {partner, regions}` from the registration, and the staffing check honours it: a scoped clearance covers only a
request that names its partner and one of its regions. Fictional people only.
"""

import json
import shutil
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from clearer_helpers import set_level
from conftest import EXAMPLE_ROSTER_PATH, make_fictional_store
from jsonschema import Draft202012Validator
from privacy_helpers import import_roster_ungated
from test_clearance import (
    AT, C5, D1, D2, DOMAINS, EVIDENCE, ISSUE, K7, P3, R8, RUBRIC, STD, T0, UNIT, calibrate, cleared, decide, hold,
    of_kind, put, reasons, signers,
)

from teachermodel import app, cli, events, records, rules, signoff as tm_signoff, staffing, units, workflow
from teachermodel.flows import dry_run as dry_run_flow
from teachermodel.standards import load_schema, validate

PARTNER = R8
ORG = "tm:org/example-partner"
CAND = "tm:candidate/r8n4h--example-agent-loop-1--remote"
SME_CAND = "tm:candidate/k7m2q--example-agent-loop-1--in-person"
DRY_RUN = "tm:step/dry-run"
SCOPE = {"partner": ORG, "regions": ["DE"]}


# --- the pure parts: records.clearances and the staffing check ------------------------------------------------------


def clearance_event(cid="0123456789abcdef", *, scope=None, instructor=PARTNER, unit=UNIT, modes=("remote",),
                    issued="2026-10-20", expires="2027-10-20", at="2026-10-20T10:00:00+00:00"):
    payload = {
        "clearance": f"tm:clearance/{cid}", "candidate": CAND, "instructor": instructor, "unit": unit,
        "modes": list(modes), "outcome": "cleared", "conditions": [], "recheck": None,
        "clearers": ["tm:instructor/p3x9d", "tm:instructor/c5w1t"], "observations": ["obs00001", "obs00002"],
        "issued": issued, "expires": expires, "framework_version": "0.2.0",
    }
    if scope is not None:
        payload["scope"] = scope
    event = events.make_event("clearance", CAND, "tm:system/teachermodel", payload, at=at)
    assert events.check_event(event) == []
    return event


def request(*, partner=None, region=None, on="2026-11-02", mode="remote"):
    out = {"instructor": PARTNER, "unit": UNIT, "mode": mode, "date": on}
    if partner is not None:
        out["partner"] = partner
    if region is not None:
        out["region"] = region
    return out


def check(log, req):
    return staffing.check(log, req, STD["rules"], detail=True)


def test_records_read_the_scope_of_a_clearance():
    (scoped,) = records.clearances([clearance_event(scope={"partner": ORG, "regions": ["DE", "AT"]})])
    assert scoped.scope == rules.Scope(partner=ORG, regions=("DE", "AT"))
    (open_,) = records.clearances([clearance_event()])
    assert open_.scope is None


def test_an_unscoped_clearance_covers_every_request():
    log = [clearance_event()]
    for req in (request(), request(partner=ORG, region="DE"), request(partner="tm:org/other", region="FR")):
        assert check(log, req)["verdict"] == "ok", req


def test_a_scoped_clearance_covers_a_request_for_its_partner_and_region():
    log = [clearance_event(scope={"partner": ORG, "regions": ["DE", "AT"]})]
    for region in ("DE", "AT"):
        res = check(log, request(partner=ORG, region=region))
        assert res["verdict"] == "ok" and res["clearance"] == "tm:clearance/0123456789abcdef"


@pytest.mark.parametrize("req", [
    request(partner="tm:org/another-partner", region="DE"),   # another partner
    request(partner=ORG, region="FR"),                         # another region
    request(partner=ORG),                                      # no region named
    request(region="DE"),                                      # no partner named
    request(),                                                 # neither named
])
def test_a_scoped_clearance_does_not_cover_other_partners_or_regions(req):
    res = check([clearance_event(scope={"partner": ORG, "regions": ["DE"]})], req)
    assert res["verdict"] == "block" and any("scope" in r for r in res["reasons"]), res


def test_a_scope_with_regions_only_covers_any_partner_in_those_regions():
    log = [clearance_event(scope={"regions": ["DE"]})]
    assert check(log, request(partner="tm:org/anyone", region="DE"))["verdict"] == "ok"
    assert check(log, request(partner="tm:org/anyone", region="FR"))["verdict"] == "block"


def test_a_scope_with_a_partner_only_covers_that_partner_in_any_region():
    log = [clearance_event(scope={"partner": ORG})]
    assert check(log, request(partner=ORG, region="ES"))["verdict"] == "ok"
    assert check(log, request(partner="tm:org/other", region="ES"))["verdict"] == "block"


def test_each_request_gets_the_clearance_of_its_own_scope():
    log = [clearance_event("aaaaaaaaaaaaaaaa", scope={"partner": ORG, "regions": ["DE"]}),
           clearance_event("bbbbbbbbbbbbbbbb", scope={"partner": "tm:org/other", "regions": ["FR"]},
                           at="2026-10-21T10:00:00+00:00")]
    assert check(log, request(partner=ORG, region="DE"))["clearance"] == "tm:clearance/aaaaaaaaaaaaaaaa"
    assert check(log, request(partner="tm:org/other", region="FR"))["clearance"] == "tm:clearance/bbbbbbbbbbbbbbbb"
    assert check(log, request(partner=ORG, region="FR"))["verdict"] == "block"


def test_an_expired_scoped_clearance_still_blocks_with_the_usual_reason():
    res = check([clearance_event(scope=SCOPE)], request(partner=ORG, region="DE", on="2028-01-01"))
    assert res["verdict"] == "block" and "no valid clearance" in res["reasons"][0]


def test_the_request_contract_takes_an_optional_partner_and_region():
    schema = load_schema("staffing-check.schema.json")
    v = Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/request"})
    assert list(v.iter_errors(request())) == []
    assert list(v.iter_errors(request(partner=ORG, region="US-CA"))) == []
    assert list(v.iter_errors({**request(), "region": "germany"}))
    assert list(v.iter_errors({**request(), "partner": "example-partner"}))
    assert schema["$id"] == "tm:contract/staffing-check@2"  # additive: the id is unchanged


def test_the_staffing_command_takes_partner_and_region(fictional_store, capsys):
    app.append_new(fictional_store, [clearance_event(scope=SCOPE)])
    base = ["staffing-check", "--private-dir", fictional_store, "--instructor", PARTNER, "--unit", UNIT, "--mode", "remote",
            "--date", "2026-11-02"]
    assert cli.main([str(a) for a in [*base, "--partner", ORG, "--region", "DE"]]) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "ok"
    assert cli.main([str(a) for a in [*base, "--partner", ORG, "--region", "FR"]]) == 2
    assert json.loads(capsys.readouterr().out)["verdict"] == "block"
    assert cli.main([str(a) for a in base]) == 2  # no partner or region named: a scoped clearance does not cover it


# --- the flow: a partner candidate clears on recordings ------------------------------------------------------------


def partner_roster(base):
    """The example roster, with the partner instructor delivering the example unit remotely (so it has a candidate)."""
    doc = yaml.safe_load(EXAMPLE_ROSTER_PATH.read_text(encoding="utf-8"))
    for row in doc["instructors"]:
        if row["instructor"] == PARTNER:
            row["delivers"] = [{"unit": UNIT, "modes": ["remote"]}]
    path = base / "roster-in.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def observe_of(private, observer, *, instructor=PARTNER, mode="remote", from_recording=None, day="2026-10-20",
               length="full", lead=True, score=3):
    scores = {d: score for d in DOMAINS}
    payload = {"instructor": instructor, "unit": UNIT, "observer": observer, "length": length, "lead": lead,
               "mode": mode, "rubric_version": RUBRIC, "scores": scores}
    if from_recording is not None:
        payload["from_recording"] = from_recording
    n = len(of_kind(private, "observation"))
    return put(private, events.make_event(
        "observation", instructor, observer, payload,
        id=tm_signoff.input_sha256(["partner-obs", observer, instructor, day, n])[:32], at=f"{day}T10:00:00+00:00"))


def dry_run_of(private, *, candidate=CAND, instructor=PARTNER, mode="remote", recorded=True, day="2026-10-21"):
    unit = units.load(UNIT)
    checks = {"clock": "pass"}
    if recorded is not None:
        checks[dry_run_flow.FROM_RECORDING] = "pass" if recorded else "fail"
    sid = tm_signoff.input_sha256(["partner-dry", candidate, day, str(recorded)])[:16]
    passed = recorded is not False
    return put(private, events.make_event(
        "dry_run", candidate, "tm:person/clearer-1",
        {"candidate": candidate, "instructor": instructor, "unit": UNIT, "mode": mode, "passed": passed,
         "checks": checks, "failure_injected": unit["failure_catalogue"][0]["id"] if passed else None,
         "fallback_exercised": passed, "environment_sha256": units.environment_sha256(unit), "signoff_id": sid},
        at=f"{day}T10:00:00+00:00"))


def build_partner_world(base):
    private = make_fictional_store(base)
    import_roster_ungated(private, partner_roster(base), T0)
    set_level(private, PARTNER, "lead-observed")
    set_level(private, K7, "lead-observed")
    for c in (P3, C5):
        set_level(private, c, "clearer")
        calibrate(private, c)
        hold(private, c)
    app.do_run(private, now=T0)  # opens the candidates


@pytest.fixture
def partner_store(fictional_store, cached_world):
    cached_world("partner_world", build_partner_world)
    return fictional_store


def rounds(private, candidate=CAND):
    return [e for e in of_kind(private, "step", candidate) if e["payload"].get("step") == EVIDENCE]


def blocked(private, candidate=CAND):
    return [e["payload"]["reasons"] for e in of_kind(private, "check", candidate) if e["payload"].get("step") == EVIDENCE]


def test_the_partner_candidate_exists(partner_store):
    assert CAND in app.load_state(partner_store).subjects


def test_live_observations_do_not_clear_a_partner(partner_store):
    observe_of(partner_store, P3)  # no from_recording
    observe_of(partner_store, C5, from_recording=False)
    dry_run_of(partner_store)
    app.do_run(partner_store, now=T0)
    assert rounds(partner_store) == []
    why = " ".join(blocked(partner_store)[-1])
    assert "recording" in why and "0 calibrated observations" in why


def test_the_same_live_observations_clear_a_non_partner(partner_store):
    for o in (P3, C5):
        observe_of(partner_store, o, instructor=K7, mode="in-person")
    unit = units.load(UNIT)
    put(partner_store, events.make_event(
        "dry_run", SME_CAND, "tm:person/clearer-1",
        {"candidate": SME_CAND, "instructor": K7, "unit": UNIT, "mode": "in-person", "passed": True,
         "checks": {"clock": "pass"}, "failure_injected": unit["failure_catalogue"][0]["id"],
         "fallback_exercised": True, "environment_sha256": units.environment_sha256(unit), "signoff_id": "ab" * 8},
        at="2026-10-21T10:00:00+00:00"))
    app.do_run(partner_store, now=T0)
    assert len(rounds(partner_store, SME_CAND)) == 1


def test_one_live_observation_among_recordings_is_not_counted(partner_store):
    observe_of(partner_store, P3, from_recording=True)
    observe_of(partner_store, C5, from_recording=False)
    dry_run_of(partner_store)
    app.do_run(partner_store, now=T0)
    assert rounds(partner_store) == []
    assert "1 calibrated observations" in " ".join(blocked(partner_store)[-1])


def test_a_dry_run_not_from_a_recording_does_not_count(partner_store):
    observe_of(partner_store, P3, from_recording=True)
    observe_of(partner_store, C5, from_recording=True)
    dry_run_of(partner_store, recorded=None)  # the run has no from-recording item at all
    app.do_run(partner_store, now=T0)
    assert rounds(partner_store) == []
    assert "no passed dry-run" in " ".join(blocked(partner_store)[-1])


def test_recorded_observations_and_a_recorded_dry_run_open_a_round(partner_store):
    observe_of(partner_store, P3, from_recording=True)
    observe_of(partner_store, C5, from_recording=True)
    dry_run_of(partner_store)
    app.do_run(partner_store, now=T0)
    (rnd,) = rounds(partner_store)
    assert len(rnd["payload"]["observations"]) == 2


def clear_the_partner(private):
    observe_of(private, P3, from_recording=True)
    observe_of(private, C5, from_recording=True)
    dry_run_of(private)
    app.do_run(private, now=T0)
    decide(private, D1, P3, cleared(), subject=CAND)
    decide(private, D2, C5, cleared(), subject=CAND)
    app.do_run(private, now=T0 + timedelta(days=1))
    return of_kind(private, "clearance", CAND)


def test_the_partner_clearance_carries_the_partner_and_regions_of_the_registration(partner_store):
    (clearance,) = clear_the_partner(partner_store)
    assert clearance["payload"]["scope"] == SCOPE
    assert events.check_event(clearance) == []


def test_a_non_partner_clearance_has_no_scope(partner_store):
    for o in (P3, C5):
        observe_of(partner_store, o, instructor=K7, mode="in-person")
    unit = units.load(UNIT)
    put(partner_store, events.make_event(
        "dry_run", SME_CAND, "tm:person/clearer-1",
        {"candidate": SME_CAND, "instructor": K7, "unit": UNIT, "mode": "in-person", "passed": True,
         "checks": {"clock": "pass"}, "failure_injected": unit["failure_catalogue"][0]["id"],
         "fallback_exercised": True, "environment_sha256": units.environment_sha256(unit), "signoff_id": "cd" * 8},
        at="2026-10-21T10:00:00+00:00"))
    app.do_run(partner_store, now=T0)
    decide(partner_store, D1, P3, cleared(), subject=SME_CAND)
    decide(partner_store, D2, C5, cleared(), subject=SME_CAND)
    app.do_run(partner_store, now=T0 + timedelta(days=1))
    (clearance,) = of_kind(partner_store, "clearance", SME_CAND)
    assert "scope" not in clearance["payload"]


def test_the_issued_clearance_blocks_staffing_outside_its_partner_and_region(partner_store):
    clear_the_partner(partner_store)
    log = app.read_events(partner_store)
    on = "2026-11-02"
    ok = staffing.check(log, request(partner=ORG, region="DE", on=on), STD["rules"])
    assert ok["verdict"] == "ok"
    for req in (request(partner="tm:org/another-partner", region="DE", on=on), request(partner=ORG, region="FR", on=on),
                request(on=on)):
        assert staffing.check(log, req, STD["rules"])["verdict"] == "block", req


def add_clearer_person(private, person, instructor):
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    slug = person.split("/")[1]
    doc["people"].append({"person": person, "name": "Clearer " + slug, "email": f"{slug}@example.com",
                          "roles": ["clearer"], "instructor": instructor})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_the_dry_run_checklist_of_a_partner_asks_whether_it_was_done_from_a_recording():
    unit = units.load(UNIT)
    ids = [i["id"] for i in dry_run_flow.checklist_items(unit, recorded=True)]
    assert dry_run_flow.FROM_RECORDING in ids
    assert dry_run_flow.FROM_RECORDING not in [i["id"] for i in dry_run_flow.checklist_items(unit)]


def signed_dry_run(private, candidate, signer_person, *, recorded_answer="pass"):
    st = app.load_state(private)
    unit = units.load(UNIT)
    partner = dry_run_flow.is_partner(st, st.subjects[candidate]["instructor"])
    checks = {i["id"]: {"result": "pass"} for i in dry_run_flow.checklist_items(unit, recorded=partner)}
    if partner:
        checks[dry_run_flow.FROM_RECORDING] = {"result": recorded_answer}
    doc = {"schema": "tm:contract/signoff@1", "id": "e1" * 8, "step": DRY_RUN, "subject_uri": candidate,
           "input_sha256": "0" * 64, "decision": "approve", "signer": signer_person, "signed_at": AT,
           "page_template_sha256": "0" * 64,
           "fields": {"checks": checks, "failure_injected": unit["failure_catalogue"][0]["id"]}}
    event = tm_signoff.to_event(doc, "x@example.com")
    out, _ = dry_run_flow._record(st, event, doc, datetime.fromisoformat(AT))
    return out


def test_a_partner_dry_run_passes_only_when_it_was_done_from_a_recording(partner_store):
    add_clearer_person(partner_store, "tm:person/clearer-p3", P3)
    (run,) = signed_dry_run(partner_store, CAND, "tm:person/clearer-p3")
    assert run["kind"] == "dry_run" and run["payload"]["passed"] is True
    assert run["payload"]["checks"][dry_run_flow.FROM_RECORDING] == "pass"
    (live,) = signed_dry_run(partner_store, CAND, "tm:person/clearer-p3", recorded_answer="fail")
    assert live["payload"]["passed"] is False
    (other,) = signed_dry_run(partner_store, SME_CAND, "tm:person/clearer-p3")
    assert dry_run_flow.FROM_RECORDING not in other["payload"]["checks"] and other["payload"]["passed"] is True


def assignment(private, observer, instructor, candidate):
    uri = "tm:assignment/" + tm_signoff.input_sha256(["partner-assignment", observer, instructor])[:16]
    put(private, events.make_event(
        "subject", uri, workflow.SYSTEM_ACTOR,
        {"subject_kind": "assignment", "opened_by": "tm:step/assignments-approved",
         "attrs": {"candidate": candidate, "instructor": instructor, "unit": UNIT, "mode": "remote", "observer": observer,
                   "length": "full", "lead": True, "delivery_ref": "partner-1"}},
        id=tm_signoff.input_sha256(["opened", uri])[:32], at="2026-10-26T09:00:00+00:00"))
    return uri


def observed_by(private, observer, answer):
    """Release the observation of a fresh single-observer assignment whose observer answered `answer` to the recording
    question (None: left it unanswered); returns the released `observation` event."""
    from teachermodel.flows import observation

    uri = assignment(private, observer, PARTNER, CAND)
    scores = {d: {"score": 3, "note": "evidence"} for d in DOMAINS}
    fields = {**scores, "date": "2026-10-27", "length": "full", "lead": True, "mode": "remote"}
    if answer is not None:
        fields["from_recording"] = answer
    sid = tm_signoff.input_sha256(["partner-observe", uri])[:16]
    doc = {"schema": "tm:contract/signoff@1", "id": sid, "step": "tm:step/observe", "subject_uri": uri,
           "input_sha256": "0" * 64, "decision": "approve", "signer": observer, "signed_at": "2026-10-28T09:00:00+00:00",
           "page_template_sha256": "0" * 64, "fields": fields}
    stored = private / "signoffs" / f"{sid}.json"
    stored.parent.mkdir(exist_ok=True)
    stored.write_text(json.dumps(doc), encoding="utf-8")
    app.append_new(private, [tm_signoff.to_event(doc, "x@example.com")])
    obs, _ = observation.release(app.load_state(private), uri, datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc))
    return obs


def test_the_observe_page_asks_whether_the_session_was_scored_from_a_recording(partner_store):
    uri = assignment(partner_store, P3, PARTNER, CAND)
    (spec, *_) = app._page_specs(app.load_state(partner_store), "tm:step/observe", uri)
    field = next(f for f in spec["fields"] if f["name"] == "from_recording")
    assert field["kind"] == "bool" and field["required"] is False


def test_a_released_observation_says_it_was_scored_from_a_recording(partner_store):
    obs = observed_by(partner_store, P3, True)
    assert events.check_event(obs) == [] and obs["payload"]["from_recording"] is True
    assert "from_recording" not in observed_by(partner_store, C5, None)["payload"]  # unanswered: the field is absent
    assert observed_by(partner_store, K7, False)["payload"]["from_recording"] is False


def test_the_observation_contract_takes_an_optional_from_recording():
    base = {"instructor": K7, "unit": UNIT, "observer": P3, "length": "full", "lead": True, "rubric_version": "0.2.0",
            "scores": {"technical-depth": 3}}
    assert validate({**base, "from_recording": True}, "observation.schema.json") == []
    assert validate(base, "observation.schema.json") == []
    assert validate({**base, "from_recording": "yes"}, "observation.schema.json")


# --- a scoped clearance is still a clearance (integration review finding 8) ------------------------------------------------


def test_a_partner_clearer_with_a_scoped_clearance_decides_within_their_modules(partner_store):
    from teachermodel.flows import clearance

    put(partner_store, clearance_event(scope=SCOPE))
    st = app.load_state(partner_store)
    assert clearance.holds_unit(st, PARTNER, UNIT, date(2026, 11, 2))
    assert not clearance.holds_unit(st, PARTNER, UNIT, date(2027, 10, 21))  # expired


def test_a_scoped_clearance_moves_the_level_proposal_and_keeps_an_author_candidate_closed(partner_store):
    from teachermodel.flows import levels, pathway

    put(partner_store, clearance_event(scope=SCOPE))
    st = app.load_state(partner_store)
    rows = {r["key"]: r for r in levels.proposals(st, date(2026, 11, 2))}
    assert rows[PARTNER]["to"] == "cleared"
    assert pathway._holds_valid_clearance(records.clearances(st.events), PARTNER, UNIT, "remote", date(2026, 11, 2),
                                          STD["rules"])


def gap_rows(private):
    return {r["key"]: r["summary"] for r in
            json.loads((private / "generated" / "gap-list.json").read_text(encoding="utf-8"))["rows"]}


def test_the_gap_list_reads_a_partner_delivery_in_the_partners_scope(partner_store):
    key = f"{PARTNER} {UNIT} remote"
    app.do_run(partner_store, now=T0)
    assert key in gap_rows(partner_store)
    put(partner_store, clearance_event(scope=SCOPE))
    app.do_run(partner_store, now=T0.replace(day=27))
    assert key not in gap_rows(partner_store)  # covered for the partner's organisation and its regions
    put(partner_store, clearance_event("fedcba9876543210", scope={"partner": "tm:org/someone-else"}))
    app.do_run(partner_store, now=T0.replace(day=28))
    assert key not in gap_rows(partner_store)


def test_the_gap_list_reports_a_partner_clearance_that_misses_a_region(partner_store, tmp_path):
    put(partner_store, clearance_event(scope={"partner": ORG, "regions": ["AT"]}))
    app.do_run(partner_store, now=T0)
    assert "no valid clearance" in gap_rows(partner_store)[f"{PARTNER} {UNIT} remote"]


def test_the_gap_list_reports_a_bench_block_as_a_gap(partner_store):
    from test_staffing import bench_events

    put(partner_store, clearance_event(scope=SCOPE))
    app.do_run(partner_store, now=T0)
    assert f"{PARTNER} {UNIT} remote" not in gap_rows(partner_store)
    for e in bench_events("exit", decided="2026-10-26", instructor=PARTNER):
        put(partner_store, e)
    app.do_run(partner_store, now=T0.replace(day=27))
    assert gap_rows(partner_store)[f"{PARTNER} {UNIT} remote"].endswith("bench decision: exit")
