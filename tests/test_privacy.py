"""Privacy data helpers: base profile resolution, retention coverage and limits, verification, validate checks
(privacy-jurisdictions design sections 3, 4 and 7). Fictional fixtures only, except the real-standards checks."""

import shutil

import pytest
import yaml
from privacy_helpers import BASE_URI, FIXTURE_PRIVACY, edit_yaml, make_privacy_root

from teachermodel import events, privacy, signoff
from teachermodel.standards import ROOT, check_standards
from teachermodel.workflow import PROGRAMME

PURPOSE = "tm:purpose/test-clearance"


def jurisdictions(root):
    return root / "standards" / "privacy" / "jurisdictions"


def approval(inputs, decision="approve", at="2026-10-24T09:00:00+00:00", sid="a" * 16):
    payload = {"step": privacy.STEP_BASE_PROFILE_VERIFIED, "decision": decision, "fields_sha256": "c" * 64,
               "input_sha256": signoff.input_sha256(inputs), "signoff_id": sid, "page_template_sha256": "b" * 64,
               "signed_at": at}
    return events.make_event("signoff", PROGRAMME, "tm:person/legal-1", payload, at=at)


def retention_entries(root):
    return yaml.safe_load((root / "standards" / "retention.yaml").read_text(encoding="utf-8"))["entries"]


# --- base profile ----------------------------------------------------------------------------------


def test_the_base_profile_is_the_single_profile_with_role_base(privacy_root):
    path, doc = privacy.base_profile(privacy_root)
    assert path.name == "xx.yaml" and doc["id"] == BASE_URI
    assert privacy.base_codes(privacy_root) == ["XX"]
    # an overlay beside it does not change the answer
    shutil.copy(FIXTURE_PRIVACY / "jurisdiction-overlay.yaml", jurisdictions(privacy_root) / "yy-aa.yaml")
    assert privacy.base_profile(privacy_root)[1]["id"] == BASE_URI


def test_no_base_profile_is_an_error(privacy_root):
    (jurisdictions(privacy_root) / "xx.yaml").unlink()
    with pytest.raises(privacy.PrivacyError, match="no base profile"):
        privacy.base_profile(privacy_root)


def test_two_base_profiles_are_an_error(privacy_root):
    shutil.copy(jurisdictions(privacy_root) / "xx.yaml", jurisdictions(privacy_root) / "zz.yaml")
    with pytest.raises(privacy.PrivacyError, match="more than one base profile"):
        privacy.base_profile(privacy_root)


def test_a_profile_that_breaks_its_contract_is_an_error(privacy_root):
    edit_yaml(jurisdictions(privacy_root) / "xx.yaml", lambda d: d.__setitem__("role", "primary"))
    with pytest.raises(privacy.PrivacyError, match="xx.yaml"):
        privacy.base_profile(privacy_root)


def test_the_real_base_profile_is_ireland():
    path, doc = privacy.base_profile(ROOT)
    assert path.name == "ie.yaml" and doc["codes"] == ["IE"]


def test_profile_inputs_carry_the_file_hash_and_content(privacy_root):
    path, doc = privacy.base_profile(privacy_root)
    inputs = privacy.profile_inputs(path, privacy_root)
    assert inputs["profile"] == doc and inputs["file"] == "standards/privacy/jurisdictions/xx.yaml"
    assert len(inputs["sha256"]) == 64
    # a comment changes the bytes but not the parsed content: the hash must still move
    path.write_bytes(path.read_bytes() + b"# a note\n")
    again = privacy.profile_inputs(path, privacy_root)
    assert again["profile"] == doc and again["sha256"] != inputs["sha256"]
    assert signoff.input_sha256(again) != signoff.input_sha256(inputs)


# --- verification ----------------------------------------------------------------------------------


def test_base_counts_as_verified_only_while_a_sign_off_covers_its_bytes(privacy_root):
    path, _ = privacy.base_profile(privacy_root)
    inputs = privacy.profile_inputs(path, privacy_root)
    assert privacy.base_verified([], privacy_root) is False
    assert privacy.base_verified([approval(inputs)], privacy_root) is True
    assert privacy.base_verified([approval(inputs, decision="changes")], privacy_root) is False
    path.write_bytes(path.read_bytes() + b"# edited after verification\n")
    assert privacy.base_verified([approval(inputs)], privacy_root) is False  # the edit reopens it


def test_the_newest_approving_sign_off_decides(privacy_root):
    path, _ = privacy.base_profile(privacy_root)
    old = privacy.profile_inputs(path, privacy_root)
    path.write_bytes(path.read_bytes() + b"# v2\n")
    new = privacy.profile_inputs(path, privacy_root)
    first = approval(old, at="2026-10-24T09:00:00+00:00", sid="a" * 16)
    second = approval(new, at="2026-10-25T09:00:00+00:00", sid="b" * 16)
    assert privacy.base_verified([first, second], privacy_root) is True
    assert privacy.base_verified([second, first], privacy_root) is False


def test_a_missing_base_profile_is_not_verified(privacy_root):
    (jurisdictions(privacy_root) / "xx.yaml").unlink()
    assert privacy.base_verified([], privacy_root) is False


# --- retention coverage and limits ----------------------------------------------------------------


def test_every_category_and_purpose_pair_of_purposes_yaml_is_required(privacy_root):
    purposes = privacy.load_purposes(privacy_root)
    assert privacy.required_pairs(purposes) == [
        ("identity-data", PURPOSE), ("performance-data", PURPOSE), ("record-of-actions", PURPOSE),
        ("delivery-data", "tm:purpose/test-reuse")]


def test_coverage_gaps_name_the_missing_pairs(privacy_root):
    purposes = privacy.load_purposes(privacy_root)
    entries = retention_entries(privacy_root)
    assert privacy.coverage_gaps(purposes, entries) == []
    assert privacy.coverage_gaps(purposes, entries[:2]) == [
        f"no retention entry for record-of-actions / {PURPOSE}",
        "no retention entry for delivery-data / tm:purpose/test-reuse"]
    assert len(privacy.coverage_gaps(purposes, [])) == 4


def test_an_overlay_entry_covers_a_pair_for_validate_but_not_for_the_base(privacy_root):
    purposes = privacy.load_purposes(privacy_root)
    entries = retention_entries(privacy_root)
    entries[0] = {**entries[0], "jurisdiction": "tm:jurisdiction/yy-aa"}
    assert privacy.coverage_gaps(purposes, entries) == []
    assert privacy.coverage_gaps(purposes, entries, base_only=True) == [
        f"no base retention entry for identity-data / {PURPOSE}"]


def entry(**kw):
    return {"category": "performance-data", "purpose": PURPOSE, "period_months": 24, "starts": "x",
            "reason": "r" * 25, "basis": "legitimate-interests", **kw}


def test_limit_breaches_check_the_maximum_and_the_minimum(privacy_root):
    profile = privacy.base_profile(privacy_root)[1]  # performance-data max 60; record-of-actions 12..120
    assert privacy.limit_breaches([entry()], profile) == []
    assert privacy.limit_breaches([entry(period_months=60)], profile) == []  # the edge is allowed
    over = privacy.limit_breaches([entry(period_months=61)], profile)
    assert len(over) == 1 and "performance-data" in over[0] and "61" in over[0] and "60" in over[0]
    short = privacy.limit_breaches([entry(category="record-of-actions", period_months=11)], profile)
    assert len(short) == 1 and "11" in short[0] and "12" in short[0]
    assert privacy.limit_breaches([entry(category="record-of-actions", period_months=12)], profile) == []
    assert privacy.limit_breaches([entry(category="record-of-actions", period_months=120)], profile) == []
    assert privacy.limit_breaches([entry(category="record-of-actions", period_months=121)], profile)
    assert privacy.limit_breaches([entry(category="identity-data", period_months=999)], profile) == []  # no limit


def test_an_event_ended_entry_breaks_a_maximum_but_not_a_minimum(privacy_root):
    profile = privacy.base_profile(privacy_root)[1]
    until = {k: v for k, v in entry().items() if k != "period_months"} | {"until_event": "deletion is requested"}
    assert privacy.limit_breaches([until], profile)  # performance-data has a maximum
    assert privacy.limit_breaches([{**until, "category": "identity-data"}], profile) == []  # no limit at all


# --- validate (check_standards) ----------------------------------------------------------------------


def test_the_fictional_privacy_root_is_valid(privacy_root):
    assert check_standards(privacy_root) == []


def test_the_real_standards_are_valid():
    assert check_standards() == []


def test_an_empty_draft_retention_passes_validate(tmp_path):
    root = make_privacy_root(tmp_path, entries="empty")
    assert check_standards(root) == []


def test_a_non_draft_retention_must_cover_every_pair(tmp_path):
    root = make_privacy_root(tmp_path)
    path = root / "standards" / "retention.yaml"

    def drop_one(d):
        d["status"] = "approved"
        d["entries"] = d["entries"][:-1]

    edit_yaml(path, drop_one)
    errors = check_standards(root)
    assert any("no base retention entry for delivery-data / tm:purpose/test-reuse" in e for e in errors), errors
    # known-positive: the same entries as a draft pass
    edit_yaml(path, lambda d: d.__setitem__("status", "draft"))
    assert check_standards(root) == []


def test_a_non_draft_retention_needs_a_base_entry_for_every_pair_not_just_an_overlay_one(tmp_path):
    root = make_privacy_root(tmp_path)
    shutil.copy(FIXTURE_PRIVACY / "jurisdiction-overlay.yaml", jurisdictions(root) / "yy-aa.yaml")
    path = root / "standards" / "retention.yaml"

    def overlay_only(d):
        d["status"] = "approved"
        d["entries"][0]["jurisdiction"] = "tm:jurisdiction/yy-aa"  # the base entry of the first pair becomes an override

    edit_yaml(path, overlay_only)
    errors = check_standards(root)
    assert any("retention: no base retention entry for identity-data / tm:purpose/test-clearance" in e
               for e in errors), errors
    # an overlay override beside a base entry is fine
    def add_base(d):
        d["entries"].append({k: v for k, v in d["entries"][0].items() if k != "jurisdiction"})

    edit_yaml(path, add_base)
    assert check_standards(root) == []


def test_a_complete_approved_retention_passes(privacy_root):
    edit_yaml(privacy_root / "standards" / "retention.yaml", lambda d: d.__setitem__("status", "approved"))
    assert check_standards(privacy_root) == []


def test_validate_refuses_a_base_profile_that_uses_disclosed_purpose(privacy_root):
    edit_yaml(jurisdictions(privacy_root) / "xx.yaml",
              lambda d: d["lawful_bases"].__setitem__(PURPOSE, ["disclosed-purpose"]))
    errors = check_standards(privacy_root)
    assert any("disclosed-purpose" in e and "base" in e for e in errors), errors


def test_validate_refuses_a_proposed_basis_the_profile_does_not_allow(privacy_root):
    def worsen(d):
        d["purposes"][0]["proposed_basis"][BASE_URI]["basis"] = "legal-obligation"

    edit_yaml(privacy_root / "standards" / "privacy" / "purposes.yaml", worsen)
    errors = check_standards(privacy_root)
    assert any("legal-obligation" in e and PURPOSE in e and BASE_URI in e for e in errors), errors


def test_validate_refuses_disclosed_purpose_proposed_for_the_base(privacy_root):
    edit_yaml(privacy_root / "standards" / "privacy" / "purposes.yaml",
              lambda d: d["purposes"][0]["proposed_basis"][BASE_URI].__setitem__("basis", "disclosed-purpose"))
    errors = check_standards(privacy_root)
    assert any("disclosed-purpose" in e and "base" in e for e in errors), errors


def test_validate_refuses_a_retention_entry_with_disclosed_purpose_outside_an_overlay(privacy_root):
    edit_yaml(privacy_root / "standards" / "retention.yaml",
              lambda d: d["entries"][0].__setitem__("basis", "disclosed-purpose"))
    errors = check_standards(privacy_root)
    assert any("disclosed-purpose" in e and "overlay" in e for e in errors), errors


def test_validate_checks_purposes_against_the_data_categories_and_workflows(privacy_root):
    path = privacy_root / "standards" / "privacy" / "purposes.yaml"
    edit_yaml(path, lambda d: d["purposes"][0]["categories"].append("observations"))
    assert any("unknown data category 'observations'" in e for e in check_standards(privacy_root))
    edit_yaml(path, lambda d: d["purposes"][0]["categories"].remove("observations"))
    edit_yaml(path, lambda d: d["purposes"][0].__setitem__("workflows", ["tm:workflow/ghost"]))
    assert any("tm:workflow/ghost" in e for e in check_standards(privacy_root))
    # planned workflows need not exist
    edit_yaml(path, lambda d: (d["purposes"][0].__setitem__("workflows", ["tm:workflow/setup"]),
                               d["purposes"][0].__setitem__("planned_workflows", ["tm:workflow/ghost"])))
    assert check_standards(privacy_root) == []


def test_validate_refuses_a_profile_that_names_an_unknown_purpose(privacy_root):
    edit_yaml(jurisdictions(privacy_root) / "xx.yaml",
              lambda d: d["lawful_bases"].__setitem__("tm:purpose/ghost", ["contract"]))
    assert any("tm:purpose/ghost" in e for e in check_standards(privacy_root))


def test_validate_refuses_two_profiles_for_one_code_and_a_misnamed_file(privacy_root):
    other = jurisdictions(privacy_root) / "yy-aa.yaml"
    shutil.copy(FIXTURE_PRIVACY / "jurisdiction-overlay.yaml", other)
    assert check_standards(privacy_root) == []
    edit_yaml(other, lambda d: d.__setitem__("codes", ["XX"]))
    assert any("XX" in e and "more than one profile" in e for e in check_standards(privacy_root))
    edit_yaml(other, lambda d: d.__setitem__("codes", ["YY-AA"]))
    other.rename(jurisdictions(privacy_root) / "wrong-name.yaml")
    assert any("wrong-name.yaml" in e and "tm:jurisdiction/yy-aa" in e for e in check_standards(privacy_root))


def test_validate_needs_a_base_profile(privacy_root):
    (jurisdictions(privacy_root) / "xx.yaml").unlink()
    assert any("no base profile" in e for e in check_standards(privacy_root))


def test_validate_checks_retention_entries_against_purposes_and_jurisdictions(privacy_root):
    path = privacy_root / "standards" / "retention.yaml"
    edit_yaml(path, lambda d: d["entries"][0].__setitem__("purpose", "tm:purpose/ghost"))
    assert any("tm:purpose/ghost" in e for e in check_standards(privacy_root))
    edit_yaml(path, lambda d: d["entries"][0].__setitem__("purpose", PURPOSE))
    edit_yaml(path, lambda d: d["entries"][0].__setitem__("jurisdiction", "tm:jurisdiction/nowhere"))
    assert any("tm:jurisdiction/nowhere" in e for e in check_standards(privacy_root))
