"""Payload contracts of increment 2 (docs/plans/2026-10-24-increment-2-plan.md, "Machine contracts").

dry-run@1, calibration@1, clearance@1, subject@1, and observation@2 with its optional additions. Each schema has a
known-positive and a negative per rule; `events.check_event` validates the payload of each kind. Fictional data only.
"""

import copy

import pytest

from teachermodel import events, workflow
from teachermodel.standards import validate

UNIT = "sl:unit/example-agent-loop@1"
INSTRUCTOR = "tm:instructor/k7m2q"
OBSERVER = "tm:instructor/obs-a"
CANDIDATE = "tm:candidate/k7m2q--example-agent-loop-1--remote"
ASSIGNMENT = "tm:assignment/0123456789abcdef"
EXERCISE = "tm:exercise/fedcba9876543210"
CLEARANCE = "tm:clearance/00112233445566ff"
SIGNOFF = "0123456789abcdef0123456789abcdef"
SHA = "a" * 64

DRY_RUN = {
    "candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote", "passed": True,
    "checks": {"preflight-keys": "pass", "run-sheet-walk": "pass"}, "failure_injected": "rate-limit",
    "fallback_exercised": True, "environment_sha256": SHA, "signoff_id": SIGNOFF,
}
CALIBRATION = {
    "exercise": EXERCISE, "observer": OBSERVER, "unit": UNIT, "rubric_version": "0.2.0", "within_one_share": 0.95,
    "exact_share": 0.7, "passed": True, "signoff_id": SIGNOFF,
}
CLEARANCE_PAYLOAD = {
    "clearance": CLEARANCE, "candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "modes": ["remote"],
    "outcome": "cleared", "conditions": [], "recheck": None, "clearers": ["tm:instructor/clr-a", "tm:person/clr-b"],
    "observations": ["evt00000001", "evt00000002"], "issued": "2026-10-24", "expires": "2027-10-24",
    "framework_version": "0.2.0",
}
SUBJECTS = {
    "candidate": {"subject_kind": "candidate", "opened_by": "tm:step/open-candidates",
                  "attrs": {"instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote"}},
    "assignment": {"subject_kind": "assignment", "opened_by": "tm:step/assignments-approved",
                   "attrs": {"candidate": CANDIDATE, "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote",
                             "observer": OBSERVER, "length": "full", "lead": True, "delivery_ref": "delivery-17"}},
    "exercise": {"subject_kind": "exercise", "opened_by": "tm:cli/open-exercise",
                 "attrs": {"unit": UNIT, "rubric_version": "0.2.0", "recording_ref": "rec-1",
                           "observers": [OBSERVER], "reference_key": "calibration/ex-1"}},
}
OBSERVATION = {
    "instructor": INSTRUCTOR, "unit": UNIT, "observer": OBSERVER, "length": "full", "lead": True,
    "rubric_version": "0.2.0", "scores": {"technical-depth": 3},
}


def mut(doc, fn):
    d = copy.deepcopy(doc)
    fn(d)
    return d


# --- known positives ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("schema, doc", [
    ("dry-run.schema.json", DRY_RUN),
    ("calibration.schema.json", CALIBRATION),
    ("clearance.schema.json", CLEARANCE_PAYLOAD),
    ("subject.schema.json", SUBJECTS["candidate"]),
    ("subject.schema.json", SUBJECTS["assignment"]),
    ("subject.schema.json", SUBJECTS["exercise"]),
    ("observation.schema.json", OBSERVATION),
])
def test_known_positive(schema, doc):
    assert validate(doc, schema) == []


@pytest.mark.parametrize("name, ident", [
    ("dry-run", "dry-run@1"), ("calibration", "calibration@1"), ("clearance", "clearance@1"),
    ("subject", "subject@2"), ("observation", "observation@2"),
])
def test_contract_ids(name, ident):
    import json

    from teachermodel.standards import ROOT

    doc = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert doc["$id"] == f"tm:contract/{ident}"


# --- dry-run@1 ---------------------------------------------------------------------------------------------------

DRY_RUN_NEGATIVES = {
    "no candidate": lambda d: d.pop("candidate"),
    "candidate of another kind": lambda d: d.__setitem__("candidate", "tm:instructor/x"),
    "instructor of another kind": lambda d: d.__setitem__("instructor", "tm:candidate/x"),
    "module reference": lambda d: d.__setitem__("unit", "tm:module/x"),
    "unit without version": lambda d: d.__setitem__("unit", "sl:unit/x"),
    "unknown mode": lambda d: d.__setitem__("mode", "telepathy"),
    "passed not a boolean": lambda d: d.__setitem__("passed", "yes"),
    "no checks": lambda d: d.__setitem__("checks", {}),
    "check result unknown": lambda d: d["checks"].__setitem__("preflight-keys", "maybe"),
    "check result boolean": lambda d: d["checks"].__setitem__("preflight-keys", True),
    "fallback not a boolean": lambda d: d.__setitem__("fallback_exercised", "yes"),
    "no environment hash": lambda d: d.pop("environment_sha256"),
    "short environment hash": lambda d: d.__setitem__("environment_sha256", "abc"),
    "uppercase environment hash": lambda d: d.__setitem__("environment_sha256", "A" * 64),
    "no signoff id": lambda d: d.pop("signoff_id"),
    "signoff id too short": lambda d: d.__setitem__("signoff_id", "abc"),
    "unknown field": lambda d: d.__setitem__("notes", "free text never belongs here"),
    "passed with no failure injected": lambda d: d.__setitem__("failure_injected", None),
    "passed without the fallback": lambda d: d.__setitem__("fallback_exercised", False),
    "passed with a failed check": lambda d: d["checks"].__setitem__("run-sheet-walk", "fail"),
}


@pytest.mark.parametrize("case", sorted(DRY_RUN_NEGATIVES))
def test_dry_run_rejects(case):
    assert validate(mut(DRY_RUN, DRY_RUN_NEGATIVES[case]), "dry-run.schema.json"), case


def test_a_dry_run_that_did_not_pass_may_lack_a_failure_or_the_fallback():
    doc = mut(DRY_RUN, lambda d: d.update(passed=False, failure_injected=None, fallback_exercised=False,
                                          checks={"preflight-keys": "fail"}))
    assert validate(doc, "dry-run.schema.json") == []


# --- calibration@1 -----------------------------------------------------------------------------------------------

CALIBRATION_NEGATIVES = {
    "no exercise": lambda d: d.pop("exercise"),
    "exercise of another kind": lambda d: d.__setitem__("exercise", "tm:assignment/0123456789abcdef"),
    "observer not an instructor": lambda d: d.__setitem__("observer", "tm:person/x"),
    "module reference": lambda d: d.__setitem__("unit", "tm:module/x"),
    "no rubric version": lambda d: d.pop("rubric_version"),
    "share above one": lambda d: d.__setitem__("within_one_share", 1.01),
    "share below zero": lambda d: d.__setitem__("exact_share", -0.1),
    "share as text": lambda d: d.__setitem__("exact_share", "70%"),
    "no share": lambda d: d.pop("within_one_share"),
    "passed not a boolean": lambda d: d.__setitem__("passed", 1),
    "no signoff id": lambda d: d.pop("signoff_id"),
    "reference scores smuggled in": lambda d: d.__setitem__("reference", {"technical-depth": 3}),
    "scores smuggled in": lambda d: d.__setitem__("scores", {"technical-depth": 3}),
}


@pytest.mark.parametrize("case", sorted(CALIBRATION_NEGATIVES))
def test_calibration_rejects(case):
    assert validate(mut(CALIBRATION, CALIBRATION_NEGATIVES[case]), "calibration.schema.json"), case


# --- clearance@1 -------------------------------------------------------------------------------------------------

CLEARANCE_NEGATIVES = {
    "clearance id not 16 hex": lambda d: d.__setitem__("clearance", "tm:clearance/xyz"),
    "clearance id of another kind": lambda d: d.__setitem__("clearance", "tm:exercise/00112233445566ff"),
    "no candidate": lambda d: d.pop("candidate"),
    "module reference": lambda d: d.__setitem__("unit", "tm:module/x"),
    "no modes": lambda d: d.__setitem__("modes", []),
    "repeated mode": lambda d: d.__setitem__("modes", ["remote", "remote"]),
    "unknown mode": lambda d: d.__setitem__("modes", ["telepathy"]),
    "unknown outcome": lambda d: d.__setitem__("outcome", "maybe"),
    "one clearer": lambda d: d.__setitem__("clearers", ["tm:instructor/clr-a"]),
    "three clearers": lambda d: d.__setitem__("clearers", ["tm:instructor/a", "tm:instructor/b", "tm:instructor/c"]),
    "the same clearer twice": lambda d: d.__setitem__("clearers", ["tm:instructor/a", "tm:instructor/a"]),
    "clearer not a person": lambda d: d.__setitem__("clearers", ["tm:instructor/a", "Pat Example"]),
    "observations as text": lambda d: d.__setitem__("observations", "evt00000001"),
    "repeated observation": lambda d: d.__setitem__("observations", ["evt00000001", "evt00000001"]),
    "cleared without observations": lambda d: d.__setitem__("observations", []),
    "issued not a date": lambda d: d.__setitem__("issued", "yesterday"),
    "issued with a time": lambda d: d.__setitem__("issued", "2026-10-24T10:00:00Z"),
    "no expiry": lambda d: d.pop("expires"),
    "no framework version": lambda d: d.pop("framework_version"),
    "conditions as text": lambda d: d.__setitem__("conditions", "none"),
    "cleared with conditions but none listed": lambda d: d.update(outcome="cleared_with_conditions",
                                                                  recheck="2027-01-24"),
    "cleared with conditions but no recheck": lambda d: d.update(outcome="cleared_with_conditions",
                                                                 conditions=["Shadow one more delivery"]),
    "unknown field": lambda d: d.__setitem__("note", "free text never belongs here"),
}


@pytest.mark.parametrize("case", sorted(CLEARANCE_NEGATIVES))
def test_clearance_rejects(case):
    assert validate(mut(CLEARANCE_PAYLOAD, CLEARANCE_NEGATIVES[case]), "clearance.schema.json"), case


def test_clearance_with_conditions_carries_conditions_and_a_recheck():
    doc = mut(CLEARANCE_PAYLOAD, lambda d: d.update(outcome="cleared_with_conditions", recheck="2027-01-24",
                                                    conditions=["Shadow one more delivery"]))
    assert validate(doc, "clearance.schema.json") == []


@pytest.mark.parametrize("outcome", ["not_yet", "expired", "revoked"])
def test_a_clearance_outcome_without_a_grant_may_have_no_observations(outcome):
    doc = mut(CLEARANCE_PAYLOAD, lambda d: d.update(outcome=outcome, observations=[]))
    assert validate(doc, "clearance.schema.json") == []


# --- subject@1 ---------------------------------------------------------------------------------------------------

SUBJECT_NEGATIVES = {
    "candidate": {
        "no instructor": lambda d: d["attrs"].pop("instructor"),
        "no unit": lambda d: d["attrs"].pop("unit"),
        "no mode": lambda d: d["attrs"].pop("mode"),
        "unknown mode": lambda d: d["attrs"].__setitem__("mode", "telepathy"),
        "module reference": lambda d: d["attrs"].__setitem__("unit", "tm:module/x"),
        "instructor of another kind": lambda d: d["attrs"].__setitem__("instructor", "tm:person/x"),
        "extra attribute": lambda d: d["attrs"].__setitem__("name", "Pat Example"),
        "an assignment attribute": lambda d: d["attrs"].__setitem__("observer", OBSERVER),
    },
    "assignment": {
        "no candidate": lambda d: d["attrs"].pop("candidate"),
        "candidate of another kind": lambda d: d["attrs"].__setitem__("candidate", ASSIGNMENT),
        "no observer": lambda d: d["attrs"].pop("observer"),
        "observer of another kind": lambda d: d["attrs"].__setitem__("observer", "tm:person/x"),
        "no length": lambda d: d["attrs"].pop("length"),
        "unknown length": lambda d: d["attrs"].__setitem__("length", "medium"),
        "lead as text": lambda d: d["attrs"].__setitem__("lead", "yes"),
        "no delivery_ref": lambda d: d["attrs"].pop("delivery_ref"),
        "empty delivery_ref": lambda d: d["attrs"].__setitem__("delivery_ref", ""),
        "recording_ref as a number": lambda d: d["attrs"].__setitem__("recording_ref", 7),
        "extra attribute": lambda d: d["attrs"].__setitem__("notes", "x"),
    },
    "exercise": {
        "no unit": lambda d: d["attrs"].pop("unit"),
        "no rubric version": lambda d: d["attrs"].pop("rubric_version"),
        "no recording_ref": lambda d: d["attrs"].pop("recording_ref"),
        "no observers": lambda d: d["attrs"].__setitem__("observers", []),
        "observer not an instructor": lambda d: d["attrs"].__setitem__("observers", ["tm:person/x"]),
        "repeated observer": lambda d: d["attrs"].__setitem__("observers", [OBSERVER, OBSERVER]),
        "no reference_key": lambda d: d["attrs"].pop("reference_key"),
        "reference scores in the attrs": lambda d: d["attrs"].__setitem__("reference", {"technical-depth": 3}),
    },
}


@pytest.mark.parametrize("kind, case", [(k, c) for k, cases in SUBJECT_NEGATIVES.items() for c in sorted(cases)])
def test_subject_rejects_per_kind(kind, case):
    assert validate(mut(SUBJECTS[kind], SUBJECT_NEGATIVES[kind][case]), "subject.schema.json"), (kind, case)


SUBJECT_COMMON_NEGATIVES = {
    "unknown kind": lambda d: d.__setitem__("subject_kind", "wizard"),
    "instructor is not a child kind": lambda d: d.__setitem__("subject_kind", "instructor"),
    "no kind": lambda d: d.pop("subject_kind"),
    "no attrs": lambda d: d.pop("attrs"),
    "attrs as a list": lambda d: d.__setitem__("attrs", []),
    "no opener": lambda d: d.pop("opened_by"),
    "opener not a step": lambda d: d.__setitem__("opened_by", "open-candidates"),
    "unknown field": lambda d: d.__setitem__("note", "x"),
}


@pytest.mark.parametrize("case", sorted(SUBJECT_COMMON_NEGATIVES))
def test_subject_rejects_common(case):
    assert validate(mut(SUBJECTS["candidate"], SUBJECT_COMMON_NEGATIVES[case]), "subject.schema.json"), case


def test_subject_attrs_must_match_the_kind():
    wrong = mut(SUBJECTS["candidate"], lambda d: d.__setitem__("attrs", SUBJECTS["exercise"]["attrs"]))
    assert validate(wrong, "subject.schema.json")


def test_assignment_may_carry_a_recording_ref():
    doc = mut(SUBJECTS["assignment"], lambda d: d["attrs"].__setitem__("recording_ref", "rec-9"))
    assert validate(doc, "subject.schema.json") == []


# --- observation@2 additions -------------------------------------------------------------------------------------


def test_observation_accepts_the_optional_additions():
    doc = mut(OBSERVATION, lambda d: d.update(assignment=ASSIGNMENT, delivery_ref="delivery-17",
                                              recorded_at="2026-10-24T10:00:00+00:00"))
    assert validate(doc, "observation.schema.json") == []


OBSERVATION_NEGATIVES = {
    "assignment of another kind": lambda d: d.__setitem__("assignment", CANDIDATE),
    "assignment id too short": lambda d: d.__setitem__("assignment", "tm:assignment/abc"),
    "empty delivery_ref": lambda d: d.__setitem__("delivery_ref", ""),
    "recorded_at not a date-time": lambda d: d.__setitem__("recorded_at", "yesterday"),
    "unknown field": lambda d: d.__setitem__("notes", "free text never belongs here"),
}


@pytest.mark.parametrize("case", sorted(OBSERVATION_NEGATIVES))
def test_observation_rejects_malformed_additions(case):
    base = mut(OBSERVATION, lambda d: d.update(assignment=ASSIGNMENT, delivery_ref="delivery-17",
                                               recorded_at="2026-10-24T10:00:00+00:00"))
    assert validate(mut(base, OBSERVATION_NEGATIVES[case]), "observation.schema.json"), case


# --- events.check_event validates each payload -------------------------------------------------------------------

ACTOR = "tm:system/teachermodel"


def event(kind, subject, payload, actor=ACTOR):
    return events.make_event(kind, subject, actor, payload, id="evt00000099", at="2026-10-24T10:00:00+00:00")


GOOD_EVENTS = [
    ("dry_run", CANDIDATE, DRY_RUN),
    ("calibration", EXERCISE, CALIBRATION),
    ("clearance", CANDIDATE, CLEARANCE_PAYLOAD),
    ("subject", CANDIDATE, SUBJECTS["candidate"]),
    ("subject", ASSIGNMENT, SUBJECTS["assignment"]),
    ("subject", EXERCISE, SUBJECTS["exercise"]),
]


@pytest.mark.parametrize("kind, subject, payload", GOOD_EVENTS)
def test_check_event_accepts_a_valid_payload(kind, subject, payload):
    assert events.check_event(event(kind, subject, payload)) == []


@pytest.mark.parametrize("kind, subject, payload", GOOD_EVENTS)
def test_check_event_rejects_an_invalid_payload(kind, subject, payload):
    errors = events.check_event(event(kind, subject, {**payload, "unexpected": 1}))
    assert errors and all(e.startswith("payload/") for e in errors), errors
    assert events.check_event(event(kind, subject, {}))


def test_check_event_rejects_an_observation_with_a_malformed_addition():
    bad = event("observation", INSTRUCTOR, {**OBSERVATION, "assignment": "tm:assignment/x"})
    assert events.check_event(bad)


def test_events_append_refuses_an_invalid_payload(tmp_path):
    with pytest.raises(events.EventError):
        events.append(tmp_path / "e.jsonl", event("dry_run", CANDIDATE, {"passed": True}))


# --- a subject event's URI belongs to its kind ---------------------------------------------------------------------


@pytest.mark.parametrize("subject_kind, uri", [
    ("candidate", ASSIGNMENT), ("candidate", INSTRUCTOR), ("assignment", CANDIDATE), ("exercise", ASSIGNMENT),
    ("assignment", "tm:assignment/xyz"), ("exercise", "tm:exercise/0123"),
    ("candidate", "tm:candidate/k7m2q--example-agent-loop-1--hybrid"),  # not the URI of these attrs
    ("candidate", "tm:candidate/someone-else--example-agent-loop-1--remote"),
])
def test_check_event_refuses_a_subject_uri_that_does_not_fit_its_kind(subject_kind, uri):
    errors = events.check_event(event("subject", uri, SUBJECTS[subject_kind]))
    assert errors and any("subject_uri" in e for e in errors), errors


def test_candidate_uri_is_derived_from_the_attrs():
    assert workflow.candidate_uri(INSTRUCTOR, UNIT, "remote") == CANDIDATE
    assert workflow.candidate_uri("tm:instructor/p3x9d", "sl:unit/a-b@12", "in-person") == \
        "tm:candidate/p3x9d--a-b-12--in-person"
