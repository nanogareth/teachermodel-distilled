"""Integration-review fixes for the privacy data (findings 5, 7, 9, 10, 12, 13, 14): what legal verifies covers
purposes.yaml, the DPIA binds to the base triggers and the purposes, validate checks templates and retention against
every profile, one malformed overlay blocks only its own jurisdiction, and a skip counts only from the system.
Fictional fixtures only."""

from datetime import datetime, timedelta, timezone

import pytest
from privacy_helpers import (
    OVERLAY_URI,
    PROGRAMME,
    STEP_DPIA,
    STEP_VERIFIED,
    add_overlay,
    due_ids,
    edit_yaml,
    sign_step,
)

from teachermodel import app, events, overlay, privacy, setup, signoff, workflow
from teachermodel.bridge import SYSTEM_ACTOR
from teachermodel.flows.common import PageProblem
from teachermodel.standards import check_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
TODAY = T0.date()


def jur(root):
    return root / "standards" / "privacy" / "jurisdictions"


def tick(private, root, hours=0):
    return app.do_tick(private, now=T0 + timedelta(hours=hours), root=root)


def reader(private, root):
    return app._current_input_reader(app.load_state(private, root))


# --- 5: purposes.yaml is part of what legal verifies ------------------------------------------------------


def test_profile_inputs_carry_the_hash_of_purposes_yaml(privacy_root):
    path, _ = privacy.base_profile(privacy_root)
    before = privacy.profile_inputs(path, privacy_root)
    assert len(before["purposes_sha256"]) == 64
    edit_yaml(privacy_root / privacy.PURPOSES_FILE, lambda d: d["purposes"][0].__setitem__("name", "Edited"))
    after = privacy.profile_inputs(path, privacy_root)
    assert after["purposes_sha256"] != before["purposes_sha256"] and after["sha256"] == before["sha256"]


def test_overlay_inputs_carry_the_purposes_hash_too(privacy_root):
    overlay_path = add_overlay(privacy_root)
    base_path, _ = privacy.base_profile(privacy_root)
    inputs = privacy.overlay_profile_inputs(overlay_path, base_path, privacy_root)
    assert inputs["purposes_sha256"] == privacy.profile_inputs(overlay_path, privacy_root)["purposes_sha256"]


def test_editing_purposes_yaml_reopens_the_base_verification(fictional_store, privacy_root):
    tick(fictional_store, privacy_root)
    sign_step(fictional_store, privacy_root, STEP_VERIFIED)
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(fictional_store, privacy_root, TODAY)
    edit_yaml(privacy_root / privacy.PURPOSES_FILE, lambda d: d["purposes"][0].__setitem__("name", "Edited"))
    assert (STEP_VERIFIED, PROGRAMME) in due_ids(fictional_store, privacy_root, TODAY)


def test_editing_purposes_yaml_reopens_the_overlay_verification(fictional_store, privacy_root):
    add_overlay(privacy_root)
    tick(fictional_store, privacy_root)
    sign_step(fictional_store, privacy_root, STEP_VERIFIED)
    base_path, _ = privacy.base_profile(privacy_root)
    path, _ = privacy.overlay_profile("US-CA", privacy_root)
    log = [events.make_event("signoff", OVERLAY_URI, "tm:person/seed", {
        "step": privacy.STEP_PROFILE_VERIFIED, "decision": "approve", "fields_sha256": "c" * 64,
        "input_sha256": signoff.input_sha256(privacy.overlay_profile_inputs(path, base_path, privacy_root)),
        "signoff_id": "s" * 16, "page_template_sha256": "b" * 64, "signed_at": "2026-10-26T09:00:00+00:00"},
        at="2026-10-26T09:00:00+00:00")]
    assert privacy.overlay_verified(log, OVERLAY_URI, path, base_path, privacy_root)
    edit_yaml(privacy_root / privacy.PURPOSES_FILE, lambda d: d["purposes"][0].__setitem__("name", "Edited"))
    assert not privacy.overlay_verified(log, OVERLAY_URI, path, base_path, privacy_root)


# --- 7: the DPIA binds to the base triggers and the purposes ---------------------------------------------


def test_the_dpia_input_changes_with_the_base_triggers_and_the_purposes(fictional_store, privacy_root):
    tick(fictional_store, privacy_root)
    base = reader(fictional_store, privacy_root)(STEP_DPIA, PROGRAMME)
    assert isinstance(base, str)

    def trigger(d):
        d["dpia_triggers"].append({"criterion": "large-scale", "citation": "Fictional Data Protection Act s.50"})

    edit_yaml(jur(privacy_root) / "xx.yaml", trigger)
    with_trigger = reader(fictional_store, privacy_root)(STEP_DPIA, PROGRAMME)
    assert with_trigger != base
    edit_yaml(privacy_root / privacy.PURPOSES_FILE, lambda d: d["purposes"][0].__setitem__("name", "Edited"))
    assert reader(fictional_store, privacy_root)(STEP_DPIA, PROGRAMME) not in (base, with_trigger)


def test_the_dpia_input_does_not_move_with_the_retention_table_or_the_record_of_processing(fictional_store, privacy_root):
    """The ROPA text includes the retention table, which is edited while the DPIA is done; it rides in the unhashed intro."""
    tick(fictional_store, privacy_root)
    before = reader(fictional_store, privacy_root)(STEP_DPIA, PROGRAMME)
    edit_yaml(privacy_root / "standards" / "retention.yaml", lambda d: d["entries"][0].__setitem__("period_months", 13))
    tick(fictional_store, privacy_root, hours=1)  # the ROPA re-renders
    assert reader(fictional_store, privacy_root)(STEP_DPIA, PROGRAMME) == before


def test_a_dpia_signoff_stops_covering_after_a_trigger_edit(fictional_store, privacy_root):
    tick(fictional_store, privacy_root)
    sign_step(fictional_store, privacy_root, STEP_VERIFIED)
    sign_step(fictional_store, privacy_root, "tm:step/ropa-approved")
    sign_step(fictional_store, privacy_root, STEP_DPIA)
    assert (STEP_DPIA, PROGRAMME) not in due_ids(fictional_store, privacy_root, TODAY)
    edit_yaml(jur(privacy_root) / "xx.yaml",
              lambda d: d["dpia_triggers"].append({"criterion": "large-scale", "citation": "Fictional Act s.50"}))
    sign_step(fictional_store, privacy_root, STEP_VERIFIED, at="2026-10-26T09:30:00+00:00")
    assert (STEP_DPIA, PROGRAMME) in due_ids(fictional_store, privacy_root, TODAY)


def test_a_base_trigger_that_is_not_a_screening_criterion_id_stops_the_dpia_page(fictional_store, privacy_root):
    edit_yaml(jur(privacy_root) / "xx.yaml",
              lambda d: d["dpia_triggers"].__setitem__(0, {"criterion": "Systematic scoring", "citation": "s.5"}))
    tick(fictional_store, privacy_root)
    st = app.load_state(fictional_store, privacy_root)
    with pytest.raises(PageProblem, match="unknown DPIA criterion 'Systematic scoring' in base profile"):
        app.PAGE_SPECS[STEP_DPIA](st, PROGRAMME)
    assert reader(fictional_store, privacy_root)(STEP_DPIA, PROGRAMME) is None  # a sign-off cannot be accepted either


def test_validate_refuses_a_base_trigger_that_is_not_a_screening_criterion_id(privacy_root):
    assert check_standards(privacy_root) == []
    edit_yaml(jur(privacy_root) / "xx.yaml",
              lambda d: d["dpia_triggers"].__setitem__(0, {"criterion": "Systematic scoring", "citation": "s.5"}))
    errors = check_standards(privacy_root)
    assert any("unknown DPIA criterion" in e and "Systematic scoring" in e for e in errors), errors


# --- 9: validate checks each template against its profile, and the retention against every profile --------


def base_template(root):
    return root / "standards" / "templates" / "privacy-notice.md"


def test_validate_names_a_base_element_with_no_marker_in_the_template(privacy_root):
    path = base_template(privacy_root)
    path.write_text(path.read_text(encoding="utf-8").replace("<!-- element: retention -->\n", ""), encoding="utf-8", newline="\n")
    errors = check_standards(privacy_root)
    assert any("privacy-notice.md" in e and "retention" in e and "no marker" in e for e in errors), errors


def test_validate_names_a_marker_the_profile_does_not_list(privacy_root):
    path = base_template(privacy_root)
    path.write_text(path.read_text(encoding="utf-8") + "\n<!-- element: ghost -->\nText.\n", encoding="utf-8", newline="\n")
    errors = check_standards(privacy_root)
    assert any("privacy-notice.md" in e and "ghost" in e for e in errors), errors


def test_validate_checks_an_overlay_template_against_its_profile(privacy_root):
    add_overlay(privacy_root)
    assert check_standards(privacy_root) == []
    tpl = privacy_root / "standards" / "templates" / "privacy-notice-us-ca.md"
    tpl.write_text("## No markers here\n\nText.\n", encoding="utf-8", newline="\n")
    errors = check_standards(privacy_root)
    assert any("privacy-notice-us-ca.md" in e and "categories-collected" in e for e in errors), errors


def test_validate_refuses_a_retention_entry_that_breaks_a_draft_profiles_limit(privacy_root):
    assert check_standards(privacy_root) == []
    edit_yaml(privacy_root / "standards" / "retention.yaml",
              lambda d: [e.__setitem__("period_months", 61) for e in d["entries"] if e["category"] == "performance-data"])
    errors = check_standards(privacy_root)
    assert any("retention" in e and "61 months is above the 60-month maximum" in e for e in errors), errors


def test_validate_checks_the_effective_entries_of_an_overlay_against_its_limits(privacy_root):
    add_overlay(privacy_root, limits=[{"category": "performance-data", "max_months": 12, "citation": "Fictional Act s.10"}])
    errors = check_standards(privacy_root)
    assert any("24 months is above the 12-month maximum" in e and "tm:jurisdiction/us-ca" in e for e in errors), errors


# --- 10: one malformed profile isolates to its own jurisdiction -----------------------------------------


def break_overlay(root):
    (jur(root) / "us-ca.yaml").write_text("schema_version: 1\nid: tm:jurisdiction/us-ca\nrole: overlay\n", encoding="utf-8")


def test_a_broken_overlay_does_not_stop_the_base_profile(privacy_root):
    add_overlay(privacy_root)
    break_overlay(privacy_root)
    path, doc = privacy.base_profile(privacy_root)
    assert doc["role"] == "base" and privacy.base_codes(privacy_root) == ["IE"]
    assert privacy.overlay_profile("DE", privacy_root) is None


def test_a_broken_overlay_blocks_only_its_own_code_and_names_the_file(privacy_root):
    add_overlay(privacy_root)
    break_overlay(privacy_root)
    with pytest.raises(privacy.PrivacyError, match="us-ca.yaml"):
        privacy.overlay_profile("US-CA", privacy_root)


def test_a_broken_overlay_with_invalid_yaml_syntax_is_still_an_overlay(privacy_root):
    add_overlay(privacy_root)
    (jur(privacy_root) / "us-ca.yaml").write_text("role: overlay\nid: [unclosed\n", encoding="utf-8")
    assert privacy.base_profile(privacy_root)[1]["role"] == "base"


def test_a_broken_base_still_stops_everything(fictional_store, privacy_root):
    add_overlay(privacy_root)
    (jur(privacy_root) / "xx.yaml").write_text("schema_version: 1\nid: tm:jurisdiction/xx\nrole: base\n", encoding="utf-8")
    with pytest.raises(privacy.PrivacyError, match="xx.yaml"):
        privacy.base_profile(privacy_root)
    with pytest.raises(app.AppError, match="xx.yaml"):
        app.load_state(fictional_store, privacy_root)


def test_a_broken_overlay_leaves_the_base_flows_running(fictional_store, privacy_root):
    add_overlay(privacy_root)
    break_overlay(privacy_root)
    rep = tick(fictional_store, privacy_root)
    assert all(r.ok for r in rep)
    assert any(e["payload"].get("step") == setup.STEP_ROPA for e in app.read_events(fictional_store) if e["kind"] == "step")
    st = app.load_state(fictional_store, privacy_root)  # ingest loads the same state
    assert st.settings["notice_version"] == "2026-11"
    assert (STEP_VERIFIED, PROGRAMME) in due_ids(fictional_store, privacy_root, TODAY)


def test_a_broken_overlay_is_reported_by_its_own_steps(privacy_root, tmp_path):
    add_overlay(privacy_root)
    break_overlay(privacy_root)
    private = tmp_path / "p"
    private.mkdir()
    out = overlay.profile_present(private, [], OVERLAY_URI, "US-CA", T0, root=privacy_root)
    assert out and out[0]["payload"]["result"] == "blocked"
    assert any("us-ca.yaml" in r for r in out[0]["payload"]["reasons"])


def test_validate_still_reports_every_broken_file(privacy_root):
    add_overlay(privacy_root)
    break_overlay(privacy_root)
    errors = check_standards(privacy_root)
    assert any("us-ca.yaml" in e for e in errors)


# --- 12: a skip counts only when the system wrote it ---------------------------------------------------


STEP = {"id": "tm:step/dpia-delta", "subject": "jurisdiction", "needs": [],
        "done_when": {"kind": "signoff", "match": {"step": "tm:step/dpia-delta"}, "bind": "input", "skippable": True}}
J = "tm:jurisdiction/us-ca"


def skip_event(actor):
    return events.make_event("step", J, actor, {"step": "tm:step/dpia-delta", "skipped": True, "reason": "no delta",
                                                "input_sha256": "h" * 64}, at="2026-10-26T09:00:00+00:00")


def test_a_skip_event_from_the_system_closes_a_skippable_step():
    done = workflow._completions(STEP, J, [skip_event(SYSTEM_ACTOR)], lambda step, subject: "h" * 64)
    assert len(done) == 1


def test_a_skip_event_from_anyone_else_does_not():
    assert workflow._completions(STEP, J, [skip_event("tm:person/dpo-1")], lambda step, subject: "h" * 64) == []


def test_the_dpia_delta_check_counts_a_skip_only_from_the_system():
    inputs = {"x": 1}
    sha = signoff.input_sha256(inputs)
    forged = events.make_event("step", J, "tm:person/dpo-1", {"step": privacy.STEP_DPIA_DELTA, "skipped": True,
                                                              "input_sha256": sha}, at="2026-10-26T09:00:00+00:00")
    real = events.make_event("step", J, SYSTEM_ACTOR, {"step": privacy.STEP_DPIA_DELTA, "skipped": True,
                                                       "input_sha256": sha}, at="2026-10-26T09:00:00+00:00")
    assert not privacy.dpia_delta_done([forged], J, inputs)
    assert privacy.dpia_delta_done([real], J, inputs)
    assert privacy.dpia_delta_done([forged, real], J, inputs)


# --- 14: the base codes are required --------------------------------------------------------------------


def test_the_engine_has_no_default_base_codes():
    with pytest.raises(TypeError):
        workflow.subjects([])
    with pytest.raises(TypeError):
        workflow.notice_variant("2026-11", "IE")
    assert not hasattr(workflow, "BASE_CODES")
    assert workflow.notice_variant("2026-11", "IE", ["IE"]) == "2026-11"
    assert workflow.notice_variant("2026-11", "US-CA", ["IE"]) == "2026-11-us-ca"
    assert set(workflow.subjects([], ["IE"])) == {PROGRAMME}


# --- 13: an event-ended entry against a limit ------------------------------------------------------------


def test_an_event_ended_entry_passes_a_minimum_and_fails_a_maximum(privacy_root):
    _, base = privacy.base_profile(privacy_root)
    entry = {"category": "record-of-actions", "purpose": "p", "until_event": "the instructor asks", "starts": "x",
             "reason": "r", "basis": "legitimate-interests"}
    only_min = {**base, "retention_limits": [{"category": "record-of-actions", "min_months": 12, "citation": "c"}]}
    assert privacy.limit_breaches([entry], only_min) == []
    with_max = {**base, "retention_limits": [{"category": "record-of-actions", "max_months": 120, "citation": "c"}]}
    (breach,) = privacy.limit_breaches([entry], with_max)
    assert "has no maximum" in breach
    assert "unbounded" in privacy.limit_breaches.__doc__
