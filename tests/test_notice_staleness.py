"""Integration-review fixes 1 and 4: an unapproved retention period never reaches a notice, and a notice text cannot
change under a version that has already been sent. Fictional fixtures only (base `xx` coded IE, overlay coded US-CA)."""

import email
import email.policy
import hashlib
import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from conftest import EXAMPLE_ROSTER_PATH, make_fictional_store
from privacy_helpers import (
    OVERLAY_URI,
    PROGRAMME,
    STEP_NOTICE_APPROVED,
    STEP_RETENTION,
    add_overlay,
    due_ids,
    edit_yaml,
    make_privacy_root,
    sign_step,
)
from test_privacy_overlay_workflow import TODAY, events_of, tick, to_overlay, verify_overlay

from teachermodel import app, events, overlay, privacy, setup

VARIANT_APPROVED = privacy.STEP_VARIANT_APPROVED
SME, CONTRACTOR = "tm:instructor/k7m2q", "tm:instructor/c5w1t"
NOW = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)


def build_sent_world(base):
    """The overlay world through an approved variant and its drafts: Irish (base) and Californian (variant) drafts exist."""
    private, root = make_fictional_store(base), make_privacy_root(base)
    add_overlay(root)
    roster = base / "roster-in.yaml"
    shutil.copy(EXAMPLE_ROSTER_PATH, roster)
    to_overlay(private, root, roster)
    verify_overlay(private, root)
    sign_step(private, root, VARIANT_APPROVED, subject=OVERLAY_URI, at="2026-10-26T11:00:00+00:00")
    tick(private, root, hours=5)


@pytest.fixture
def sent_world(fictional_store, privacy_root, cached_world):
    """build_sent_world, built once per session and copied into this test's tmp_path."""
    cached_world("sent_world", build_sent_world)
    return fictional_store, privacy_root


def set_months(root, months):
    edit_yaml(root / "standards" / "retention.yaml",
              lambda d: d["entries"][0].__setitem__("period_months", months))


def draft(private, uri):
    """The text body of an instructor's unsent draft."""
    raw = (private / "generated" / "notice-drafts" / f"{uri.split('/', 1)[1]}.eml").read_bytes()
    return email.message_from_bytes(raw, policy=email.policy.default).get_body(("plain",)).get_content().replace("\r\n", "\n")


def sha_of_last_draft(private, uri):
    return events_of(private, "step", "tm:step/notice-drafts", uri)[-1]["payload"]["text_sha256"]


def sent(private, uri, variant, op="o" * 8):
    events.append(private / app.EVENT_LOG, events.make_event(
        "notice", uri, "tm:system/teachermodel",
        {"step": "tm:step/notice-sent", "notice_version": "2026-11", "given_on": "2026-10-27", "op_id": op,
         "notice_variant": variant}, at="2026-10-27T09:00:00+00:00"))


# --- 1: retention reaches no notice unapproved --------------------------------------------------------------


def test_the_reviewers_scenario_an_unapproved_period_does_not_reach_the_variant(sent_world):
    private, root = sent_world
    variant = private / "generated" / "notice-2026-11-us-ca.md"
    before = variant.read_text(encoding="utf-8")
    assert "24 months" in before
    set_months(root, 12)  # nobody approves it
    tick(private, root, hours=6)
    assert variant.read_text(encoding="utf-8") == before  # not re-rendered
    base = (private / "generated" / "notice-2026-11.md").read_text(encoding="utf-8")
    assert "12 months" not in base
    now = due_ids(private, root, TODAY)
    assert (STEP_RETENTION, PROGRAMME) in now  # the head of training is asked again
    assert (STEP_NOTICE_APPROVED, PROGRAMME) not in now and (VARIANT_APPROVED, OVERLAY_URI) not in now
    assert ("tm:step/notice-drafts", SME) not in now


def test_notice_variant_refuses_while_retention_is_not_approved(sent_world):
    private, root = sent_world
    set_months(root, 12)
    st = app.load_state(private, root)
    (blocked,) = overlay.notice_variant(private, st.events, st.settings, OVERLAY_URI, "US-CA", NOW, root=root)
    assert blocked["kind"] == "check" and "retention not approved" in blocked["payload"]["reasons"]


def test_the_approvals_of_the_notice_and_the_variant_cover_the_retention_they_were_rendered_with(sent_world):
    private, root = sent_world
    st = app.load_state(private, root)
    read = app._current_input_reader(st)
    base_before, variant_before = read(STEP_NOTICE_APPROVED, PROGRAMME), read(VARIANT_APPROVED, OVERLAY_URI)
    assert base_before and variant_before
    set_months(root, 12)
    st = app.load_state(private, root)
    read = app._current_input_reader(st)
    assert read(STEP_NOTICE_APPROVED, PROGRAMME) != base_before
    assert read(VARIANT_APPROVED, OVERLAY_URI) != variant_before


def test_notice_inputs_and_variant_inputs_carry_a_retention_hash():
    assert setup.notice_inputs("t", "v", "p", "r" * 64)["retention_sha256"] == "r" * 64
    assert setup.variant_inputs("t", "v", "b", "o", "r" * 64)["retention_sha256"] == "r" * 64


def test_the_whole_chain_runs_again_after_a_retention_change_and_the_drafts_follow(sent_world):
    private, root = sent_world
    assert "24 months" in (private / "generated" / "notice-2026-11-us-ca.md").read_text(encoding="utf-8")
    set_months(root, 12)
    tick(private, root, hours=6)
    sign_step(private, root, STEP_RETENTION, at="2026-10-26T12:00:00+00:00")
    tick(private, root, hours=7)  # the base notice re-renders with 12 months
    assert "12 months" in (private / "generated" / "notice-2026-11.md").read_text(encoding="utf-8")
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T12:10:00+00:00")
    tick(private, root, hours=8)  # the variant re-renders
    assert "12 months" in (private / "generated" / "notice-2026-11-us-ca.md").read_text(encoding="utf-8")
    assert "12 months" not in draft(private, CONTRACTOR)  # the Californian draft waits for the approved variant
    sign_step(private, root, VARIANT_APPROVED, subject=OVERLAY_URI, at="2026-10-26T12:20:00+00:00")
    tick(private, root, hours=9)
    assert "12 months" in draft(private, CONTRACTOR) and "12 months" in draft(private, SME)


# --- 4: a text cannot change under a version that was sent -----------------------------------------------


def approve_new_retention(private, root, months, hour):
    set_months(root, months)
    tick(private, root, hours=hour)
    sign_step(private, root, STEP_RETENTION, at=f"2026-10-26T{hour + 6:02d}:00:00+00:00")


def test_notice_text_will_not_change_under_a_version_that_was_sent(sent_world):
    private, root = sent_world
    sent(private, SME, "2026-11")
    path = private / "generated" / "notice-2026-11.md"
    before = path.read_bytes()
    approve_new_retention(private, root, 12, 6)
    tick(private, root, hours=7)
    assert path.read_bytes() == before
    blocked = [e for e in events_of(private, "check", setup.STEP_NOTICE_TEXT) if e["payload"]["result"] == "blocked"]
    assert blocked and blocked[-1]["payload"]["reasons"] == [
        "notice text changed under version 2026-11: bump notice_version in settings"]


def test_an_unchanged_text_under_a_sent_version_is_not_blocked(sent_world):
    private, root = sent_world
    sent(private, SME, "2026-11")
    st = app.load_state(private, root)
    assert setup.notice_text(private, st.events, st.settings, NOW, root=root) == []


def test_notice_text_may_change_under_a_version_nobody_was_sent(sent_world):
    private, root = sent_world
    approve_new_retention(private, root, 12, 6)
    tick(private, root, hours=7)
    assert "12 months" in (private / "generated" / "notice-2026-11.md").read_text(encoding="utf-8")


def test_the_variant_will_not_change_under_a_variant_that_was_sent(sent_world):
    private, root = sent_world
    sent(private, CONTRACTOR, "2026-11-us-ca")
    path = private / "generated" / "notice-2026-11-us-ca.md"
    before = path.read_bytes()
    approve_new_retention(private, root, 12, 6)
    tick(private, root, hours=7)
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T14:00:00+00:00")  # the base had no sent notice
    tick(private, root, hours=9)
    assert path.read_bytes() == before
    blocked = [e for e in events_of(private, "check", privacy.STEP_NOTICE_VARIANT, OVERLAY_URI)
               if e["payload"]["result"] == "blocked"]
    assert blocked and "notice text changed under variant 2026-11-us-ca: bump notice_version in settings" in \
        blocked[-1]["payload"]["reasons"]


# --- 4: a draft follows the approved text ------------------------------------------------------------------


def test_a_draft_is_rebuilt_when_the_approved_text_differs_from_the_one_it_was_built_from(sent_world):
    private, root = sent_world
    before = sha_of_last_draft(private, SME)
    assert "24 months" in draft(private, SME)
    approve_new_retention(private, root, 12, 6)
    tick(private, root, hours=7)
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T14:00:00+00:00")
    tick(private, root, hours=9)
    after = sha_of_last_draft(private, SME)
    assert after != before
    assert "12 months" in draft(private, SME)
    text = (private / "generated" / "notice-2026-11.md").read_text(encoding="utf-8")
    assert after == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_a_draft_that_is_up_to_date_is_not_rewritten(sent_world):
    private, root = sent_world
    count = len(events_of(private, "step", "tm:step/notice-drafts", SME))
    tick(private, root, hours=10)
    tick(private, root, hours=11)
    assert len(events_of(private, "step", "tm:step/notice-drafts", SME)) == count
