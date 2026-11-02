"""Payload contracts of increment 3 (docs/plans/2026-10-25-increment-3-plan.md, "Machine contracts"; decision 0014).

event@4 (+ `outcome`), subject@2 (+ cycle, sample, bench, override), audit@1, coaching-cycle@1, cpd@1, outcome@1,
bench-decision@1, outcome-import@1, and the additive `scope` of clearance@1. Each schema has a known positive and a
negative per rule; `events.check_event` validates the payload and the subject URI of each kind. Fictional data only.
"""

import copy
import json

import pytest

from teachermodel import events
from teachermodel.events import make_event
from teachermodel.standards import ROOT, validate
from teachermodel.workflow import needs_met
from teachermodel.workflow import subjects as engine_subjects

UNIT = "sl:unit/example-agent-loop@1"
INSTRUCTOR = "tm:instructor/k7m2q"
OBSERVER = "tm:instructor/obs-a"
SECOND = "tm:instructor/obs-b"
COACH = "tm:instructor/coach-a"
SIGNOFF = "0123456789abcdef0123456789abcdef"
SHA = "b" * 64
CYCLE = "tm:cycle/k7m2q--2"
SAMPLE = "tm:sample/2026Q4--evt00000001"
BENCH = "tm:bench/k7m2q--1"
OVERRIDE = "tm:override/0123456789abcdef"
AT = "2026-10-25T10:00:00+00:00"


def mut(doc, fn):
    d = copy.deepcopy(doc)
    fn(d)
    return d


AUDIT = {
    "sample": SAMPLE, "observation": "evt00000001", "observer": OBSERVER, "second_observer": SECOND,
    "within_one_share": 0.85, "exact_share": 0.5, "agreed": False, "referred_to_calibration": True,
    "signoff_id": SIGNOFF,
}
COACHING_CYCLE = {
    "cycle": CYCLE, "instructor": INSTRUCTOR, "coach": COACH, "number": 2, "intensity": "triggered",
    "focus": ["technical-depth"], "phase": "closed", "change": {"technical-depth": 1, "facilitation": -0.5},
    "signoff_id": SIGNOFF,
}
CPD = {
    "instructor": INSTRUCTOR, "activity_key": "cpd/k7m2q/2026-10-20", "domains": ["technical-depth"], "hours": 2.5,
    "logged_on": "2026-10-20", "signoff_id": SIGNOFF,
}
OUTCOME = {
    "delivery_ref": "delivery-17", "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote",
    "delivered_on": "2026-10-20", "learners_assessed": 18, "score": 71.5, "baseline": 80.0, "feedback": 4.1,
    "feedback_median": 4.4, "source": "lms-export",
}
BENCH_DECISION = {
    "bench": BENCH, "instructor": INSTRUCTOR, "decision": "return-to-co-teaching", "rationale_key": "bench/k7m2q--1",
    "evidence_pack_sha256": SHA, "decided_by": "tm:person/head", "signoff_id": SIGNOFF,
}
DELIVERY = {k: v for k, v in OUTCOME.items() if k != "source"}
OUTCOME_IMPORT = {
    "schema": "tm:contract/outcome-import@1", "source": "lms-export", "exported_at": "2026-10-25T08:00:00Z",
    "deliveries": [DELIVERY],
}
CLEARANCE_PAYLOAD = {
    "clearance": "tm:clearance/00112233445566ff", "candidate": "tm:candidate/k7m2q--example-agent-loop-1--remote",
    "instructor": INSTRUCTOR, "unit": UNIT, "modes": ["remote"], "outcome": "cleared", "conditions": [],
    "recheck": None, "clearers": ["tm:instructor/clr-a", "tm:person/clr-b"],
    "observations": ["evt00000001", "evt00000002"], "issued": "2026-10-24", "expires": "2027-10-24",
    "framework_version": "0.2.0",
}
SUBJECTS = {
    "cycle": ("tm:cycle/k7m2q--2", {"subject_kind": "cycle", "opened_by": "tm:step/open-cycles", "attrs": {
        "instructor": INSTRUCTOR, "coach": COACH, "number": 2, "intensity": "standard", "focus": ["technical-depth"]}}),
    "sample": (SAMPLE, {"subject_kind": "sample", "opened_by": "tm:step/draw-sample", "attrs": {
        "observation": "evt00000001", "instructor": INSTRUCTOR, "observer": OBSERVER, "quarter": "2026Q4",
        "second_observer": SECOND}}),
    "bench": (BENCH, {"subject_kind": "bench", "opened_by": "tm:step/open-bench", "attrs": {
        "instructor": INSTRUCTOR, "reason": "contract-end"}}),
    "override": (OVERRIDE, {"subject_kind": "override", "opened_by": "tm:cli/request-override", "attrs": {
        "instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote", "date": "2026-11-02", "request_ref": "override/req-1"}}),
}

PAYLOADS = {
    "audit": ("audit.schema.json", AUDIT, SAMPLE),
    "coaching_cycle": ("coaching-cycle.schema.json", COACHING_CYCLE, CYCLE),
    "cpd": ("cpd.schema.json", CPD, INSTRUCTOR),
    "outcome": ("outcome.schema.json", OUTCOME, INSTRUCTOR),
    "bench_decision": ("bench-decision.schema.json", BENCH_DECISION, BENCH),
}


def contract(name):
    return json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))


def event(kind, uri, payload, actor="tm:person/owner"):
    return make_event(kind, uri, actor, payload, id="evt00000099", at=AT)


# --- identity: ids, kinds, history ------------------------------------------------------------------------


@pytest.mark.parametrize("name, ident", [
    ("event", "event@5"), ("subject", "subject@2"), ("audit", "audit@1"), ("coaching-cycle", "coaching-cycle@1"),
    ("cpd", "cpd@1"), ("outcome", "outcome@1"), ("bench-decision", "bench-decision@1"),
    ("outcome-import", "outcome-import@1"), ("clearance", "clearance@1"), ("people", "people@1"),
])
def test_contract_ids(name, ident):
    assert contract(f"{name}.schema.json")["$id"] == f"tm:contract/{ident}"


def test_event_v4_adds_exactly_the_outcome_kind_and_v3_is_kept():
    new, v3 = contract("v4/event.schema.json"), contract("v3/event.schema.json")
    assert (new["$id"], v3["$id"]) == ("tm:contract/event@4", "tm:contract/event@3")
    assert "outcome" in new["properties"]["kind"]["enum"] and "outcome" not in v3["properties"]["kind"]["enum"]
    assert sorted(set(new["properties"]["kind"]["enum"]) - {"outcome"}) == sorted(v3["properties"]["kind"]["enum"])


def test_subject_v2_adds_its_kinds_and_v1_is_kept():
    """Decision 0014 added four kinds within subject@2; decision 0021 added appeal, decision 0024 recalibration."""
    new, v1 = contract("subject.schema.json"), contract("v1/subject.schema.json")
    assert (new["$id"], v1["$id"]) == ("tm:contract/subject@2", "tm:contract/subject@1")
    kinds, old = new["properties"]["subject_kind"]["enum"], v1["properties"]["subject_kind"]["enum"]
    assert sorted(set(kinds) - set(old)) == ["appeal", "bench", "cycle", "override", "recalibration", "sample"] and set(old) <= set(kinds)


# v3 and subject@1 are history now: pinned to the bytes as they stood before decision 0014.
V3_SHA256 = {"event.schema.json": "85111cc58c3d51f44eaef7b8a7a4f65f5066b563889bd0b1eb3ea38129e1ea69"}
V1_SUBJECT_SHA256 = {"subject.schema.json": "85e39f165787fe44a602f15408dc23d84761e38f64ab915566ae881f07bd9464"}


def test_v3_and_v1_subject_schemas_unchanged():
    import hashlib

    for name, digest in V3_SHA256.items():
        assert hashlib.sha256((ROOT / "contracts" / "v3" / name).read_bytes()).hexdigest() == digest, name
    for name, digest in V1_SUBJECT_SHA256.items():
        assert hashlib.sha256((ROOT / "contracts" / "v1" / name).read_bytes()).hexdigest() == digest, name


def test_the_workflows_schema_lists_the_new_subject_kinds():
    enum = contract("workflows.schema.json")["$defs"]["step"]["properties"]["subject"]["enum"]
    assert {"cycle", "sample", "bench", "override"} <= set(enum)


# --- known positives, through the schema and through check_event -------------------------------------------


@pytest.mark.parametrize("kind", sorted(PAYLOADS))
def test_payload_known_positive(kind):
    schema, payload, uri = PAYLOADS[kind]
    assert validate(payload, schema) == []
    assert events.check_event(event(kind, uri, payload)) == []


def test_optional_fields_may_be_absent():
    assert validate({k: v for k, v in COACHING_CYCLE.items() if k not in ("change", "signoff_id")},
                    "coaching-cycle.schema.json") == []
    assert validate({k: v for k, v in OUTCOME.items() if k not in ("feedback", "feedback_median")},
                    "outcome.schema.json") == []


@pytest.mark.parametrize("kind", sorted(SUBJECTS))
def test_subject_known_positive(kind):
    uri, payload = SUBJECTS[kind]
    assert validate(payload, "subject.schema.json") == []
    assert events.check_event(event("subject", uri, payload, "tm:system/teachermodel")) == []


def test_subject_v2_still_accepts_the_v1_kinds():
    candidate = {"subject_kind": "candidate", "opened_by": "tm:step/open-candidates",
                 "attrs": {"instructor": INSTRUCTOR, "unit": UNIT, "mode": "remote"}}
    assert validate(candidate, "subject.schema.json") == []


def test_event_v4_accepts_the_outcome_kind():
    assert events.check_event(event("outcome", INSTRUCTOR, OUTCOME, "tm:system/teachermodel")) == []


# --- negatives ---------------------------------------------------------------------------------------------

AUDIT_NEGATIVES = {
    "no sample": lambda d: d.pop("sample"),
    "sample of another kind": lambda d: d.__setitem__("sample", "tm:cycle/k7m2q--2"),
    "no observation": lambda d: d.pop("observation"),
    "short observation id": lambda d: d.__setitem__("observation", "e1"),
    "observer not an instructor": lambda d: d.__setitem__("observer", "tm:person/x"),
    "no second observer": lambda d: d.pop("second_observer"),
    "second observer not an instructor": lambda d: d.__setitem__("second_observer", "x"),
    "share above one": lambda d: d.__setitem__("within_one_share", 1.01),
    "share below zero": lambda d: d.__setitem__("exact_share", -0.1),
    "share as text": lambda d: d.__setitem__("exact_share", "half"),
    "agreed as text": lambda d: d.__setitem__("agreed", "yes"),
    "no referral flag": lambda d: d.pop("referred_to_calibration"),
    "referral as text": lambda d: d.__setitem__("referred_to_calibration", "yes"),
    "no signoff id": lambda d: d.pop("signoff_id"),
    "short signoff id": lambda d: d.__setitem__("signoff_id", "abc"),
    "unknown field": lambda d: d.__setitem__("first_scores", {"technical-depth": 3}),
}
CYCLE_NEGATIVES = {
    "no cycle": lambda d: d.pop("cycle"),
    "cycle of another kind": lambda d: d.__setitem__("cycle", "tm:bench/k7m2q--1"),
    "instructor of another kind": lambda d: d.__setitem__("instructor", "tm:person/x"),
    "coach of another kind": lambda d: d.__setitem__("coach", "tm:person/x"),
    "number zero": lambda d: d.__setitem__("number", 0),
    "number as text": lambda d: d.__setitem__("number", "2"),
    "unknown intensity": lambda d: d.__setitem__("intensity", "intense"),
    "no focus": lambda d: d.pop("focus"),
    "empty focus": lambda d: d.__setitem__("focus", []),
    "repeated focus": lambda d: d.__setitem__("focus", ["technical-depth", "technical-depth"]),
    "focus not a domain id": lambda d: d.__setitem__("focus", ["Technical Depth"]),
    "unknown phase": lambda d: d.__setitem__("phase", "done"),
    "no phase": lambda d: d.pop("phase"),
    "change as a list": lambda d: d.__setitem__("change", [1]),
    "change delta as text": lambda d: d["change"].__setitem__("technical-depth", "up"),
    "change key not a domain id": lambda d: d["change"].__setitem__("Technical Depth", 1),
    "short signoff id": lambda d: d.__setitem__("signoff_id", "abc"),
    "unknown field": lambda d: d.__setitem__("feedback_text", "free text never belongs here"),
}
CPD_NEGATIVES = {
    "no instructor": lambda d: d.pop("instructor"),
    "instructor of another kind": lambda d: d.__setitem__("instructor", "tm:person/x"),
    "no activity key": lambda d: d.pop("activity_key"),
    "empty activity key": lambda d: d.__setitem__("activity_key", ""),
    "no domains": lambda d: d.__setitem__("domains", []),
    "repeated domain": lambda d: d.__setitem__("domains", ["technical-depth", "technical-depth"]),
    "domain not an id": lambda d: d.__setitem__("domains", ["Technical Depth"]),
    "zero hours": lambda d: d.__setitem__("hours", 0),
    "negative hours": lambda d: d.__setitem__("hours", -1),
    "hours as text": lambda d: d.__setitem__("hours", "two"),
    "date with a time": lambda d: d.__setitem__("logged_on", "2026-10-20T09:00:00Z"),
    "no signoff id": lambda d: d.pop("signoff_id"),
    "unknown field": lambda d: d.__setitem__("activity", "Read a book on agents"),
}
OUTCOME_NEGATIVES = {
    "learner email": lambda d: d.__setitem__("learner_email", "learner@example.test"),
    "learner name": lambda d: d.__setitem__("learner", "Pat Example"),
    "learner scores": lambda d: d.__setitem__("learners", [{"score": 50}]),
    "no delivery ref": lambda d: d.pop("delivery_ref"),
    "empty delivery ref": lambda d: d.__setitem__("delivery_ref", ""),
    "instructor of another kind": lambda d: d.__setitem__("instructor", "tm:person/x"),
    "module reference": lambda d: d.__setitem__("unit", "tm:module/x"),
    "unknown mode": lambda d: d.__setitem__("mode", "telepathy"),
    "no delivery date": lambda d: d.pop("delivered_on"),
    "delivery date with a time": lambda d: d.__setitem__("delivered_on", "2026-10-20T09:00:00Z"),
    "learners as text": lambda d: d.__setitem__("learners_assessed", "18"),
    "fractional learners": lambda d: d.__setitem__("learners_assessed", 17.5),
    "negative learners": lambda d: d.__setitem__("learners_assessed", -1),
    "score as text": lambda d: d.__setitem__("score", "high"),
    "negative score": lambda d: d.__setitem__("score", -1),
    "no baseline": lambda d: d.pop("baseline"),
    "feedback as text": lambda d: d.__setitem__("feedback", "good"),
    "no source": lambda d: d.pop("source"),
    "empty source": lambda d: d.__setitem__("source", ""),
}
BENCH_DECISION_NEGATIVES = {
    "no bench": lambda d: d.pop("bench"),
    "bench of another kind": lambda d: d.__setitem__("bench", "tm:cycle/k7m2q--1"),
    "instructor of another kind": lambda d: d.__setitem__("instructor", "tm:person/x"),
    "unknown decision": lambda d: d.__setitem__("decision", "fire"),
    "no decision": lambda d: d.pop("decision"),
    "no rationale key": lambda d: d.pop("rationale_key"),
    "empty rationale key": lambda d: d.__setitem__("rationale_key", ""),
    "rationale text": lambda d: d.__setitem__("rationale", "Struggles with pacing."),
    "short pack hash": lambda d: d.__setitem__("evidence_pack_sha256", "abc"),
    "uppercase pack hash": lambda d: d.__setitem__("evidence_pack_sha256", "A" * 64),
    "no pack hash": lambda d: d.pop("evidence_pack_sha256"),
    "decided by a system": lambda d: d.__setitem__("decided_by", "tm:system/teachermodel"),
    "no decider": lambda d: d.pop("decided_by"),
    "no signoff id": lambda d: d.pop("signoff_id"),
}
NEGATIVES = {
    "audit": AUDIT_NEGATIVES, "coaching_cycle": CYCLE_NEGATIVES, "cpd": CPD_NEGATIVES, "outcome": OUTCOME_NEGATIVES,
    "bench_decision": BENCH_DECISION_NEGATIVES,
}
CASES = sorted((kind, case) for kind, cases in NEGATIVES.items() for case in cases)


@pytest.mark.parametrize("kind, case", CASES)
def test_payload_rejects(kind, case):
    schema, payload, uri = PAYLOADS[kind]
    bad = mut(payload, NEGATIVES[kind][case])
    assert validate(bad, schema), case
    assert events.check_event(event(kind, uri, bad)), case  # check_event wires the same schema


def test_a_bench_decision_may_be_decided_by_the_instructor_a_mapped_person_signs_as():
    assert validate({**BENCH_DECISION, "decided_by": "tm:instructor/head-1"}, "bench-decision.schema.json") == []


def test_every_new_event_kind_has_a_payload_schema():
    assert {k: v[0] for k, v in PAYLOADS.items()}.items() <= events.PAYLOAD_SCHEMAS.items()


def test_an_outcome_payload_with_an_extra_field_is_refused_by_the_log():
    bad = {**OUTCOME, "learner_email": "learner@example.test"}
    errors = events.check_event(event("outcome", INSTRUCTOR, bad, "tm:system/teachermodel"))
    assert errors and "learner_email" in " ".join(errors)


# --- subject@2: attrs and URI rules ----------------------------------------------------------------------

SUBJECT_ATTR_NEGATIVES = {
    "cycle": {
        "no coach": lambda a: a.pop("coach"),
        "coach of another kind": lambda a: a.__setitem__("coach", "tm:person/x"),
        "number zero": lambda a: a.__setitem__("number", 0),
        "unknown intensity": lambda a: a.__setitem__("intensity", "harsh"),
        "empty focus": lambda a: a.__setitem__("focus", []),
        "focus not a domain id": lambda a: a.__setitem__("focus", ["Depth"]),
        "empty trigger": lambda a: a.__setitem__("trigger", ""),
        "unknown attr": lambda a: a.__setitem__("notes", "x"),
    },
    "sample": {
        "no observation": lambda a: a.pop("observation"),
        "no second observer": lambda a: a.pop("second_observer"),
        "observer of another kind": lambda a: a.__setitem__("observer", "tm:person/x"),
        "quarter not a quarter": lambda a: a.__setitem__("quarter", "autumn"),
        "unknown attr": lambda a: a.__setitem__("scores", {}),
    },
    "bench": {
        "unknown reason": lambda a: a.__setitem__("reason", "dislike"),
        "no reason": lambda a: a.pop("reason"),
        "instructor of another kind": lambda a: a.__setitem__("instructor", "tm:person/x"),
        "unknown attr": lambda a: a.__setitem__("rationale", "x"),
    },
    "override": {
        "module reference": lambda a: a.__setitem__("unit", "tm:module/x"),
        "unknown mode": lambda a: a.__setitem__("mode", "telepathy"),
        "date with a time": lambda a: a.__setitem__("date", "2026-11-02T09:00:00Z"),
        "no request ref": lambda a: a.pop("request_ref"),
        "empty request ref": lambda a: a.__setitem__("request_ref", ""),
        "unknown attr": lambda a: a.__setitem__("reason", "x"),
    },
}
SUBJECT_ATTR_CASES = sorted((kind, case) for kind, cases in SUBJECT_ATTR_NEGATIVES.items() for case in cases)


@pytest.mark.parametrize("kind, case", SUBJECT_ATTR_CASES)
def test_subject_attrs_rejected(kind, case):
    uri, payload = SUBJECTS[kind]
    bad = mut(payload, lambda d: SUBJECT_ATTR_NEGATIVES[kind][case](d["attrs"]))
    assert validate(bad, "subject.schema.json"), case
    assert events.check_event(event("subject", uri, bad, "tm:system/teachermodel")), case


def test_optional_cycle_trigger_is_accepted():
    uri, payload = SUBJECTS["cycle"]
    triggered = mut(payload, lambda d: d["attrs"].update(intensity="triggered", trigger="tm:trigger/0123456789abcdef"))
    assert validate(triggered, "subject.schema.json") == []


@pytest.mark.parametrize("kind, bad_uri", [
    ("cycle", "tm:cycle/k7m2q--3"),  # number differs from attrs.number
    ("cycle", "tm:cycle/other--2"),  # slug differs from attrs.instructor
    ("cycle", "tm:cycle/k7m2q"),
    ("cycle", "tm:assignment/0123456789abcdef"),
    ("sample", "tm:sample/2026Q3--evt00000001"),  # quarter differs from attrs.quarter
    ("sample", "tm:sample/2026Q4--evt00000002"),  # observation differs from attrs.observation
    ("sample", "tm:sample/evt00000001"),
    ("bench", "tm:bench/other--1"),  # slug differs from attrs.instructor
    ("bench", "tm:bench/k7m2q"),
    ("bench", "tm:bench/k7m2q--0"),
    ("bench", "tm:bench/k7m2q--x"),
    ("override", "tm:override/0123456789abcde"),  # 15 hex
    ("override", "tm:override/0123456789ABCDEF"),
    ("override", "tm:override/k7m2q--1"),
])
def test_subject_uri_must_fit_its_kind(kind, bad_uri):
    _, payload = SUBJECTS[kind]
    errors = events.check_event(event("subject", bad_uri, payload, "tm:system/teachermodel"))
    assert errors and "subject_uri" in " ".join(errors), bad_uri


def test_bench_numbers_beyond_one_are_accepted():
    _, payload = SUBJECTS["bench"]
    for uri in ("tm:bench/k7m2q--2", "tm:bench/k7m2q--12"):
        assert events.check_event(event("subject", uri, payload, "tm:system/teachermodel")) == [], uri


def test_a_slug_containing_two_hyphens_round_trips():
    # slugs may hold hyphens; the URI is still derived from attrs, not guessed by splitting
    attrs = {**SUBJECTS["cycle"][1]["attrs"], "instructor": "tm:instructor/eng-1-a"}
    payload = {**SUBJECTS["cycle"][1], "attrs": attrs}
    assert events.check_event(event("subject", "tm:cycle/eng-1-a--2", payload, "tm:system/teachermodel")) == []


# --- engine: the new kinds resolve instructor needs through attrs.instructor -------------------------------


def step(sid, subject, needs=()):
    return {"id": f"tm:step/{sid}", "name": sid, "type": "human", "role": "coordinator", "subject": subject,
            "needs": list(needs), "done_when": {"kind": "signoff", "match": {"step": f"tm:step/{sid}"}},
            "page": "approve", "basis": "test"}


def _log(kind):
    uri, payload = SUBJECTS[kind]
    reg = make_event("registration", INSTRUCTOR, "tm:person/owner", {"type": "sme-engineer", "level": "lead-observed",
                                                                      "jurisdiction": "IE"}, at="2026-10-01T09:00:00+00:00")
    opened = make_event("subject", uri, "tm:system/teachermodel", payload, at="2026-10-02T09:00:00+00:00")
    return uri, [reg, opened]


@pytest.mark.parametrize("kind", sorted(SUBJECTS))
def test_the_engine_lists_the_new_child_subjects(kind):
    uri, log = _log(kind)
    found = engine_subjects(log, ("IE",))
    assert found[uri]["kind"] == kind and found[uri]["instructor"] == INSTRUCTOR


@pytest.mark.parametrize("kind", sorted(SUBJECTS))
def test_a_child_resolves_an_instructor_need_against_attrs_instructor(kind):
    uri, log = _log(kind)
    doc = {"workflows": [{"id": "tm:workflow/t", "name": "t", "basis": "test", "steps": [
        step("parent", "instructor"), step("child", kind, needs=["tm:step/parent"])]}]}
    found = engine_subjects(log, ("IE",))
    assert not needs_met(doc, log, found, "tm:step/child", uri)
    done = make_event("signoff", INSTRUCTOR, "tm:person/owner", {"step": "tm:step/parent", "decision": "approve"},
                      at="2026-10-03T09:00:00+00:00")
    assert needs_met(doc, [*log, done], found, "tm:step/child", uri)


# --- clearance@1: the additive scope (W11) -----------------------------------------------------------------

SCOPES = [{}, {"partner": "tm:org/example-partner"}, {"regions": ["IE", "US-CA"]},
          {"partner": "tm:org/example-partner", "regions": ["IE"]}]


@pytest.mark.parametrize("scope", SCOPES)
def test_clearance_scope_accepted(scope):
    payload = {**CLEARANCE_PAYLOAD, "scope": scope}
    assert validate(payload, "clearance.schema.json") == []
    assert events.check_event(event("clearance", INSTRUCTOR, payload)) == []


def test_clearance_without_a_scope_is_still_valid():
    assert validate(CLEARANCE_PAYLOAD, "clearance.schema.json") == []  # additive: earlier @1 payloads validate


SCOPE_NEGATIVES = {
    "partner not an org": {"partner": "example-partner"},
    "partner of another kind": {"partner": "tm:instructor/x"},
    "region not a code": {"regions": ["Ireland"]},
    "lowercase region": {"regions": ["ie"]},
    "no regions": {"regions": []},
    "repeated region": {"regions": ["IE", "IE"]},
    "regions as text": {"regions": "IE"},
    "unknown scope field": {"unit": UNIT},
}


@pytest.mark.parametrize("case", sorted(SCOPE_NEGATIVES))
def test_clearance_scope_rejected(case):
    assert validate({**CLEARANCE_PAYLOAD, "scope": SCOPE_NEGATIVES[case]}, "clearance.schema.json"), case
    assert validate({**CLEARANCE_PAYLOAD, "scope": "all"}, "clearance.schema.json")


def test_clearance_description_notes_the_additive_scope():
    assert "scope" in contract("clearance.schema.json")["description"]


# --- clearance@1: the additive founding mark (decision 0017) ----------------------------------------------


def test_clearance_founding_mark_accepted_and_optional():
    payload = {**CLEARANCE_PAYLOAD, "founding": True}
    assert validate(payload, "clearance.schema.json") == []
    assert events.check_event(event("clearance", INSTRUCTOR, payload)) == []
    assert validate(CLEARANCE_PAYLOAD, "clearance.schema.json") == []  # additive: earlier @1 payloads validate
    assert "founding" in contract("clearance.schema.json")["description"]


@pytest.mark.parametrize("value", [False, "true", 1, None])
def test_clearance_founding_mark_is_true_or_absent(value):
    assert validate({**CLEARANCE_PAYLOAD, "founding": value}, "clearance.schema.json")


# --- outcome-import@1 (hub candidate) ----------------------------------------------------------------------

IMPORT_NEGATIVES = {
    "wrong schema id": lambda d: d.__setitem__("schema", "tm:contract/outcome-import@2"),
    "no schema": lambda d: d.pop("schema"),
    "no source": lambda d: d.pop("source"),
    "empty source": lambda d: d.__setitem__("source", ""),
    "no export time": lambda d: d.pop("exported_at"),
    "export time a date": lambda d: d.__setitem__("exported_at", "2026-10-25"),
    "no deliveries": lambda d: d.pop("deliveries"),
    "deliveries not a list": lambda d: d.__setitem__("deliveries", DELIVERY),
    "top-level extra field": lambda d: d.__setitem__("learners", []),
    "learner email on a delivery": lambda d: d["deliveries"][0].__setitem__("learner_email", "learner@example.test"),
    "learner name on a delivery": lambda d: d["deliveries"][0].__setitem__("learner_name", "Pat Example"),
    "learner list on a delivery": lambda d: d["deliveries"][0].__setitem__("learners", [{"id": "u1"}]),
    "source on a delivery": lambda d: d["deliveries"][0].__setitem__("source", "lms-export"),
    "delivery without a ref": lambda d: d["deliveries"][0].pop("delivery_ref"),
    "delivery without a baseline": lambda d: d["deliveries"][0].pop("baseline"),
    "delivery with a module reference": lambda d: d["deliveries"][0].__setitem__("unit", "tm:module/x"),
    "delivery with an unknown mode": lambda d: d["deliveries"][0].__setitem__("mode", "telepathy"),
    "delivery instructor an email": lambda d: d["deliveries"][0].__setitem__("instructor", "a@example.test"),
    "delivery with fractional learners": lambda d: d["deliveries"][0].__setitem__("learners_assessed", 1.5),
}


def test_outcome_import_known_positive():
    assert validate(OUTCOME_IMPORT, "outcome-import.schema.json") == []
    assert validate({**OUTCOME_IMPORT, "deliveries": []}, "outcome-import.schema.json") == []
    lean = mut(OUTCOME_IMPORT, lambda d: [d["deliveries"][0].pop(k) for k in ("feedback", "feedback_median")])
    assert validate(lean, "outcome-import.schema.json") == []


@pytest.mark.parametrize("case", sorted(IMPORT_NEGATIVES))
def test_outcome_import_rejects(case):
    assert validate(mut(OUTCOME_IMPORT, IMPORT_NEGATIVES[case]), "outcome-import.schema.json"), case


def test_every_object_of_outcome_import_refuses_extra_fields():
    def objects(node, path="#"):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                yield path, node
            for k, v in node.items():
                yield from objects(v, f"{path}/{k}")
        elif isinstance(node, list):
            for n, v in enumerate(node):
                yield from objects(v, f"{path}/{n}")

    found = list(objects(contract("outcome-import.schema.json")))
    assert len(found) >= 2  # the document and a delivery
    assert all(node.get("additionalProperties") is False for _, node in found), [p for p, n in found if n.get("additionalProperties") is not False]


def test_outcome_import_deliveries_have_the_fields_of_the_outcome_payload():
    delivery = contract("outcome-import.schema.json")["$defs"]["delivery"]
    assert contract("outcome-import.schema.json")["properties"]["deliveries"]["items"] == {"$ref": "#/$defs/delivery"}
    expect = set(contract("outcome.schema.json")["properties"]) - {"source"}
    assert set(delivery["properties"]) == expect
