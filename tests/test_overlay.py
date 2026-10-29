"""Overlay workflow auto steps: profile-present, retention-check, dpia-delta-check, notice-variant (privacy-
jurisdictions design section 4). Fictional fixtures only: the base profile `xx` re-coded to IE and a fictional overlay
coded US-CA, never the AI-drafted profiles."""

from datetime import datetime, timezone

import pytest
import yaml
from privacy_helpers import OVERLAY_URI, add_overlay, edit_yaml, prerequisite_events

from teachermodel import events, overlay, privacy, setup, signoff
from teachermodel.bridge import SYSTEM_ACTOR
from teachermodel.workflow import PROGRAMME

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
SETTINGS = {
    "schema": "tm:contract/settings@1", "library": "TeacherModel Private", "mailbox": "signoffs@example.com",
    "it_email": "it.requests@example.com", "dpo_email": "dpo@example.com", "notice_version": "2026-11",
}
VARIANT = "2026-11-us-ca"
LIMITS = [{"category": "performance-data", "max_months": 12, "citation": "Fictional Privacy Rights Act s.10"}]


@pytest.fixture
def private(tmp_path):
    p = tmp_path / "private"
    p.mkdir()
    return p


@pytest.fixture
def root(privacy_root):
    add_overlay(privacy_root)
    return privacy_root


def kinds(evs):
    return [e["kind"] for e in evs]


def check_all(evs):
    for e in evs:
        assert events.check_event(e) == [], e
    return evs


def approval(step, inputs, subject=PROGRAMME, at="2026-10-24T10:00:00+00:00", decision="approve"):
    payload = {"step": step, "decision": decision, "fields_sha256": "c" * 64, "input_sha256": signoff.input_sha256(inputs),
               "signoff_id": signoff.input_sha256([step, subject, at, decision])[:16], "page_template_sha256": "b" * 64,
               "signed_at": at}
    return events.make_event("signoff", subject, "tm:person/seed", payload, at=at)


def paths(root):
    base_path, _ = privacy.base_profile(root)
    path, _ = privacy.overlay_profile("US-CA", root)
    return base_path, path


def base_verified(root):
    base_path, _ = paths(root)
    return approval(privacy.STEP_BASE_PROFILE_VERIFIED, privacy.profile_inputs(base_path, root))


def retention_approved(root, log):
    ret = setup.load_retention(root / "standards" / "retention.yaml", root)
    return approval(privacy.STEP_RETENTION_APPROVED, privacy.retention_inputs(root, ret, log))


def overlay_verified(root):
    base_path, path = paths(root)
    return approval(privacy.STEP_PROFILE_VERIFIED, privacy.overlay_profile_inputs(path, base_path, root), OVERLAY_URI)


def base_notice_approved(private, root, log):
    """Render the base notice for `log` and return the owner's approval of it."""
    evs = setup.notice_text(private, log, SETTINGS, NOW, root=root)
    assert kinds(evs) == ["step"], evs
    text = (private / evs[0]["payload"]["output"]).read_text(encoding="utf-8")
    base_path, _ = paths(root)
    sha = privacy.profile_inputs(base_path, root)["sha256"]
    return approval(setup.STEP_NOTICE_APPROVED,
                    setup.notice_inputs(text, "2026-11", sha, setup.retention_digest(root, log)))


def ready(private, root):
    """A log in which everything the overlay steps need from the base workflow is done and legal verified the overlay."""
    log = [base_verified(root)]
    log.append(retention_approved(root, log))
    log.append(base_notice_approved(private, root, log))
    log.append(overlay_verified(root))
    return log


def run_variant(private, root, log, **kw):
    return overlay.notice_variant(private, log, SETTINGS, OVERLAY_URI, "US-CA", NOW, root=root, **kw)


def reasons_of(evs):
    assert kinds(evs) == ["check"], evs
    assert evs[0]["payload"]["result"] == "blocked" and evs[0]["subject_uri"] == OVERLAY_URI
    return evs[0]["payload"]["reasons"]


# --- profile-present ---------------------------------------------------------------------------------


def test_profile_present_is_done_once_an_overlay_profile_covers_the_code(root, private):
    evs = check_all(overlay.profile_present(private, [], OVERLAY_URI, "US-CA", NOW, root=root))
    assert kinds(evs) == ["step"] and evs[0]["subject_uri"] == OVERLAY_URI
    p = evs[0]["payload"]
    assert p["step"] == privacy.STEP_PROFILE_PRESENT and p["profile"] == OVERLAY_URI
    assert p["profile_sha256"] == privacy.profile_inputs(paths(root)[1], root)["sha256"]
    assert overlay.profile_present(private, evs, OVERLAY_URI, "US-CA", NOW, root=root) == []  # nothing new to say


def test_profile_present_is_blocked_with_the_code_until_a_profile_exists(root, private):
    evs = check_all(overlay.profile_present(private, [], "tm:jurisdiction/de", "DE", NOW, root=root))
    assert kinds(evs) == ["check"] and evs[0]["payload"]["result"] == "blocked"
    assert evs[0]["payload"]["reasons"] == ["no profile for DE"]
    assert evs[0]["subject_uri"] == "tm:jurisdiction/de" and evs[0]["payload"]["step"] == privacy.STEP_PROFILE_PRESENT
    assert overlay.profile_present(private, evs, "tm:jurisdiction/de", "DE", NOW, root=root) == []  # reported once


def test_a_base_profile_covering_the_code_does_not_count_as_an_overlay(root, private):
    edit_yaml(root / "standards" / "privacy" / "jurisdictions" / "xx.yaml", lambda d: d.__setitem__("codes", ["IE", "DE"]))
    evs = overlay.profile_present(private, [], "tm:jurisdiction/de", "DE", NOW, root=root)
    assert evs[0]["payload"]["reasons"] == ["no profile for DE"]


def test_profile_present_names_a_profile_that_breaks_its_contract(root, private):
    edit_yaml(root / "standards" / "privacy" / "jurisdictions" / "us-ca.yaml", lambda d: d.__setitem__("role", "primary"))
    evs = overlay.profile_present(private, [], OVERLAY_URI, "US-CA", NOW, root=root)
    assert kinds(evs) == ["check"] and "us-ca.yaml" in evs[0]["payload"]["reasons"][0]


# --- retention-check ---------------------------------------------------------------------------------


def run_retention(private, root, log):
    return overlay.retention_check(private, log, OVERLAY_URI, "US-CA", NOW, root=root)


def test_retention_check_passes_when_every_entry_is_inside_both_profiles(root, private):
    log = ready(private, root)
    evs = check_all(run_retention(private, root, log))
    assert kinds(evs) == ["step"] and evs[0]["payload"]["step"] == privacy.STEP_RETENTION_CHECK
    assert run_retention(private, root, log + evs) == []  # unchanged: nothing appended


def test_retention_check_names_each_breach_of_the_overlay_limits(tmp_path, private):
    root = make_root(tmp_path, limits=[
        *LIMITS, {"category": "record-of-actions", "min_months": 36, "citation": "Fictional Privacy Rights Act s.11"}])
    log = ready(private, root)
    reasons = reasons_of(check_all(run_retention(private, root, log)))
    assert len(reasons) == 2
    assert any("performance-data" in r and "24 months" in r and "12-month maximum" in r for r in reasons)
    assert any("record-of-actions" in r and "24 months" in r and "36-month minimum" in r for r in reasons)
    assert all(OVERLAY_URI in r for r in reasons)


def make_root(tmp_path, **kw):
    from privacy_helpers import make_privacy_root

    root = make_privacy_root(tmp_path)
    add_overlay(root, **kw)
    return root


def test_an_overlay_entry_cures_the_breach(tmp_path, private):
    root = make_root(tmp_path, limits=LIMITS)

    def override(d):
        d["entries"].append({"category": "performance-data", "purpose": "tm:purpose/test-clearance",
                             "jurisdiction": OVERLAY_URI, "period_months": 12, "starts": "The engagement ends.",
                             "reason": "Fictional: the overlay allows 12 months at most.", "basis": "legitimate-interests"})

    log = ready(private, root)
    assert reasons_of(run_retention(private, root, log))
    edit_yaml(root / "standards" / "retention.yaml", override)
    log = ready(private, root)  # the retention approval covers the new entries
    assert kinds(check_all(run_retention(private, root, log))) == ["step"]


def test_retention_check_is_blocked_until_the_overlay_is_verified_and_after_it_is_edited(root, private):
    log = ready(private, root)
    unverified = [e for e in log if e["payload"]["step"] != privacy.STEP_PROFILE_VERIFIED]
    assert reasons_of(run_retention(private, root, unverified)) == ["profile for US-CA is not verified"]
    base_path, _ = paths(root)
    base_path.write_bytes(base_path.read_bytes() + b"# edited\n")  # the overlay approval covers the base hash too
    assert reasons_of(run_retention(private, root, log)) == ["profile for US-CA is not verified"]


def test_retention_check_is_blocked_while_the_retention_table_is_empty(tmp_path, private):
    from privacy_helpers import make_privacy_root

    root = make_privacy_root(tmp_path, entries="empty")
    add_overlay(root)
    log = [base_verified(root), overlay_verified(root)]
    assert "retention entries still empty" in " ".join(reasons_of(run_retention(private, root, log)))


# --- dpia-delta-check --------------------------------------------------------------------------------


def run_delta(private, root, log):
    return overlay.dpia_delta_check(private, log, OVERLAY_URI, "US-CA", NOW, root=root)


def test_no_delta_closes_the_dpia_delta_with_a_skip_event_and_says_so(root, private):
    log = ready(private, root)
    evs = check_all(run_delta(private, root, log))
    assert kinds(evs) == ["step", "step"] and all(e["subject_uri"] == OVERLAY_URI for e in evs)
    checked, skipped = (e["payload"] for e in evs)
    assert checked["step"] == privacy.STEP_DPIA_DELTA_CHECK and checked["delta"] == []
    base_path, path = paths(root)
    assert skipped == {"step": privacy.STEP_DPIA_DELTA, "skipped": True, "reason": "no delta",
                       "input_sha256": signoff.input_sha256(privacy.dpia_delta_inputs(path, base_path, root))}
    assert run_delta(private, root, log + evs) == []


def test_a_delta_asks_the_dpo_and_writes_no_skip(tmp_path, private):
    root = make_root(tmp_path, triggers=[{"criterion": "ca-sell-or-share", "citation": "Fictional Act s.21"}])
    evs = check_all(run_delta(private, root, ready(private, root)))
    assert kinds(evs) == ["step"]
    assert evs[0]["payload"] == {"step": privacy.STEP_DPIA_DELTA_CHECK, "delta": ["ca-sell-or-share"]}


def test_a_changed_profile_gives_a_new_skip_with_a_new_hash(root, private):
    log = ready(private, root)
    first = run_delta(private, root, log)
    _, path = paths(root)
    path.write_bytes(path.read_bytes() + b"# edited\n")
    log = [e for e in log if e["payload"]["step"] != privacy.STEP_PROFILE_VERIFIED] + [overlay_verified(root)]
    again = run_delta(private, root, log + first)
    assert kinds(again) == ["step"]  # the check itself said the same; only the skip covers new bytes
    assert again[0]["payload"]["step"] == privacy.STEP_DPIA_DELTA
    assert again[0]["payload"]["input_sha256"] != first[1]["payload"]["input_sha256"]


def test_dpia_delta_check_waits_for_the_overlay_to_be_verified(root, private):
    log = [e for e in ready(private, root) if e["payload"]["step"] != privacy.STEP_PROFILE_VERIFIED]
    assert reasons_of(run_delta(private, root, log)) == ["profile for US-CA is not verified"]


# --- notice-variant ----------------------------------------------------------------------------------


def with_delta_done(root, log):
    """The DPIA delta closed the way the engine closes it: a skip event or the DPO's sign-off."""
    return log + run_delta(root.parent / "private", root, log)


def test_the_variant_is_the_base_notice_plus_the_overlay_sections_for_the_overlays_retention(tmp_path, private):
    root = make_root(tmp_path, limits=LIMITS)
    edit_yaml(root / "standards" / "retention.yaml", lambda d: d["entries"].append(
        {"category": "performance-data", "purpose": "tm:purpose/test-clearance", "jurisdiction": OVERLAY_URI,
         "period_months": 12, "starts": "The engagement ends.", "reason": "Fictional overlay reason for twelve months.",
         "basis": "legitimate-interests"}))
    log = ready(private, root)
    log = with_delta_done(root, log)
    evs = check_all(run_variant(private, root, log))
    assert kinds(evs) == ["step"] and evs[0]["subject_uri"] == OVERLAY_URI
    p = evs[0]["payload"]
    assert p["step"] == privacy.STEP_NOTICE_VARIANT and p["output"] == f"generated/notice-{VARIANT}.md"
    assert p["notice_variant"] == VARIANT and p["notice_version"] == "2026-11"
    text = (private / p["output"]).read_text(encoding="utf-8")
    assert f"Version {VARIANT}" in text and "<!--" not in text
    assert "## For residents of Fictional State" in text and "The categories of personal information" in text
    assert "Fictional overlay reason for twelve months." in text  # the overlay's own retention entry
    assert "Fictional notice sentence for the overlay" in text  # the overlay's purposes with their notice_text
    assert "Fictional: disclosed at collection" not in text  # and never the reason legal reads
    assert "The organisation is the controller" in text and "Who is responsible" in text  # the base notice is in it
    base = (private / "generated" / "notice-2026-11.md").read_text(encoding="utf-8")
    assert "Version 2026-11\n" in base and base != text  # the base notice is untouched
    assert run_variant(private, root, log + evs) == []  # unchanged: nothing appended


def test_the_variant_renders_the_base_retention_where_the_overlay_has_no_entry(root, private):
    log = with_delta_done(root, ready(private, root))
    evs = run_variant(private, root, log)
    text = (private / evs[0]["payload"]["output"]).read_text(encoding="utf-8")
    assert "Fictional reason for keeping performance-data that long." in text


def test_the_variant_is_blocked_until_each_precondition_holds(root, private):
    log = with_delta_done(root, ready(private, root))
    no_overlay = [e for e in log if e["payload"].get("step") != privacy.STEP_PROFILE_VERIFIED]
    assert "profile for US-CA is not verified" in reasons_of(run_variant(private, root, no_overlay))
    no_base_notice = [e for e in log if e["payload"].get("step") != setup.STEP_NOTICE_APPROVED]
    assert any("base notice" in r and "not approved" in r for r in reasons_of(run_variant(private, root, no_base_notice)))
    no_delta = [e for e in log if e["payload"].get("step") not in (privacy.STEP_DPIA_DELTA, privacy.STEP_DPIA_DELTA_CHECK)]
    assert any("DPIA delta" in r for r in reasons_of(run_variant(private, root, no_delta)))
    assert not (private / "generated" / f"notice-{VARIANT}.md").exists()


def test_the_variant_is_blocked_by_a_retention_breach_even_when_retention_check_once_passed(tmp_path, private):
    root = make_root(tmp_path, limits=LIMITS)
    log = ready(private, root)
    reasons = reasons_of(run_variant(private, root, with_delta_done(root, log)))
    assert any("performance-data" in r and "12-month maximum" in r for r in reasons)


def test_the_variant_needs_a_template_with_a_marker_for_every_overlay_element(root, private):
    log = with_delta_done(root, ready(private, root))
    tpl = root / "standards" / "templates" / "privacy-notice-us-ca.md"
    tpl.unlink()
    reasons = reasons_of(run_variant(private, root, log))
    assert any("privacy-notice-us-ca.md" in r for r in reasons)
    tpl.write_text("## No markers here\n\nSome text for $dpo_email.\n", encoding="utf-8", newline="\n")
    reasons = reasons_of(run_variant(private, root, log))
    assert reasons == ["notice template has no marker for mandatory element categories-collected "
                       "(<!-- element: categories-collected -->)"]
    tpl.write_text("<!-- element: categories-collected -->\n\n## Heading right after\n", encoding="utf-8", newline="\n")
    assert reasons_of(run_variant(private, root, log)) == ["section for mandatory element categories-collected renders empty"]
    tpl.write_text("<!-- element: categories-collected -->\nText $nonsense\n", encoding="utf-8", newline="\n")
    assert any("nonsense" in r for r in reasons_of(run_variant(private, root, log)))
    assert not (private / "generated" / f"notice-{VARIANT}.md").exists()


def test_the_variant_needs_a_proposed_basis_for_every_purpose_under_the_overlay(root, private):
    def drop(d):
        del d["purposes"][0]["proposed_basis"][OVERLAY_URI]

    edit_yaml(root / "standards" / "privacy" / "purposes.yaml", drop)  # before the verifications: purposes.yaml is covered
    log = with_delta_done(root, ready(private, root))
    reasons = reasons_of(run_variant(private, root, log))
    assert reasons == ["purpose tm:purpose/test-clearance has no proposed basis for tm:jurisdiction/us-ca"]


def test_the_variant_stays_blocked_while_decision_0005_is_open(root, private, tmp_path):
    log = with_delta_done(root, ready(private, root))
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "0005-x.md").write_text("---\nstatus: proposed\n---\n## Decision\nx\n", encoding="utf-8")
    reasons = reasons_of(run_variant(private, root, log, decisions_dir=d))
    assert any("0005" in r for r in reasons)


def test_a_signed_dpia_delta_also_unblocks_the_variant(tmp_path, private):
    root = make_root(tmp_path, triggers=[{"criterion": "ca-sell-or-share", "citation": "Fictional Act s.21"}])
    log = ready(private, root)
    log += run_delta(private, root, log)
    assert any("DPIA delta" in r for r in reasons_of(run_variant(private, root, log)))
    base_path, path = paths(root)
    signed = approval(privacy.STEP_DPIA_DELTA, privacy.dpia_delta_inputs(path, base_path, root), OVERLAY_URI)
    assert kinds(run_variant(private, root, log + [signed])) == ["step"]
    stale = approval(privacy.STEP_DPIA_DELTA, {"delta": [], "overlay_profile_sha256": "0" * 64,
                                              "base_profile_sha256": "1" * 64}, OVERLAY_URI)
    assert any("DPIA delta" in r for r in reasons_of(run_variant(private, root, log + [stale])))


# --- notice drafts: the base notice or the instructor's approved variant -------------------------------------------

import email  # noqa: E402
import email.policy  # noqa: E402
import shutil  # noqa: E402

from teachermodel.standards import ROOT  # noqa: E402

SME, PRO, CONTRACTOR, PARTNER = "tm:instructor/k7m2q", "tm:instructor/p3x9d", "tm:instructor/c5w1t", "tm:instructor/r8n4h"


def eml(private, uri):
    path = private / "generated" / "notice-drafts" / f"{uri.split('/', 1)[1]}.eml"
    return email.message_from_bytes(path.read_bytes(), policy=email.policy.default) if path.is_file() else None


def variant_approval(private, root, log, at="2026-10-24T11:00:00+00:00"):
    """Render the variant and return (log with its approval, the variant text)."""
    log = with_delta_done(root, log)
    evs = run_variant(private, root, log)
    assert kinds(evs) == ["step"], evs
    text = (private / evs[0]["payload"]["output"]).read_text(encoding="utf-8")
    base_path, path = paths(root)
    inputs = setup.variant_inputs(text, VARIANT, privacy.profile_inputs(base_path, root)["sha256"],
                                  privacy.profile_inputs(path, root)["sha256"], setup.retention_digest(root, log))
    return [*log, *evs, approval(privacy.STEP_VARIANT_APPROVED, inputs, OVERLAY_URI, at=at)], text


@pytest.fixture
def drafting(root, private, tmp_path):
    """A roster of an Irish SME engineer and professional, a Californian contractor and a German partner, with the base
    notice approved. Returns (private, root, log)."""
    roster = tmp_path / "roster-in.yaml"
    shutil.copy(ROOT / "standards" / "templates" / "roster.example.yaml", roster)
    log = setup.import_roster(private, roster, prerequisite_events(root), NOW, root=root)
    return private, root, [*log, *ready(private, root)]


def drafts(private, root, log):
    return check_all(setup.notice_drafts(private, log, SETTINGS, NOW, root=root))


def test_each_instructor_gets_the_notice_for_their_jurisdiction(drafting):
    private, root, log = drafting
    log, variant_text = variant_approval(private, root, log)
    evs = drafts(private, root, log)
    by = {e["subject_uri"]: e for e in evs if e["kind"] == "step"}
    assert set(by) == {SME, PRO, CONTRACTOR}
    assert {u: e["payload"]["notice_variant"] for u, e in by.items()} == {
        SME: "2026-11", PRO: "2026-11", CONTRACTOR: VARIANT}
    assert all(e["payload"]["notice_version"] == "2026-11" for e in by.values())
    assert eml(private, SME)["Subject"] == "Privacy notice: instructor development [tm-notice 2026-11]"
    ca = eml(private, CONTRACTOR)
    assert ca["Subject"] == f"Privacy notice: instructor development [tm-notice {VARIANT}]"
    assert variant_text in ca.get_body(("plain",)).get_content().replace("\r\n", "\n")
    assert "For residents of Fictional State" in ca.get_body(("plain",)).get_content() \
        and "Fictional State" not in eml(private, SME).get_body(("plain",)).get_content()
    assert by[CONTRACTOR]["payload"]["text_sha256"] == signoff_text_sha(variant_text)


def signoff_text_sha(text):
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_an_instructor_whose_jurisdiction_has_no_profile_gets_a_blocked_check_and_no_draft(drafting):
    private, root, log = drafting
    log, _ = variant_approval(private, root, log)
    evs = drafts(private, root, log)
    blocked = [e for e in evs if e["kind"] == "check" and e["subject_uri"] == PARTNER]
    assert len(blocked) == 1 and blocked[0]["payload"]["step"] == "tm:step/notice-drafts"
    assert blocked[0]["payload"]["reasons"] == ["no profile for DE"]
    assert eml(private, PARTNER) is None
    assert setup.notice_drafts(private, [*log, *evs], SETTINGS, NOW, root=root) == []  # reported once


def test_an_unapproved_variant_blocks_only_that_instructor_and_names_the_variant(drafting):
    private, root, log = drafting
    evs = drafts(private, root, log)  # the variant is neither rendered nor approved
    by_kind = {(e["kind"], e["subject_uri"]): e for e in evs}
    assert ("step", SME) in by_kind and ("step", PRO) in by_kind
    assert by_kind[("check", CONTRACTOR)]["payload"]["reasons"] == [f"notice variant {VARIANT} is not rendered"]
    assert eml(private, CONTRACTOR) is None and eml(private, SME) is not None
    log, _ = variant_approval(private, root, [*log, *evs])
    later = drafts(private, root, log)
    assert [(e["kind"], e["subject_uri"]) for e in later if e["subject_uri"] == CONTRACTOR] == [("step", CONTRACTOR)]
    assert not [e for e in later if e["subject_uri"] in (SME, PRO)]  # theirs are unchanged


def test_a_variant_that_is_rendered_but_not_approved_says_so(drafting):
    private, root, log = drafting
    log = with_delta_done(root, log)
    log += run_variant(private, root, log)
    reasons = {e["subject_uri"]: e["payload"]["reasons"] for e in drafts(private, root, log) if e["kind"] == "check"}
    assert reasons[CONTRACTOR] == [f"notice variant {VARIANT} is not approved"]


def test_a_variant_approval_of_other_bytes_does_not_count(drafting):
    private, root, log = drafting
    log, _ = variant_approval(private, root, log)
    base_path, path = paths(root)
    path.write_bytes(path.read_bytes() + b"# edited after the owner approved\n")
    reasons = {e["subject_uri"]: e["payload"]["reasons"] for e in drafts(private, root, log) if e["kind"] == "check"}
    assert reasons[CONTRACTOR] == [f"latest approval does not approve the current notice variant {VARIANT}"]


# --- the real California template -----------------------------------------------------------------------------


def test_the_real_us_ca_template_fills_a_section_for_every_element_of_the_real_profile():
    from string import Template

    from teachermodel import notice

    _, doc = privacy.overlay_profile("US-CA", ROOT)
    text = (ROOT / "standards" / "templates" / "privacy-notice-us-ca.md").read_text(encoding="utf-8")
    known = {"version", "dpo_email", "held", "purposes", "legitimate_interests", "separation", "recipients", "retention",
             "consent", "complaint", "overlay_purposes", "overlay_complaint"}
    assert Template(text).get_identifiers() and set(Template(text).get_identifiers()) <= known
    rendered = Template(text).substitute({k: f"text for {k}" for k in known})
    ids = [e["id"] for e in doc["notice_elements"]]
    problems = notice.element_problems(rendered, ids)
    assert ids and [p for p in problems if "draft" not in p.lower()] == []  # every element has a marker and a section
    assert any("draft" in p.lower() for p in problems)  # the real template is a draft, so it cannot be rendered yet
    assert "<!--" not in notice.strip_markers(rendered)
