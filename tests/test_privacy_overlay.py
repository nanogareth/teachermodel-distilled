"""Overlay profile helpers: finding the profile of a code, merged retention limits, the DPIA delta (privacy-
jurisdictions design sections 2 and 4). Fictional fixtures only."""

import pytest
from privacy_helpers import OVERLAY_URI, add_overlay, edit_yaml

from teachermodel import pages, privacy

PURPOSE = "tm:purpose/test-clearance"


def entry(**kw):
    return {"category": "performance-data", "purpose": PURPOSE, "period_months": 24, "starts": "x",
            "reason": "r" * 25, "basis": "legitimate-interests", **kw}


@pytest.fixture
def overlay_root(privacy_root):
    add_overlay(privacy_root, limits=[
        {"category": "performance-data", "max_months": 12, "citation": "Fictional Privacy Rights Act s.10"},
        {"category": "record-of-actions", "min_months": 36, "citation": "Fictional Privacy Rights Act s.11"}])
    return privacy_root


def test_overlay_profile_is_found_by_code(overlay_root):
    path, doc = privacy.overlay_profile("US-CA", overlay_root)
    assert path.name == "us-ca.yaml" and doc["id"] == OVERLAY_URI and doc["role"] == "overlay"
    assert privacy.overlay_profile("DE", overlay_root) is None  # no profile for that code
    assert privacy.overlay_profile("IE", overlay_root) is None  # the base covers IE; it is not an overlay


def test_a_base_profile_is_never_returned_as_an_overlay(overlay_root):
    edit_yaml(overlay_root / "standards" / "privacy" / "jurisdictions" / "xx.yaml",
              lambda d: d.__setitem__("codes", ["IE", "DE"]))
    assert privacy.overlay_profile("DE", overlay_root) is None


def test_overlay_profile_matches_the_code_exactly_ignoring_case(overlay_root):
    assert privacy.overlay_profile("us-ca", overlay_root)[1]["id"] == OVERLAY_URI
    assert privacy.overlay_profile("US", overlay_root) is None


def test_overlay_profile_inputs_carry_both_hashes_so_a_base_edit_reopens_the_overlay(overlay_root):
    base_path, _ = privacy.base_profile(overlay_root)
    path, _ = privacy.overlay_profile("US-CA", overlay_root)
    before = privacy.overlay_profile_inputs(path, base_path, overlay_root)
    assert before["sha256"] == privacy.profile_inputs(path, overlay_root)["sha256"]
    assert before["base_profile_sha256"] == privacy.profile_inputs(base_path, overlay_root)["sha256"]
    assert before["profile"]["id"] == OVERLAY_URI and before["file"].endswith("jurisdictions/us-ca.yaml")
    base_path.write_bytes(base_path.read_bytes() + b"# edited\n")
    after = privacy.overlay_profile_inputs(path, base_path, overlay_root)
    assert after["base_profile_sha256"] != before["base_profile_sha256"] and after["sha256"] == before["sha256"]


def test_effective_entries_let_an_overlay_entry_override_the_base_one():
    base = entry()
    other = entry(category="identity-data")
    over = entry(period_months=12, jurisdiction=OVERLAY_URI)
    elsewhere = entry(period_months=6, jurisdiction="tm:jurisdiction/de")
    assert privacy.effective_entries([base, other, over, elsewhere], OVERLAY_URI) == [over, other]
    assert privacy.effective_entries([base, other, over, elsewhere], "tm:jurisdiction/none") == [base, other]
    only_over = entry(category="record-of-actions", jurisdiction=OVERLAY_URI)
    assert privacy.effective_entries([base, only_over], OVERLAY_URI) == [base, only_over]  # an extra pair stays


def test_overlay_limit_is_a_shorter_maximum_than_the_bases(overlay_root):
    _, base = privacy.base_profile(overlay_root)  # performance-data max 60
    _, overlay = privacy.overlay_profile("US-CA", overlay_root)  # performance-data max 12
    assert privacy.limit_breaches([entry()], base) == []  # fine for the base alone
    found = privacy.overlay_retention_breaches([entry()], base, overlay)
    assert len(found) == 1 and "performance-data" in found[0] and "24" in found[0] and "12" in found[0]
    assert OVERLAY_URI in found[0] and "Fictional Privacy Rights Act s.10" in found[0]
    assert privacy.overlay_retention_breaches([entry(period_months=12)], base, overlay) == []  # the edge is allowed
    assert privacy.overlay_retention_breaches([entry(period_months=13)], base, overlay)


def test_the_stricter_of_the_two_limits_holds(overlay_root):
    _, base = privacy.base_profile(overlay_root)  # record-of-actions 12..120
    _, overlay = privacy.overlay_profile("US-CA", overlay_root)  # record-of-actions min 36
    rec = entry(category="record-of-actions")
    assert privacy.overlay_retention_breaches([{**rec, "period_months": 36}], base, overlay) == []
    short = privacy.overlay_retention_breaches([{**rec, "period_months": 24}], base, overlay)  # base allows 24, overlay not
    assert len(short) == 1 and "36" in short[0]
    shorter = privacy.overlay_retention_breaches([{**rec, "period_months": 6}], base, overlay)
    assert len(shorter) == 2  # below the base minimum and the overlay minimum
    long_ = privacy.overlay_retention_breaches([{**rec, "period_months": 121}], base, overlay)
    assert len(long_) == 1 and "120" in long_[0]  # the base maximum still holds under the overlay


def test_an_overlay_entry_cures_a_breach_by_the_base_entry(overlay_root):
    _, base = privacy.base_profile(overlay_root)
    _, overlay = privacy.overlay_profile("US-CA", overlay_root)
    entries = [entry(period_months=24), entry(period_months=12, jurisdiction=OVERLAY_URI)]
    assert privacy.overlay_retention_breaches(entries, base, overlay) == []
    assert privacy.overlay_retention_breaches(entries[:1], base, overlay)


def test_an_event_ended_entry_breaks_an_overlay_maximum(overlay_root):
    _, base = privacy.base_profile(overlay_root)
    _, overlay = privacy.overlay_profile("US-CA", overlay_root)
    until = {k: v for k, v in entry().items() if k != "period_months"} | {"until_event": "deletion is requested"}
    assert len(privacy.overlay_retention_breaches([until], base, overlay)) == 2  # both profiles cap performance-data


def test_the_base_screening_covers_nine_criteria_and_an_overlay_trigger_outside_them_is_the_delta(privacy_root):
    assert "evaluation-scoring" in pages.DPIA_CRITERION_IDS and len(pages.DPIA_CRITERION_IDS) == 9
    add_overlay(privacy_root, triggers=[
        {"criterion": "evaluation-scoring", "citation": "Fictional Privacy Rights Act s.20"},
        {"criterion": "ca-sell-or-share", "citation": "Fictional Privacy Rights Act s.21"},
        {"criterion": "ca-sell-or-share", "citation": "Fictional Privacy Rights Act s.22"}])
    _, overlay = privacy.overlay_profile("US-CA", privacy_root)
    assert privacy.dpia_delta(overlay) == [{"criterion": "ca-sell-or-share", "citations": [
        "Fictional Privacy Rights Act s.21", "Fictional Privacy Rights Act s.22"]}]


def test_no_delta_when_every_trigger_is_a_base_criterion_or_there_are_none(privacy_root):
    add_overlay(privacy_root, triggers=[{"criterion": "systematic-monitoring", "citation": "Fictional Act s.1"}])
    assert privacy.dpia_delta(privacy.overlay_profile("US-CA", privacy_root)[1]) == []
    add_overlay(privacy_root)
    assert privacy.dpia_delta(privacy.overlay_profile("US-CA", privacy_root)[1]) == []


def test_dpia_delta_inputs_hash_the_delta_and_both_profiles(privacy_root):
    add_overlay(privacy_root, triggers=[{"criterion": "ca-sell-or-share", "citation": "Fictional Act s.21"}])
    base_path, _ = privacy.base_profile(privacy_root)
    path, _ = privacy.overlay_profile("US-CA", privacy_root)
    inputs = privacy.dpia_delta_inputs(path, base_path, privacy_root)
    assert inputs["delta"] == [{"criterion": "ca-sell-or-share", "citations": ["Fictional Act s.21"]}]
    assert set(inputs) == {"delta", "overlay_profile_sha256", "base_profile_sha256"}
    assert inputs["base_profile_sha256"] == privacy.profile_inputs(base_path, privacy_root)["sha256"]
