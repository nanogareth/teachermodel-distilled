"""tm:workflow/privacy-overlay driven through the app: profile present, verified, retention check, DPIA delta, notice
variant, then the drafts and the W1 chain of an overlay instructor (privacy-jurisdictions design section 4). Fictional
fixtures only (base `xx` coded IE, an overlay coded US-CA), except the one test of the real standards at the end."""

import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from conftest import EXAMPLE_ROSTER_PATH, make_fictional_store
from privacy_helpers import (
    OVERLAY_URI,
    STEP_DPIA,
    STEP_NOTICE_APPROVED,
    STEP_RETENTION,
    STEP_VERIFIED,
    add_overlay,
    due_ids,
    edit_yaml,
    import_roster_ungated,
    make_privacy_root,
    seed_check,
    sign_step,
    tm_data,
)

from teachermodel import app, privacy
from teachermodel.standards import ROOT, load_standards
from teachermodel.workflow import PROGRAMME

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
TODAY = T0.date()
DE = "tm:jurisdiction/de"
SME, PRO, CONTRACTOR, PARTNER = "tm:instructor/k7m2q", "tm:instructor/p3x9d", "tm:instructor/c5w1t", "tm:instructor/r8n4h"
PROFILE_PRESENT, PROFILE_VERIFIED = privacy.STEP_PROFILE_PRESENT, privacy.STEP_PROFILE_VERIFIED
RETENTION_CHECK, DELTA_CHECK, DELTA = privacy.STEP_RETENTION_CHECK, privacy.STEP_DPIA_DELTA_CHECK, privacy.STEP_DPIA_DELTA
VARIANT, VARIANT_APPROVED = privacy.STEP_NOTICE_VARIANT, privacy.STEP_VARIANT_APPROVED
DRAFTS = "tm:step/notice-drafts"
VARIANT_ID = "2026-11-us-ca"


def tick(private, root, hours=0):
    return app.do_tick(private, now=T0 + timedelta(hours=hours), root=root)


def events_of(private, kind, step=None, subject=None):
    return [e for e in app.read_events(private) if e["kind"] == kind and (step is None or e["payload"].get("step") == step)
            and (subject is None or e["subject_uri"] == subject)]


def due(private, root):
    return due_ids(private, root, TODAY)


@pytest.fixture
def roster(tmp_path):
    dest = tmp_path / "roster-in.yaml"
    shutil.copy(EXAMPLE_ROSTER_PATH, dest)
    return dest


def to_overlay(private, root, roster):
    """The base workflow done through the base notice approval, the roster imported (Irish, Californian and German
    instructors), and one tick since: the overlay workflow has begun for US-CA and DE."""
    tick(private, root)
    seed_check(private, "tm:step/library-exists")
    sign_step(private, root, STEP_VERIFIED, at="2026-10-26T09:00:00+00:00")
    sign_step(private, root, STEP_DPIA, at="2026-10-26T09:05:00+00:00")
    sign_step(private, root, STEP_RETENTION, at="2026-10-26T09:10:00+00:00")
    app.do_import_roster(private, roster, now=T0 + timedelta(hours=1), root=root)
    tick(private, root, hours=2)
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T09:20:00+00:00")
    tick(private, root, hours=3)


def build_world(base):
    private, root = make_fictional_store(base), make_privacy_root(base)
    roster = base / "roster-in.yaml"
    shutil.copy(EXAMPLE_ROSTER_PATH, roster)
    add_overlay(root)
    to_overlay(private, root, roster)


@pytest.fixture
def world(fictional_store, privacy_root, roster, cached_world):
    """The overlay added and to_overlay done: built once per session, copied into this test's tmp_path."""
    cached_world("overlay_world", build_world)
    return fictional_store, privacy_root


def verify_overlay(private, root, hours=4):
    sign_step(private, root, PROFILE_VERIFIED, subject=OVERLAY_URI, at="2026-10-26T10:00:00+00:00")
    tick(private, root, hours=hours)


# --- the workflow definition -----------------------------------------------------------------------


def _steps():
    return {w["id"]: {s["id"]: s for s in w["steps"]} for w in load_standards()["workflows"]["workflows"]}


def test_privacy_overlay_defines_the_steps_with_their_roles_and_bindings():
    steps = _steps()["tm:workflow/privacy-overlay"]
    assert set(steps) == {PROFILE_PRESENT, PROFILE_VERIFIED, RETENTION_CHECK, DELTA_CHECK, DELTA, VARIANT, VARIANT_APPROVED}
    assert all(s["subject"] == "jurisdiction" for s in steps.values())
    assert {k: (s["type"], s["role"]) for k, s in steps.items()} == {
        PROFILE_PRESENT: ("auto", "legal"), PROFILE_VERIFIED: ("human", "legal"),
        RETENTION_CHECK: ("auto", "head-of-training"), DELTA_CHECK: ("auto", "dpo"), DELTA: ("human", "dpo"),
        VARIANT: ("auto", "programme-owner"), VARIANT_APPROVED: ("human", "programme-owner")}
    for human in (PROFILE_VERIFIED, DELTA, VARIANT_APPROVED):
        assert steps[human]["done_when"]["bind"] == "input"
    assert steps[DELTA]["done_when"].get("skippable") is True
    assert steps[DELTA]["page"] == "dpia_screening" and steps[PROFILE_VERIFIED]["page"] == "approve"
    assert steps[PROFILE_VERIFIED]["needs"] == [PROFILE_PRESENT]
    assert set(steps[VARIANT]["needs"]) == {PROFILE_VERIFIED, RETENTION_CHECK, DELTA, STEP_NOTICE_APPROVED}
    assert set(steps[RETENTION_CHECK]["needs"]) == {PROFILE_VERIFIED, STEP_RETENTION}
    assert set(steps[VARIANT_APPROVED]["needs"]) == {PROFILE_VERIFIED, VARIANT, STEP_NOTICE_APPROVED}


def test_drafts_sent_and_w1_follow_the_variant():
    steps = {k: s for group in _steps().values() for k, s in group.items()}
    assert VARIANT_APPROVED in steps[DRAFTS]["needs"]
    sent = steps["tm:step/notice-sent"]["done_when"]
    assert sent["kind"] == "notice"
    assert sent["match"] == {"step": "tm:step/notice-sent", "notice_variant": "${subject.notice_variant}"}
    for w1 in ("commitment-manager", "commitment-partner-lead", "baseline-self-assessment"):
        needs = steps[f"tm:step/{w1}"]["needs"]
        assert "tm:step/notice-sent" in needs and VARIANT_APPROVED in needs, w1


# --- profile-present ------------------------------------------------------------------------------


def test_the_overlay_workflow_starts_for_each_non_base_code_after_the_roster_import(world):
    private, root = world
    st = app.load_state(private, root)
    assert {u for u, i in st.subjects.items() if i["kind"] == "jurisdiction"} == {OVERLAY_URI, DE}
    present = events_of(private, "step", PROFILE_PRESENT)
    assert [e["subject_uri"] for e in present] == [OVERLAY_URI] and present[0]["payload"]["profile"] == OVERLAY_URI
    blocked = events_of(private, "check", PROFILE_PRESENT, DE)
    assert len(blocked) == 1 and blocked[0]["payload"]["reasons"] == ["no profile for DE"]
    now = due(private, root)
    assert (PROFILE_PRESENT, DE) in now and (PROFILE_PRESENT, OVERLAY_URI) not in now  # DE stays waiting
    assert (PROFILE_VERIFIED, OVERLAY_URI) in now and (PROFILE_VERIFIED, DE) not in now


def test_the_german_overlay_never_gets_past_profile_present_and_the_irish_base_has_none(world):
    private, root = world
    verify_overlay(private, root)
    tick(private, root, hours=5)
    de_steps = {s for s, u in due(private, root) | set() if u == DE}
    assert de_steps == {PROFILE_PRESENT}
    assert not [e for e in app.read_events(private) if e["subject_uri"] == "tm:jurisdiction/ie"]


def test_the_overlay_page_shows_the_profile_bytes_the_base_hash_and_a_first_verification(world):
    private, root = world
    page = private / "pages" / "profile-verified--us-ca--legal-1.html"
    data = tm_data(page)
    base_path, _ = privacy.base_profile(root)
    path, _ = privacy.overlay_profile("US-CA", root)
    assert data["subject_uri"] == OVERLAY_URI and data["role"] == "legal" and data["step"] == PROFILE_VERIFIED
    assert data["inputs"] == privacy.overlay_profile_inputs(path, base_path, root)
    assert "first verification" in page.read_text(encoding="utf-8")


# --- the rest of the overlay chain ----------------------------------------------------------------


def test_verifying_the_overlay_runs_the_checks_skips_the_empty_delta_and_renders_the_variant(world):
    private, root = world
    verify_overlay(private, root)
    assert [e["subject_uri"] for e in events_of(private, "step", RETENTION_CHECK)] == [OVERLAY_URI]
    assert events_of(private, "step", DELTA_CHECK)[0]["payload"]["delta"] == []
    skip = events_of(private, "step", DELTA)[0]["payload"]
    assert skip["skipped"] is True and skip["reason"] == "no delta"
    now = due(private, root)
    assert (DELTA, OVERLAY_URI) not in now  # skipped: the DPO is never asked
    out = events_of(private, "step", VARIANT)[0]["payload"]
    assert out["notice_variant"] == VARIANT_ID and (private / out["output"]).is_file()
    assert (VARIANT_APPROVED, OVERLAY_URI) in now
    page = tm_data(private / "pages" / "variant-approved--us-ca--owner-1.html")
    assert page["inputs"]["version"] == VARIANT_ID and "For residents of Fictional State" in page["inputs"]["text"]


def test_the_drafts_of_the_irish_wait_for_nothing_and_the_californian_waits_for_the_variant(world):
    private, root = world
    verify_overlay(private, root)
    drafted = {e["subject_uri"]: e["payload"]["notice_variant"] for e in events_of(private, "step", DRAFTS)
               if "output" in e["payload"]}
    assert drafted == {SME: "2026-11", PRO: "2026-11"}
    now = due(private, root)
    assert (DRAFTS, CONTRACTOR) not in now and (DRAFTS, PARTNER) not in now  # their needs are unmet
    assert ("tm:step/notice-sent", SME) in now and ("tm:step/notice-sent", CONTRACTOR) not in now
    sign_step(private, root, VARIANT_APPROVED, subject=OVERLAY_URI, at="2026-10-26T11:00:00+00:00")
    tick(private, root, hours=5)
    assert (DRAFTS, CONTRACTOR) not in due(private, root)
    drafted = {e["subject_uri"]: e["payload"]["notice_variant"] for e in events_of(private, "step", DRAFTS)
               if "output" in e["payload"]}
    assert drafted[CONTRACTOR] == VARIANT_ID and PARTNER not in drafted
    msg = (private / "generated" / "notice-drafts" / "c5w1t.eml").read_text(encoding="utf-8")
    assert f"[tm-notice {VARIANT_ID}]" in msg
    assert ("tm:step/notice-sent", CONTRACTOR) in due(private, root)


def test_the_plan_asks_for_each_instructors_own_tag(world):
    private, root = world
    verify_overlay(private, root)
    sign_step(private, root, VARIANT_APPROVED, subject=OVERLAY_URI, at="2026-10-26T11:00:00+00:00")
    tick(private, root, hours=5)
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    tags = {o["subject"]: o["args"]["tag"] for o in plan["ops"] if o["op"] == "mail.sent"}
    assert tags == {SME: "[tm-notice 2026-11]", PRO: "[tm-notice 2026-11]", CONTRACTOR: f"[tm-notice {VARIANT_ID}]"}


def test_a_delta_asks_the_dpo_and_holds_the_variant_until_it_is_decided(fictional_store, privacy_root, roster):
    add_overlay(privacy_root, triggers=[{"criterion": "ca-sell-or-share", "citation": "Fictional Act s.21"}])
    to_overlay(fictional_store, privacy_root, roster)
    private, root = fictional_store, privacy_root
    verify_overlay(private, root)
    assert events_of(private, "step", DELTA_CHECK)[0]["payload"]["delta"] == ["ca-sell-or-share"]
    assert not events_of(private, "step", DELTA) and not events_of(private, "step", VARIANT)
    assert (DELTA, OVERLAY_URI) in due(private, root)
    page = tm_data(private / "pages" / "dpia-delta--us-ca--dpo-1.html")
    assert page["role"] == "dpo" and "ca-sell-or-share" in {f["name"] for f in page["fields"]}
    assert page["inputs"]["delta"] == [{"criterion": "ca-sell-or-share", "citations": ["Fictional Act s.21"]}]
    sign_step(private, root, DELTA, subject=OVERLAY_URI, at="2026-10-26T10:30:00+00:00")
    tick(private, root, hours=5)
    assert (DELTA, OVERLAY_URI) not in due(private, root)
    assert events_of(private, "step", VARIANT) and (VARIANT_APPROVED, OVERLAY_URI) in due(private, root)


def test_a_breach_of_the_overlay_limits_blocks_the_variant_until_an_overlay_entry_fits(
        fictional_store, privacy_root, roster):
    add_overlay(privacy_root, limits=[
        {"category": "performance-data", "max_months": 12, "citation": "Fictional Privacy Rights Act s.10"}])
    private, root = fictional_store, privacy_root
    to_overlay(private, root, roster)
    verify_overlay(private, root)
    blocked = events_of(private, "check", RETENTION_CHECK, OVERLAY_URI)
    assert len(blocked) == 1 and "12-month maximum" in blocked[0]["payload"]["reasons"][0]
    assert not events_of(private, "step", RETENTION_CHECK) and not events_of(private, "step", VARIANT)
    assert (RETENTION_CHECK, OVERLAY_URI) in due(private, root)
    # the fix: an overlay entry for the pair; the base entry stays, so the base approval reopens with the new row
    edit_yaml(root / "standards" / "retention.yaml", lambda d: d["entries"].append(
        {"category": "performance-data", "purpose": "tm:purpose/test-clearance", "jurisdiction": OVERLAY_URI,
         "period_months": 12, "starts": "The engagement ends.", "reason": "Fictional: the overlay allows 12 months.",
         "basis": "legitimate-interests"}))
    tick(private, root, hours=5)
    assert (STEP_RETENTION, PROGRAMME) in due(private, root)  # the table changed, so the approval is open again
    sign_step(private, root, STEP_RETENTION, at="2026-10-26T12:00:00+00:00")
    tick(private, root, hours=6)
    assert events_of(private, "step", RETENTION_CHECK) and (RETENTION_CHECK, OVERLAY_URI) not in due(private, root)


def test_editing_the_base_profile_reopens_the_overlay_approvals(world):
    private, root = world
    verify_overlay(private, root)
    sign_step(private, root, VARIANT_APPROVED, subject=OVERLAY_URI, at="2026-10-26T11:00:00+00:00")
    tick(private, root, hours=5)
    now = due(private, root)
    assert (PROFILE_VERIFIED, OVERLAY_URI) not in now and (VARIANT_APPROVED, OVERLAY_URI) not in now
    base_path, _ = privacy.base_profile(root)
    base_path.write_bytes(base_path.read_bytes() + b"# edited\n")
    now = due(private, root)
    assert (STEP_VERIFIED, PROGRAMME) in now and (PROFILE_VERIFIED, OVERLAY_URI) in now
    assert (VARIANT_APPROVED, OVERLAY_URI) not in now  # it waits for the overlay to be verified again


def test_editing_the_overlay_profile_reopens_its_approvals_and_rerenders_the_variant(world):
    private, root = world
    verify_overlay(private, root)
    sign_step(private, root, VARIANT_APPROVED, subject=OVERLAY_URI, at="2026-10-26T11:00:00+00:00")
    tick(private, root, hours=5)
    _, path = privacy.base_profile(root)[0], privacy.overlay_profile("US-CA", root)[0]
    path.write_bytes(path.read_bytes() + b"# edited\n")
    assert (PROFILE_VERIFIED, OVERLAY_URI) in due(private, root)
    sign_step(private, root, PROFILE_VERIFIED, subject=OVERLAY_URI, at="2026-10-26T13:00:00+00:00")
    tick(private, root, hours=7)
    assert (VARIANT_APPROVED, OVERLAY_URI) in due(private, root)  # the owner approves the variant again


# --- the real standards (J5 drafts), no names anywhere --------------------------------------------------


def test_with_the_real_standards_us_ca_waits_for_legal_and_de_is_blocked(fictional_store, roster):
    private = fictional_store
    import_roster_ungated(private, roster, T0)
    app.do_run(private, now=T0, root=ROOT)
    queue = app.do_next(private, now=T0, root=ROOT).lines
    assert any(PROFILE_VERIFIED in line and "tm:jurisdiction/us-ca" in line and " legal " in line for line in queue), queue
    assert any(PROFILE_PRESENT in line and "tm:jurisdiction/de" in line for line in queue), queue
    assert not any(PROFILE_VERIFIED in line and "tm:jurisdiction/de" in line for line in queue)
    blocked = events_of(private, "check", PROFILE_PRESENT, DE)
    assert [e["payload"]["reasons"] for e in blocked] == [["no profile for DE"]]
    present = events_of(private, "step", PROFILE_PRESENT, OVERLAY_URI)
    assert present and present[0]["payload"]["profile"] == OVERLAY_URI
    st = app.load_state(private, ROOT)
    assert "tm:jurisdiction/ie" not in st.subjects  # Ireland is the base
    app.do_pages(private, now=T0, root=ROOT)
    data = tm_data(private / "pages" / "profile-verified--us-ca--legal-1.html")
    assert data["inputs"]["profile"]["status"] == "draft" and data["inputs"]["profile"]["drafted_by"] == "ai-assisted"
    raw = (private / app.EVENT_LOG).read_text(encoding="utf-8")
    names = yaml.safe_load(EXAMPLE_ROSTER_PATH.read_text(encoding="utf-8"))["instructors"]
    assert not [n for row in names for n in row["identity"].values() if str(n) in raw]
