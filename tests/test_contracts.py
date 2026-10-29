"""v2 contracts: unit references and the five new event kinds (decisions 0007, 0008)."""

import json
from pathlib import Path

import pytest

from teachermodel import events
from teachermodel.standards import validate

ROOT = Path(__file__).resolve().parent.parent
UNIT = "sl:unit/example-agent-loop@1"

OBS = {
    "instructor": "tm:instructor/eng-1",
    "unit": UNIT,
    "observer": "tm:instructor/obs-a",
    "length": "full",
    "lead": True,
    "rubric_version": "0.2.0",
    "scores": {"technical-depth": 3},
}
REQ = {"instructor": "tm:instructor/eng-1", "unit": UNIT, "mode": "remote", "date": "2026-10-24"}
SUBJECT_CANDIDATE = {
    "subject_kind": "candidate",
    "attrs": {"instructor": "tm:instructor/eng-1", "unit": UNIT, "mode": "remote"},
    "opened_by": "tm:step/open-candidates",
}


def test_v1_unit_ref_rejected():
    for bad in ("tm:module/x", "sl:module/x", "tm:unit/x", "sl:unit/x", "sl:unit/x@"):
        assert validate({**OBS, "unit": bad}, "observation.schema.json"), bad
    # the v1 field name is gone, not just its pattern
    legacy = {k: v for k, v in OBS.items() if k != "unit"} | {"module": "tm:module/x"}
    assert validate(legacy, "observation.schema.json")
    # known-positive
    assert validate(OBS, "observation.schema.json") == []


def test_staffing_request_rejects_module_refs():
    schema = json.loads((ROOT / "contracts" / "staffing-check.schema.json").read_text(encoding="utf-8"))
    from jsonschema import Draft202012Validator

    v = Draft202012Validator({**schema["$defs"]["request"], "$defs": schema["$defs"]})
    assert not list(v.iter_errors(REQ))
    assert list(v.iter_errors({**REQ, "unit": "tm:module/x"}))


@pytest.mark.parametrize("name", ["staffing-check", "observation", "roster"])
def test_ids_are_v2_and_v1_kept(name):
    new = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
    old = json.loads((ROOT / "contracts" / "v1" / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert new["$id"] == f"tm:contract/{name}@2"
    assert old["$id"] == f"tm:contract/{name}@1"


def test_event_is_v4_and_v1_v2_v3_kept():
    def load(*parts):
        return json.loads(ROOT.joinpath("contracts", *parts).read_text(encoding="utf-8"))

    new, v3 = load("event.schema.json"), load("v3", "event.schema.json")
    v2, v1 = load("v2", "event.schema.json"), load("v1", "event.schema.json")
    assert (new["$id"], v3["$id"], v2["$id"], v1["$id"]) == (
        "tm:contract/event@4", "tm:contract/event@3", "tm:contract/event@2", "tm:contract/event@1")
    kinds, v3_kinds, v2_kinds = (d["properties"]["kind"]["enum"] for d in (new, v3, v2))
    assert "subject" in v3_kinds and "subject" not in v2_kinds
    assert sorted(set(v3_kinds) - {"subject"}) == sorted(v2_kinds)  # event@3 added exactly one kind (decision 0011)
    assert "outcome" in kinds and "outcome" not in v3_kinds
    assert sorted(set(kinds) - {"outcome"}) == sorted(v3_kinds)  # event@4 adds exactly one kind (decision 0014)


def test_event_v3_subject_kind_accepted():
    ev = events.make_event("subject", "tm:candidate/eng-1--example-agent-loop-1--remote", "tm:system/teachermodel", SUBJECT_CANDIDATE,
                           id="evt00000020", at="2026-10-24T10:00:00+00:00")
    assert events.check_event(ev) == []


@pytest.mark.parametrize("kind", ["signoff", "notice", "check", "registration", "step"])
def test_event_v2_new_kinds_accepted(kind):
    ev = events.make_event(kind, "tm:instructor/eng-1", "tm:person/owner", {"ref": "x"},
                           id="evt00000002", at="2026-10-24T10:00:00+00:00")
    assert events.check_event(ev) == []


def test_event_unknown_kind_still_rejected():
    ev = events.make_event("bogus", "tm:instructor/eng-1", "tm:person/owner", {},
                           id="evt00000003", at="2026-10-24T10:00:00+00:00")
    assert events.check_event(ev)


def test_observation_event_payload_validated_with_unit():
    ev = events.make_event("observation", "tm:instructor/eng-1", "tm:instructor/obs-a", OBS,
                           id="evt00000004", at="2026-10-24T10:00:00+00:00")
    assert events.check_event(ev) == []
    bad = events.make_event("observation", "tm:instructor/eng-1", "tm:instructor/obs-a",
                            {**OBS, "unit": "tm:module/x"}, id="evt00000005", at="2026-10-24T10:00:00+00:00")
    assert events.check_event(bad)


# v2 schemas are history too: pinned to the bytes of event@2 as it stood before event@3 (decision 0011).
V2_SHA256 = {
    "event.schema.json": "8644d3e68c682ebc217005ba6ea252589499c98d71bbe845b6ea15212127f879",
}


def test_v2_schemas_unchanged():
    import hashlib

    from teachermodel.standards import ROOT

    for name, digest in V2_SHA256.items():
        assert hashlib.sha256((ROOT / "contracts" / "v2" / name).read_bytes()).hexdigest() == digest, name


# v1 schemas are history: pinned to the bytes of the @1 originals.
V1_SHA256 = {
    "event.schema.json": "1288759540cf393f01f6a71198116d3e8cedc1d6a2286da341c2b0c718989b52",
    "observation.schema.json": "90026eb8b265a7b7e19cd454ce993879f1c66671a651edd918967c88e88dccf0",
    "roster.schema.json": "eca2b5c3904acd4c31f5d378c65db04927ce28275ca28b35add284f3debf2f74",
    "staffing-check.schema.json": "d758f50bd7cb24697b50945e09a6e6db1df4505c5a12e79ec570527166796726",
    "retention.schema.json": "4fdfa62b47213755888733d0cb38e720bc8eeeb318b67ebe522a0382e6315d40",
}


def test_v1_schemas_unchanged():
    import hashlib

    from teachermodel.standards import ROOT

    for name, digest in V1_SHA256.items():
        assert hashlib.sha256((ROOT / "contracts" / "v1" / name).read_bytes()).hexdigest() == digest, name


def test_system_actor_accepted():
    from teachermodel import events

    ev = events.make_event("check", "tm:programme/teachermodel", "tm:system/teachermodel", {"step": "tm:step/x"})
    assert events.check_event(ev) == []


def test_roster_module_field_rejected():
    from teachermodel import roster
    from teachermodel.standards import ROOT

    doc = roster.load(ROOT / "standards" / "templates" / "roster.example.yaml")
    d = doc["instructors"][0]["delivers"][0]
    d["module"] = d.pop("unit").replace("sl:unit/", "tm:module/").split("@")[0]
    assert roster.check_roster(doc)


# --- privacy contracts: jurisdiction@1, purposes@1, retention@2 (decisions 0009, 0010) ----------------

import copy

import yaml

FIXTURES = ROOT / "tests" / "fixtures" / "privacy"


def fixture(name):
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def test_retention_is_v2_and_v1_kept():
    new = json.loads((ROOT / "contracts" / "retention.schema.json").read_text(encoding="utf-8"))
    old = json.loads((ROOT / "contracts" / "v1" / "retention.schema.json").read_text(encoding="utf-8"))
    assert new["$id"] == "tm:contract/retention@2" and old["$id"] == "tm:contract/retention@1"


def test_new_contract_ids():
    for name in ("jurisdiction", "purposes"):
        doc = json.loads((ROOT / "contracts" / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert doc["$id"] == f"tm:contract/{name}@1"


@pytest.mark.parametrize("name", ["jurisdiction-base.yaml", "jurisdiction-overlay.yaml"])
def test_jurisdiction_accepts_fixtures(name):
    assert validate(fixture(name), "jurisdiction.schema.json") == []


def _mut(doc, fn):
    d = copy.deepcopy(doc)
    fn(d)
    return d


JURISDICTION_NEGATIVES = {
    "bad id": lambda d: d.__setitem__("id", "tm:jurisdiction/Xx"),
    "id of another kind": lambda d: d.__setitem__("id", "tm:purpose/xx"),
    "code not ISO": lambda d: d.__setitem__("codes", ["California"]),
    "no codes": lambda d: d.__setitem__("codes", []),
    "unknown role": lambda d: d.__setitem__("role", "primary"),
    "unknown basis": lambda d: d["lawful_bases"].__setitem__("tm:purpose/test-clearance", ["vibes"]),
    "purpose key not a purpose uri": lambda d: d["lawful_bases"].__setitem__("clearance", ["contract"]),
    "consent flag not boolean": lambda d: d.__setitem__("consent_valid_in_employment", "no"),
    "notice element without citation": lambda d: d["notice_elements"][0].pop("citation"),
    "retention limit without max or min": lambda d: d["retention_limits"][0].pop("max_months"),
    "retention limit without citation": lambda d: d["retention_limits"][0].pop("citation"),
    "zero-month limit": lambda d: d["retention_limits"][0].__setitem__("max_months", 0),
    "right deadline not a count of days": lambda d: d["rights"][0].__setitem__("deadline_days", "a month"),
    "no sources": lambda d: d.__setitem__("sources", []),
    "source without access date": lambda d: d["sources"][0].pop("accessed"),
    "source url not a url": lambda d: d["sources"][0].__setitem__("url", "see the website"),
    "unknown status": lambda d: d.__setitem__("status", "approved"),
    "unknown drafter": lambda d: d.__setitem__("drafted_by", "a model"),
    "unknown field": lambda d: d.__setitem__("confidence", "high"),
    "breach window without citation": lambda d: d["breach_notification"].pop("citation"),
}


@pytest.mark.parametrize("case", sorted(JURISDICTION_NEGATIVES))
def test_jurisdiction_rejects(case):
    bad = _mut(fixture("jurisdiction-base.yaml"), JURISDICTION_NEGATIVES[case])
    assert validate(bad, "jurisdiction.schema.json"), case


def test_purposes_accepts_fixture():
    assert validate(fixture("purposes.yaml"), "purposes.schema.json") == []


PURPOSES_NEGATIVES = {
    "purpose id of another kind": lambda d: d["purposes"][0].__setitem__("id", "tm:step/x"),
    "no categories": lambda d: d["purposes"][0].__setitem__("categories", []),
    "category not a slug": lambda d: d["purposes"][0].__setitem__("categories", ["Performance data"]),
    "workflow not a workflow uri": lambda d: d["purposes"][0].__setitem__("workflows", ["onboarding"]),
    "no description": lambda d: d["purposes"][0].pop("description"),
    "proposed basis unknown": lambda d: d["purposes"][0]["proposed_basis"]["tm:jurisdiction/xx"].__setitem__("basis", "vibes"),
    "proposed basis without reason": lambda d: d["purposes"][0]["proposed_basis"]["tm:jurisdiction/xx"].pop("reason"),
    "proposed basis keyed by a code": lambda d: d["purposes"][0]["proposed_basis"].__setitem__("IE", {"basis": "contract", "reason": "x" * 30}),
    "unknown status": lambda d: d.__setitem__("status", "verified"),
    "unknown field": lambda d: d["purposes"][0].__setitem__("owner", "me"),
}


@pytest.mark.parametrize("case", sorted(PURPOSES_NEGATIVES))
def test_purposes_rejects(case):
    assert validate(_mut(fixture("purposes.yaml"), PURPOSES_NEGATIVES[case]), "purposes.schema.json"), case


def test_retention_v2_accepts_fixture_and_empty_entries():
    doc = fixture("retention.yaml")
    assert validate(doc, "retention.schema.json") == []
    assert validate({**doc, "entries": []}, "retention.schema.json") == []


RETENTION_NEGATIVES = {
    "v1 version number": lambda d: d.__setitem__("schema_version", 1),
    "v1 periods block": lambda d: d.__setitem__("periods", {"observations": 24}),
    "no entries key": lambda d: d.pop("entries"),
    "neither period nor event": lambda d: d["entries"][0].pop("period_months"),
    "both period and event": lambda d: d["entries"][0].__setitem__("until_event", "deletion is requested"),
    "zero months": lambda d: d["entries"][0].__setitem__("period_months", 0),
    "null period": lambda d: d["entries"][0].__setitem__("period_months", None),
    "reason too short": lambda d: d["entries"][0].__setitem__("reason", "because"),
    "no starts": lambda d: d["entries"][0].pop("starts"),
    "no purpose": lambda d: d["entries"][0].pop("purpose"),
    "purpose not a purpose uri": lambda d: d["entries"][0].__setitem__("purpose", "clearance"),
    "jurisdiction not a jurisdiction uri": lambda d: d["entries"][1].__setitem__("jurisdiction", "US-CA"),
    "category not a slug": lambda d: d["entries"][0].__setitem__("category", "Performance data"),
    "unknown basis": lambda d: d["entries"][0].__setitem__("basis", "vibes"),
    "unknown status": lambda d: d.__setitem__("status", "verified"),
    "unknown field": lambda d: d["entries"][0].__setitem__("owner", "me"),
}


@pytest.mark.parametrize("case", sorted(RETENTION_NEGATIVES))
def test_retention_v2_rejects(case):
    assert validate(_mut(fixture("retention.yaml"), RETENTION_NEGATIVES[case]), "retention.schema.json"), case


def test_basis_enum_is_the_same_in_every_contract():
    def enum_of(name, *path):
        node = json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))
        for p in path:
            node = node[p]
        return node["enum"]

    bases = enum_of("jurisdiction.schema.json", "$defs", "basis")
    assert enum_of("purposes.schema.json", "$defs", "basis") == bases
    assert enum_of("retention.schema.json", "$defs", "basis") == bases
    assert "consent" in bases and "legitimate-interests" in bases


# --- contract additions for the drafted profiles (J3 part 1) -------------------------------------------


def test_jurisdiction_accepts_optional_scope_and_notice_timing():
    doc = _mut(fixture("jurisdiction-overlay.yaml"), lambda d: d.update(
        scope="Who and what this profile covers.",
        notice_timing={"rule": "At or before collection.", "citation": "Fictional Privacy Rights Act s.4"}))
    assert validate(doc, "jurisdiction.schema.json") == []


@pytest.mark.parametrize("case", ["empty scope", "timing without citation", "timing without rule", "timing as text"])
def test_jurisdiction_rejects_malformed_scope_and_timing(case):
    breaks = {
        "empty scope": lambda d: d.__setitem__("scope", ""),
        "timing without citation": lambda d: d.__setitem__("notice_timing", {"rule": "At collection."}),
        "timing without rule": lambda d: d.__setitem__("notice_timing", {"citation": "s.4"}),
        "timing as text": lambda d: d.__setitem__("notice_timing", "At collection."),
    }
    assert validate(_mut(fixture("jurisdiction-overlay.yaml"), breaks[case]), "jurisdiction.schema.json"), case


def test_disclosed_purpose_is_a_basis_in_all_three_contracts():
    doc = _mut(fixture("jurisdiction-overlay.yaml"),
               lambda d: d["lawful_bases"].__setitem__("tm:purpose/test-clearance", ["disclosed-purpose"]))
    assert validate(doc, "jurisdiction.schema.json") == []
    purposes = _mut(fixture("purposes.yaml"), lambda d: d["purposes"][0]["proposed_basis"].__setitem__(
        "tm:jurisdiction/yy-aa", {"basis": "disclosed-purpose", "reason": "CCPA needs no basis.", "notice_text": "We use it for this purpose only."}))
    assert validate(purposes, "purposes.schema.json") == []
    retention = _mut(fixture("retention.yaml"), lambda d: d["entries"][1].__setitem__("basis", "disclosed-purpose"))
    assert validate(retention, "retention.schema.json") == []


def test_purposes_accepts_planned_workflows_drafted_by_and_review_notes():
    doc = _mut(fixture("purposes.yaml"), lambda d: (
        d["purposes"][0].__setitem__("planned_workflows", ["tm:workflow/clearance"]),
        d.update(drafted_by="ai-assisted", review_notes=["Legal to confirm one line can cover both purposes."])))
    assert validate(doc, "purposes.schema.json") == []


PURPOSES_ADDITION_NEGATIVES = {
    "planned workflow not a workflow uri": lambda d: d["purposes"][0].__setitem__("planned_workflows", ["clearance"]),
    "planned workflows repeated": lambda d: d["purposes"][0].__setitem__(
        "planned_workflows", ["tm:workflow/a", "tm:workflow/a"]),
    "unknown drafter": lambda d: d.__setitem__("drafted_by", "a model"),
    "empty review note": lambda d: d.__setitem__("review_notes", [""]),
    "review notes as text": lambda d: d.__setitem__("review_notes", "see the draft"),
}


@pytest.mark.parametrize("case", sorted(PURPOSES_ADDITION_NEGATIVES))
def test_purposes_rejects_malformed_additions(case):
    assert validate(_mut(fixture("purposes.yaml"), PURPOSES_ADDITION_NEGATIVES[case]), "purposes.schema.json"), case


# --- the AI-drafted files in standards/privacy validate (the only test that reads them) ---------------


def _draft_profiles():
    return sorted((ROOT / "standards" / "privacy" / "jurisdictions").glob("*.yaml"))


def test_the_real_drafts_validate_against_the_contracts():
    profiles = _draft_profiles()
    assert {p.stem for p in profiles} == {"ie", "us-ca"}
    for path in profiles:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert validate(doc, "jurisdiction.schema.json") == [], path.name
        assert doc["id"] == f"tm:jurisdiction/{path.stem}"
        # drafts stay drafts: verification is a bound sign-off, never a field in the file
        assert doc["status"] == "draft" and doc["drafted_by"] == "ai-assisted"
        assert "verified_by" not in doc and "verified_on" not in doc
    purposes = yaml.safe_load((ROOT / "standards" / "privacy" / "purposes.yaml").read_text(encoding="utf-8"))
    assert validate(purposes, "purposes.schema.json") == []
    assert purposes["status"] == "draft" and purposes["drafted_by"] == "ai-assisted"
    assert len(purposes["purposes"]) == 9


def test_the_real_drafts_agree_with_each_other():
    base = yaml.safe_load((ROOT / "standards" / "privacy" / "jurisdictions" / "ie.yaml").read_text(encoding="utf-8"))
    overlay = yaml.safe_load((ROOT / "standards" / "privacy" / "jurisdictions" / "us-ca.yaml").read_text(encoding="utf-8"))
    purposes = yaml.safe_load((ROOT / "standards" / "privacy" / "purposes.yaml").read_text(encoding="utf-8"))
    ids = {p["id"] for p in purposes["purposes"]}
    assert base["role"] == "base" and overlay["role"] == "overlay"
    assert set(base["lawful_bases"]) == ids and set(overlay["lawful_bases"]) == ids
    for p in purposes["purposes"]:
        for uri, prop in p["proposed_basis"].items():
            profile = {base["id"]: base, overlay["id"]: overlay}[uri]
            assert prop["basis"] in profile["lawful_bases"][p["id"]], (p["id"], uri)
    # disclosed-purpose is a CCPA word: the base profile never uses it
    assert not any("disclosed-purpose" in bases for bases in base["lawful_bases"].values())


def test_bench_decision_is_a_separate_draft_purpose_for_legal_to_review():
    # Decision 0005 tells instructors their records serve coaching and clearance; a bench decision is a different use,
    # so it has its own purpose, served by the W10 workflow file since increment 3 (spec, legal notes).
    purposes = yaml.safe_load((ROOT / "standards" / "privacy" / "purposes.yaml").read_text(encoding="utf-8"))
    assert purposes["status"] == "draft" and purposes["drafted_by"] == "ai-assisted"
    p = {x["id"]: x for x in purposes["purposes"]}["tm:purpose/bench-decision"]
    assert p["workflows"] == ["tm:workflow/bench"] and "planned_workflows" not in p
    assert p["categories"] == ["performance-data", "employment-and-training-data", "record-of-actions"]
    assert set(p["proposed_basis"]) == {"tm:jurisdiction/ie", "tm:jurisdiction/us-ca"}
    for prop in p["proposed_basis"].values():
        assert "(legal review)" in prop["notice_text"]
    note = " ".join(n for n in purposes["review_notes"] if n.startswith("bench-decision"))
    assert "separate purpose" in note and "W10" in note and "real data" in note
    # the old "not covered" note is replaced by the one that says what was drafted
    assert not any(n.startswith("bench-decision-not-covered") for n in purposes["review_notes"])
