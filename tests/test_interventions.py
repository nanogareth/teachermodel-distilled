"""interventions.py: chains as data, conditions as rules, the outbox derived afresh on every run (decision 0029).
One-week simulated store with clearances, a schedule, an audition and a quality trigger added. Generated data only."""

import json
import re
from datetime import date, datetime, timezone

import pytest
import yaml
from jsonschema import Draft202012Validator

from teachermodel import app, events, interventions, simulate, surfaces
from teachermodel.standards import ROOT

from test_surfaces import SESSIONS, UNIT, clearance

NOW = datetime(2026, 10, 30, 7, 0, tzinfo=timezone.utc)
A, D = "tm:instructor/a1c4f", "tm:instructor/d7h2k"


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("interventions") / "store"
    try:
        simulate.simulate(s, weeks=1, end=date(2026, 10, 23))
        log = s / app.EVENT_LOG
        events.append(log, clearance(A, ["in-person"], "2026-11-10"))
        events.append(log, clearance(D, ["in-person"], "2027-10-01"))
        events.append(log, events.make_event(
            "check", D, "tm:system/teachermodel",
            {"step": "tm:step/quality-review", "instructor": D, "result": "trigger", "trigger": "score_drop"},
            at="2026-10-28T06:00:00+00:00"))
        (s / "inputs").mkdir(exist_ok=True)
        (s / "inputs" / "schedule.yaml").write_text(yaml.safe_dump(
            {"schema": "tm:contract/schedule@1", "exported_at": "2026-10-28T07:00:00Z", "sessions": SESSIONS},
            sort_keys=False), encoding="utf-8")
        folder = s / "auditions" / "a-0verd1"
        folder.mkdir(parents=True)
        (folder / "audition.yaml").write_text(yaml.safe_dump(
            {"id": "a-0verd1", "unit": UNIT, "mode": "remote", "opened": "2026-10-20", "observers": [A, D],
             "assigned": "2026-10-21"}), encoding="utf-8")
        yield s
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def outbox(store):
    ctx = surfaces.context(store, NOW)
    try:
        return interventions.build(interventions.scope(ctx))
    finally:
        ctx.con.close()  # before any other run rebuilds the index (Windows will not replace an open file)


def rows(outbox, chain):
    return [a for a in outbox["actions"] if a["chain"] == chain]


def test_the_standards_file_is_sound():
    assert interventions.problems(interventions.chains_doc()) == []


def test_a_bad_chain_or_button_is_named():
    doc = interventions.chains_doc()
    doc["chains"][0]["condition"] = "made-up"
    doc["chains"][0]["steps"][1]["button"] = "no-such-button"
    doc["buttons"][0]["writes"] = {"m365": ["send_mail"]}
    found = interventions.problems(doc)
    assert any("made-up" in p for p in found) and any("no-such-button" in p for p in found)
    assert any("reads only" in p for p in found)


def test_the_outbox_fits_its_contract_and_names_no_one(store, outbox):
    schema = json.loads((ROOT / "contracts" / "outbox.schema.json").read_text(encoding="utf-8"))
    assert not list(Draft202012Validator(schema).iter_errors(outbox))
    assert outbox["mode"] == "dry-run"
    names = [p["name"] for p in yaml.safe_load((store / "identities" / "people.yaml").read_text(encoding="utf-8"))
             ["people"] if p.get("name")]
    text = json.dumps(outbox)
    assert names and not [n for n in names if n in text]


def test_ids_are_the_same_on_every_run(store, outbox):
    ctx = surfaces.context(store, NOW)
    try:
        again = interventions.build(interventions.scope(ctx))
    finally:
        ctx.con.close()
    assert [a["action_id"] for a in again["actions"]] == [a["action_id"] for a in outbox["actions"]]
    assert len({a["action_id"] for a in outbox["actions"]}) == len(outbox["actions"])


def test_a_session_at_risk_tells_books_and_escalates_by_its_own_clock(outbox):
    c2 = [a for a in rows(outbox, "C2") if a["subject"] == "onboarding-c4"]
    steps = {(a["step"], a["role"]) for a in c2}
    assert ("tell", "lead") in steps and ("tell", "coordinator") in steps and ("book", "lead") in steps
    assert not [a for a in c2 if a["step"] in ("cover", "account")]  # due 7 days before 9 Nov: not yet
    tell = next(a for a in c2 if a["step"] == "tell" and a["role"] == "lead")
    assert (tell["to"], tell["due"], tell["state"], tell["channel"]) == (A, "2026-10-10", "overdue", "chat.post")
    book = next(a for a in c2 if a["step"] == "book")
    assert (book["button"], book["channel"], book["policy"]) == ("propose-slots", "calendar.propose", "auto-after-shadow")
    escalation = [a for a in c2 if a["kind"] == "escalate"]
    assert escalation and escalation[0]["due"] == "2026-10-12"  # one working day after the first step's due day
    assert escalation[0]["role"] == "head-of-training" and escalation[0]["to"].startswith("tm:person/")


def test_an_unchecked_lab_reaches_its_maintainer_even_unresolved(outbox):
    c5 = [a for a in rows(outbox, "C5") if a["subject"] == "cohort12-agg-lab"]
    maint = [a for a in c5 if a["role"] == "lab-maintainer"]
    assert maint and all(a["to"] is None for a in maint)  # nobody holds the role yet: shown, never dropped
    triage = next(a for a in c5 if a["step"] == "triage")
    assert (triage["channel"], triage["policy"], triage["button"]) == ("claude.act", "approve-each-call", "triage-lab")
    assert c5[0]["facts"]["lab"] == "aggregates-only-export"


def test_a_delivery_is_chased_only_a_week_after_it(outbox):
    assert not [a for a in rows(outbox, "C6") if a["subject"] == "agent-loop-g2"]  # 27 Oct: due 3 Nov


def test_an_overdue_audition_form_reminds_each_waiting_observer(outbox):
    c9 = rows(outbox, "C9")
    assert {a["to"] for a in c9 if a["step"] == "remind"} == {A, D}
    replace = next(a for a in c9 if a["step"] == "replace")
    assert (replace["role"], replace["channel"], replace["button"]) == ("coordinator", "signed-page",
                                                                         "replacement-observer")


def test_a_quality_trigger_tells_the_coach_and_instructor(outbox):
    c1 = rows(outbox, "C1")
    tell = [a for a in c1 if a["step"] == "tell"]
    assert {a["role"] for a in tell} == {"coach", "instructor"}
    assert next(a for a in tell if a["role"] == "instructor")["to"] == D
    assert not [a for a in c1 if a["step"] == "plan"]  # due ten days after 28 Oct


def test_a_source_that_never_reported_is_an_item_for_its_owner(outbox):
    c8 = rows(outbox, "C8")
    assert {a["subject"] for a in c8} >= {"daily-job", "release-check"}
    assert next(a for a in c8 if a["subject"] == "daily-job")["to"].startswith("tm:person/")
    assert not [a for a in c8 if a["kind"] == "escalate"]  # no anchor to count from: shown, not escalated


def test_chains_without_a_source_are_listed_as_waiting(outbox):
    assert [w["chain"] for w in outbox["waiting"]] == ["C3", "C11", "C13"]


@pytest.mark.parametrize("start, n, expected", [
    (date(2026, 10, 30), 1, date(2026, 11, 2)),   # Friday + 1 working day = Monday
    (date(2026, 10, 30), 0, date(2026, 10, 30)),
    (date(2026, 10, 31), 1, date(2026, 11, 2)),   # from a Saturday
    (date(2026, 10, 26), 5, date(2026, 11, 2)),
])
def test_working_days(start, n, expected):
    assert interventions.add_working_days(start, n) == expected


def test_a_step_one_person_acts_on_goes_to_one_holder_of_the_role(outbox):
    """Two coordinators both get the message, but only one is asked to act (else two tickets for one delivery)."""
    acting = [a for a in outbox["actions"] if a["kind"] in ("act", "decide")]
    per_step = {}
    for a in acting:
        per_step.setdefault((a["instance"], a["step"], a["role"]), []).append(a["to"])
    assert acting and all(len(v) == 1 for v in per_step.values())
    replace = next(a for a in outbox["actions"] if a["chain"] == "C9" and a["step"] == "replace")
    told = [a for a in outbox["actions"] if a["chain"] == "C5" and a["step"] == "tell" and a["role"] == "coordinator"]
    assert replace["to"].startswith("tm:person/") and len({a["to"] for a in told}) == len(told) >= 1
