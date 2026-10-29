"""tm:workflow/privacy-base: profile verification, DPIA, retention approval, notice (privacy-jurisdictions design
section 4). Fictional fixtures only: the fictional base profile `xx` and two fictional purposes, never the drafts."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from privacy_helpers import (
    cover_roster,
    LEGAL,
    PROGRAMME,
    ready_for_roster,
    STEP_DPIA,
    STEP_NOTICE_APPROVED,
    STEP_ROPA_APPROVED,
    STEP_RETENTION,
    STEP_VERIFIED,
    due_ids,
    edit_yaml,
    seed_check,
    sign_step,
    tm_data,
)

from teachermodel import app, privacy, setup
from teachermodel.standards import ROOT, load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
TODAY = T0.date()
LATER = T0 + timedelta(hours=2)
NOTICE = "generated/notice-2026-11.md"


def profile_path(root):
    return root / "standards" / "privacy" / "jurisdictions" / "xx.yaml"


def touch_profile(root, note="# edited after verification"):
    """Change the bytes of the base profile without changing what it says."""
    path = profile_path(root)
    path.write_bytes(path.read_bytes() + f"{note}\n".encode())


def tick(private, root, now=T0):
    return app.do_tick(private, now=now, root=root)


def steps_of(private, kind="step"):
    return [e["payload"].get("step") for e in app.read_events(private) if e["kind"] == kind]


def to_retention(private, root):
    """tick, legal verifies the profile, the DPO approves the ROPA and clears the DPIA, the head of training approves
    retention."""
    tick(private, root)
    sign_step(private, root, STEP_VERIFIED, at="2026-10-26T09:00:00+00:00")
    sign_step(private, root, STEP_ROPA_APPROVED, at="2026-10-26T09:02:00+00:00")
    sign_step(private, root, STEP_DPIA, at="2026-10-26T09:05:00+00:00")
    sign_step(private, root, STEP_RETENTION, at="2026-10-26T09:10:00+00:00")


def to_notice_text(private, root):
    to_retention(private, root)
    tick(private, root, now=T0 + timedelta(hours=1))
    assert (private / NOTICE).is_file()


@pytest.fixture
def world(fictional_store, privacy_root):
    return fictional_store, privacy_root


# --- the workflow definition -----------------------------------------------------------------------


def _steps():
    wf = load_standards()["workflows"]["workflows"]
    return {w["id"]: {s["id"]: s for s in w["steps"]} for w in wf}


def test_privacy_base_defines_the_steps_with_their_roles_and_bindings():
    steps = _steps()["tm:workflow/privacy-base"]
    assert set(steps) == {f"tm:step/{s}" for s in (
        "base-profile-verified", "ropa", "ropa-approved", "dpia-screening", "retention-approved", "notice-text", "notice-approved")}
    verified, ropa = steps[STEP_VERIFIED], steps["tm:step/ropa"]
    assert (verified["type"], verified["role"], verified["page"]) == ("human", "legal", "approve")
    assert verified["done_when"]["bind"] == "input" and verified["needs"] == []
    assert ropa["type"] == "auto" and ropa["role"] == "dpo"
    dpia = steps[STEP_DPIA]
    assert (dpia["role"], dpia["page"]) == ("dpo", "dpia_screening")
    approved = steps[STEP_ROPA_APPROVED]
    assert (approved["type"], approved["role"], approved["page"]) == ("human", "dpo", "approve")
    assert approved["needs"] == ["tm:step/ropa"] and approved["done_when"]["bind"] == "input"
    assert set(dpia["needs"]) == {STEP_ROPA_APPROVED, STEP_VERIFIED} and dpia["done_when"]["bind"] == "input"
    retention = steps[STEP_RETENTION]
    assert (retention["role"], retention["page"]) == ("head-of-training", "batch_approve")
    assert retention["done_when"]["bind"] == "input" and STEP_VERIFIED in retention["needs"]
    notice = steps[STEP_NOTICE_APPROVED]
    assert (notice["role"], notice["page"]) == ("programme-owner", "approve") and notice["done_when"]["bind"] == "input"
    assert steps["tm:step/notice-text"]["type"] == "auto" and STEP_RETENTION in steps["tm:step/notice-text"]["needs"]
    assert set(notice["needs"]) >= {"tm:step/notice-text", STEP_RETENTION}


def test_setup_lost_the_moved_steps_and_roster_import_waits_for_the_base_workflow():
    setup_steps = _steps()["tm:workflow/setup"]
    for gone in ("dpia-screening", "retention-periods", "notice-text", "notice-text-approved", "ropa"):
        assert f"tm:step/{gone}" not in setup_steps, gone
    assert set(setup_steps["tm:step/roster-import"]["needs"]) == {
        "tm:step/library-exists", STEP_VERIFIED, STEP_DPIA, STEP_RETENTION}
    assert set(setup_steps["tm:step/notice-drafts"]["needs"]) == {
        STEP_NOTICE_APPROVED, "tm:step/roster-import", "tm:step/variant-approved"}


# --- verification, then DPIA ----------------------------------------------------------------------


def test_the_first_tick_opens_the_profile_verification_for_legal_and_not_the_dpia(world):
    private, root = world
    tick(private, root)
    assert "tm:step/ropa" in steps_of(private)
    queue = app.do_next(private, now=T0, root=root).lines
    assert any(STEP_VERIFIED in line and " legal " in line for line in queue) and any("tm:step/it-done" in line for line in queue)
    assert not any(STEP_DPIA in line for line in queue)
    page = private / "pages" / "base-profile-verified--teachermodel--legal-1.html"
    data = tm_data(page)
    assert data["role"] == "legal" and data["template"] == "approve" and data["step"] == STEP_VERIFIED
    inputs = data["inputs"]
    assert inputs["profile"]["id"] == "tm:jurisdiction/xx" and inputs["file"].endswith("jurisdictions/xx.yaml")
    assert inputs["sha256"] == privacy.profile_inputs(profile_path(root), root)["sha256"]
    html = page.read_text(encoding="utf-8")
    assert "first verification" in html and "Fictional Data Protection Act" in html  # the sources are shown


def test_the_dpia_opens_only_after_the_profile_is_verified_and_the_ropa_approved(world):
    private, root = world
    tick(private, root)
    assert (STEP_DPIA, PROGRAMME) not in due_ids(private, root, TODAY)
    sign_step(private, root, STEP_VERIFIED)
    assert (STEP_DPIA, PROGRAMME) not in due_ids(private, root, TODAY)  # the ROPA is not approved yet
    assert (STEP_ROPA_APPROVED, PROGRAMME) in due_ids(private, root, TODAY)
    sign_step(private, root, STEP_ROPA_APPROVED)
    assert (STEP_DPIA, PROGRAMME) in due_ids(private, root, TODAY)
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, TODAY)
    assert (STEP_ROPA_APPROVED, PROGRAMME) not in due_ids(private, root, TODAY)


def test_the_ropa_approval_page_carries_the_generated_text_as_its_input(world):
    private, root = world
    tick(private, root)
    text = (private / "generated" / "ropa.md").read_text(encoding="utf-8")
    page = private / "pages" / "ropa-approved--teachermodel--dpo-1.html"
    data = tm_data(page)
    assert data["role"] == "dpo" and data["template"] == "approve" and data["step"] == STEP_ROPA_APPROVED
    assert data["inputs"] == {"ropa_text": text}
    assert [(f["name"], f["kind"], f["required"]) for f in data["fields"]] == [("note", "textarea", False)]
    assert "exact record of processing" in page.read_text(encoding="utf-8")


def test_editing_the_ropa_output_reopens_its_approval_and_holds_the_screening_back(world):
    private, root = world
    tick(private, root)
    sign_step(private, root, STEP_VERIFIED)
    sign_step(private, root, STEP_ROPA_APPROVED)
    due = due_ids(private, root, TODAY)
    assert (STEP_DPIA, PROGRAMME) in due and (STEP_ROPA_APPROVED, PROGRAMME) not in due
    # the ROPA output changes (in practice: the retention table is filled in, or the controller changes)
    ropa = private / "generated" / "ropa.md"
    ropa.write_text(ropa.read_text(encoding="utf-8") + "\nOne more line.\n", encoding="utf-8", newline="\n")
    due = due_ids(private, root, TODAY)
    assert (STEP_ROPA_APPROVED, PROGRAMME) in due
    assert (STEP_DPIA, PROGRAMME) not in due  # its need went stale with the approval
    sign_step(private, root, STEP_ROPA_APPROVED, at="2026-10-26T10:00:00+00:00")
    assert (STEP_DPIA, PROGRAMME) in due_ids(private, root, TODAY)


def test_a_signed_dpia_stays_done_when_the_ropa_approval_goes_stale(world):
    private, root = world
    tick(private, root)
    sign_step(private, root, STEP_VERIFIED)
    sign_step(private, root, STEP_ROPA_APPROVED)
    sign_step(private, root, STEP_DPIA)
    ropa = private / "generated" / "ropa.md"
    ropa.write_text(ropa.read_text(encoding="utf-8") + "\nOne more line.\n", encoding="utf-8", newline="\n")
    due = due_ids(private, root, TODAY)
    assert (STEP_ROPA_APPROVED, PROGRAMME) in due and (STEP_DPIA, PROGRAMME) not in due  # bound to its own inputs


def test_re_approving_the_ropa_reopens_the_dpia_screening(world):
    """The screening binds to the ROPA approval it was made against: a stale ROPA leaves it done (above), but the DPO's
    re-approval of a changed record of processing reopens it."""
    private, root = world
    tick(private, root)
    sign_step(private, root, STEP_VERIFIED)
    sign_step(private, root, STEP_ROPA_APPROVED)
    sign_step(private, root, STEP_DPIA)
    assert (STEP_DPIA, PROGRAMME) not in due_ids(private, root, TODAY)
    ropa = private / "generated" / "ropa.md"
    ropa.write_text(ropa.read_text(encoding="utf-8") + "\nOne more line.\n", encoding="utf-8", newline="\n")
    sign_step(private, root, STEP_ROPA_APPROVED, at="2026-10-26T10:00:00+00:00")
    due = due_ids(private, root, TODAY)
    assert (STEP_ROPA_APPROVED, PROGRAMME) not in due
    assert (STEP_DPIA, PROGRAMME) in due
    sign_step(private, root, STEP_DPIA, at="2026-10-26T11:00:00+00:00")
    assert (STEP_DPIA, PROGRAMME) not in due_ids(private, root, TODAY)


def test_the_dpia_page_cites_the_profile_trigger_beside_each_criterion(world):
    private, root = world

    def add_trigger(d):
        d["dpia_triggers"].append({"criterion": "evaluation-scoring", "citation": "Fictional Data Protection Act s.55"})

    edit_yaml(profile_path(root), add_trigger)
    tick(private, root)
    sign_step(private, root, STEP_VERIFIED)
    sign_step(private, root, STEP_ROPA_APPROVED)
    tick(private, root, now=LATER)
    data = tm_data(private / "pages" / "dpia-screening--teachermodel--dpo-1.html")
    fields = {f["name"]: f for f in data["fields"]}
    assert "Fictional Data Protection Act s.55" in fields["evaluation-scoring"]["help"]
    assert "Fictional Data Protection Act s.55" not in fields["large-scale"]["help"]
    # the programme's own answers stay: a trigger is a rule, not a fact about this processing
    assert fields["evaluation-scoring"]["value"] == "yes" and fields["large-scale"]["value"] == "no"
    # a trigger in free text (no criterion id) is ignored rather than guessed at
    assert all("Systematic evaluation or scoring of individuals" not in f["help"] for f in data["fields"])


# --- retention approval ----------------------------------------------------------------------------


def retention_spec(private, root):
    (spec,) = app.PAGE_SPECS[STEP_RETENTION](app.load_state(private, root), PROGRAMME)
    return spec


def test_the_retention_page_has_one_row_per_entry_and_is_bound_to_the_profile(world):
    private, root = world
    tick(private, root)
    sign_step(private, root, STEP_VERIFIED)
    sign_step(private, root, STEP_DPIA)
    spec = retention_spec(private, root)
    assert spec["template"] == "batch_approve" and spec["role"] == "head-of-training"
    rows = spec["inputs"]["rows"]
    assert len(rows) == 4 and len({r["key"] for r in rows}) == 4
    row = next(r for r in rows if r["key"].startswith("performance-data"))
    assert "24 months" in row["summary"] and "The engagement ends." in row["summary"]
    assert "Fictional reason for keeping performance-data that long." in row["summary"]
    assert "legitimate-interests" in row["summary"] and row["changed"] is True
    assert spec["inputs"]["base_profile_sha256"] == privacy.profile_inputs(profile_path(root), root)["sha256"]


def test_the_retention_page_is_refused_while_there_are_no_entries(tmp_path, fictional_store):
    from privacy_helpers import make_privacy_root

    root = make_privacy_root(tmp_path / "empty", entries="empty")
    tick(fictional_store, root)
    with pytest.raises(app.PageProblem, match="retention entries still empty"):
        app.PAGE_SPECS[STEP_RETENTION](app.load_state(fictional_store, root), PROGRAMME)


def test_the_retention_page_is_refused_while_a_pair_has_no_entry(world):
    private, root = world
    path = root / "standards" / "retention.yaml"
    edit_yaml(path, lambda d: d.__setitem__("entries", d["entries"][:-1]))
    tick(private, root)
    with pytest.raises(app.PageProblem, match="no base retention entry for delivery-data / tm:purpose/test-reuse"):
        app.PAGE_SPECS[STEP_RETENTION](app.load_state(private, root), PROGRAMME)
    # an entry that covers the pair only for an overlay does not cover the base population
    edit_yaml(path, lambda d: d["entries"].append({**d["entries"][0], "purpose": "tm:purpose/test-reuse",
                                                   "category": "delivery-data", "jurisdiction": "tm:jurisdiction/yy-aa"}))
    with pytest.raises(app.PageProblem, match="no base retention entry"):
        app.PAGE_SPECS[STEP_RETENTION](app.load_state(private, root), PROGRAMME)


def test_the_retention_page_is_refused_while_an_entry_breaks_a_verified_limit(world):
    private, root = world
    tick(private, root)
    edit_yaml(root / "standards" / "retention.yaml",
              lambda d: d["entries"][1].__setitem__("period_months", 61))  # performance-data: maximum 60
    # known-positive: the limit binds only a VERIFIED profile, so before legal signs the page still builds
    assert retention_spec(private, root)["inputs"]["rows"]
    sign_step(private, root, STEP_VERIFIED)
    with pytest.raises(app.PageProblem, match="61 months is above the 60-month maximum"):
        app.PAGE_SPECS[STEP_RETENTION](app.load_state(private, root), PROGRAMME)
    edit_yaml(root / "standards" / "retention.yaml", lambda d: d["entries"][1].__setitem__("period_months", 60))
    assert retention_spec(private, root)["inputs"]["rows"]  # the edge is within the limit


def test_a_retention_approval_goes_stale_when_an_entry_later_breaks_a_limit(world):
    private, root = world
    to_retention(private, root)
    assert (STEP_RETENTION, PROGRAMME) not in due_ids(private, root, TODAY)
    edit_yaml(root / "standards" / "retention.yaml", lambda d: d["entries"][1].__setitem__("period_months", 70))
    assert (STEP_RETENTION, PROGRAMME) in due_ids(private, root, TODAY)  # reopened, and no page can be built:
    rep = app.do_pages(private, now=LATER, root=root)
    assert any("problem" in line and "maximum" in line for line in rep.lines), rep.lines
    assert not list((private / "pages").glob("retention-approved--*.html"))


def test_roster_import_needs_verification_dpia_and_retention(world):
    private, root = world
    tick(private, root)
    seed_check(private, "tm:step/library-exists")
    importing = ("tm:step/roster-import", PROGRAMME)
    assert importing not in due_ids(private, root, TODAY)
    sign_step(private, root, STEP_VERIFIED, at="2026-10-26T09:00:00+00:00")
    assert importing not in due_ids(private, root, TODAY)
    sign_step(private, root, STEP_DPIA, at="2026-10-26T09:05:00+00:00")
    assert importing not in due_ids(private, root, TODAY)  # retention still unapproved
    sign_step(private, root, STEP_RETENTION, at="2026-10-26T09:10:00+00:00")
    assert importing in due_ids(private, root, TODAY)


# --- the chain reopens when the profile is edited ----------------------------------------------------


def test_editing_the_base_profile_reopens_verification_retention_and_the_notice(world):
    private, root = world
    to_notice_text(private, root)
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T10:00:00+00:00")
    due = due_ids(private, root, TODAY)
    assert not {(STEP_VERIFIED, PROGRAMME), (STEP_RETENTION, PROGRAMME), (STEP_NOTICE_APPROVED, PROGRAMME)} & due

    touch_profile(root)
    due = due_ids(private, root, TODAY)
    assert (STEP_VERIFIED, PROGRAMME) in due
    # blocked until re-verified: not done, and not due either
    assert (STEP_RETENTION, PROGRAMME) not in due and (STEP_NOTICE_APPROVED, PROGRAMME) not in due
    assert (STEP_DPIA, PROGRAMME) not in due  # the DPIA answers stay; only the bound approvals reopen

    sign_step(private, root, STEP_VERIFIED, at="2026-10-26T11:00:00+00:00")
    due = due_ids(private, root, TODAY)
    assert (STEP_RETENTION, PROGRAMME) in due  # its approval covered the old profile
    assert (STEP_NOTICE_APPROVED, PROGRAMME) not in due  # waits for retention in turn
    sign_step(private, root, STEP_RETENTION, at="2026-10-26T11:05:00+00:00")
    tick(private, root, now=T0 + timedelta(hours=3))  # the notice is rendered again against the retention in force now
    due = due_ids(private, root, TODAY)
    assert (STEP_NOTICE_APPROVED, PROGRAMME) in due and (STEP_RETENTION, PROGRAMME) not in due
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T11:10:00+00:00")
    assert not {(STEP_VERIFIED, PROGRAMME), (STEP_RETENTION, PROGRAMME), (STEP_NOTICE_APPROVED, PROGRAMME)} & due_ids(
        private, root, TODAY)


def test_a_changed_purpose_re_renders_the_notice_and_reopens_its_approval(world):
    private, root = world
    to_notice_text(private, root)
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T10:00:00+00:00")
    before = steps_of(private).count("tm:step/notice-text")
    edit_yaml(root / "standards" / "privacy" / "purposes.yaml",
              lambda d: d["purposes"][0].__setitem__("description", "A fictional new description of clearing."))
    assert (STEP_NOTICE_APPROVED, PROGRAMME) not in due_ids(private, root, TODAY)  # still the old text
    tick(private, root, now=T0 + timedelta(hours=3))
    # purposes.yaml is part of what legal verifies, so the edit reopened the verification: nothing renders until it holds
    assert (STEP_VERIFIED, PROGRAMME) in due_ids(private, root, TODAY)
    assert steps_of(private).count("tm:step/notice-text") == before
    sign_step(private, root, STEP_VERIFIED, at="2026-10-26T10:30:00+00:00")
    tick(private, root, now=T0 + timedelta(hours=4))
    assert steps_of(private).count("tm:step/notice-text") == before + 1
    assert "A fictional new description of clearing." in (private / NOTICE).read_text(encoding="utf-8")
    assert (STEP_NOTICE_APPROVED, PROGRAMME) in due_ids(private, root, TODAY)  # the owner approves the new text
    tick(private, root, now=T0 + timedelta(hours=5))
    assert steps_of(private).count("tm:step/notice-text") == before + 1  # a second run changes nothing


# --- the notice -------------------------------------------------------------------------------------


def test_the_notice_renders_from_purposes_retention_profile_and_0005(world):
    private, root = world
    to_notice_text(private, root)
    text = (private / NOTICE).read_text(encoding="utf-8")
    assert not any(line.startswith("DRAFT") for line in text.splitlines())  # a draft banner would have blocked it
    assert "<!--" not in text  # element markers are for the check, not for the reader
    # purposes: name, description and the proposed basis with its notice text (the reason is for legal, not the notice)
    assert "Clearance decisions" in text and "Deciding whether an instructor may teach a unit" in text
    assert "legitimate interests" in text
    assert "Fictional notice sentence for clearance." in text
    assert "The training function must be able to show that instructors were assessed before teaching." not in text
    assert "Reuse of a recording in teaching material" in text and "consent" in text
    assert "Fictional notice sentence for reuse. You can say no, with no consequence." in text
    assert "Optional: an instructor can say no with no consequence." not in text
    # retention: period, start and reason per entry
    assert "24 months" in text and "The engagement ends." in text
    assert "Fictional reason for keeping performance-data that long." in text
    # decision 0005 and the regulator named in the profile
    _, separation, _ = setup._decision(root / "docs" / "decisions", "0005")
    assert separation and separation in text
    assert "Fictional Data Protection Commission" in text and "https://example.test/regulator" in text
    # the retention table comes through the approved entries: nothing says "not set"
    assert "not set" not in text


def test_the_notice_is_blocked_until_the_profile_is_verified_and_retention_approved(world):
    private, root = world
    tick(private, root)
    st = app.load_state(private, root)
    reasons = setup.notice_text(private, st.events, st.settings, T0, root=root)[0]["payload"]["reasons"]
    assert "base profile not verified" in reasons and "retention not approved" in reasons
    assert not (private / NOTICE).exists()


def test_the_notice_is_blocked_while_retention_has_no_entries(tmp_path, fictional_store):
    from privacy_helpers import make_privacy_root

    root = make_privacy_root(tmp_path / "empty", entries="empty")
    tick(fictional_store, root)
    st = app.load_state(fictional_store, root)
    reasons = setup.notice_text(fictional_store, st.events, st.settings, T0, root=root)[0]["payload"]["reasons"]
    assert any("no retention entries" in r for r in reasons)


def test_the_notice_is_blocked_when_a_mandatory_element_has_no_marker(world):
    private, root = world
    tick(private, root)
    sign_step(private, root, STEP_VERIFIED)
    sign_step(private, root, STEP_DPIA)
    sign_step(private, root, STEP_RETENTION)
    template = root / "standards" / "templates" / "privacy-notice.md"
    text = template.read_text(encoding="utf-8")
    assert "<!-- element: retention -->" in text
    template.write_text(text.replace("<!-- element: retention -->\n", ""), encoding="utf-8")
    st = app.load_state(private, root)
    (ev,) = setup.notice_text(private, st.events, st.settings, T0, root=root)
    assert ev["kind"] == "check" and ev["payload"]["result"] == "blocked"
    assert any("retention" in r and "marker" in r for r in ev["payload"]["reasons"]), ev["payload"]["reasons"]
    assert not (private / NOTICE).exists()
    # known-positive: the unchanged template renders
    template.write_text(text, encoding="utf-8")
    assert setup.notice_text(private, st.events, st.settings, T0, root=root)[0]["kind"] == "step"


def test_the_notice_is_blocked_when_a_mandatory_section_renders_empty(world):
    private, root = world
    tick(private, root)
    for step in (STEP_VERIFIED, STEP_DPIA, STEP_RETENTION):
        sign_step(private, root, step)
    template = root / "standards" / "templates" / "privacy-notice.md"
    text = template.read_text(encoding="utf-8")
    assert "<!-- element: retention -->\n$retention" in text
    template.write_text(text.replace("<!-- element: retention -->\n$retention", "<!-- element: retention -->\n"),
                        encoding="utf-8")
    st = app.load_state(private, root)
    (ev,) = setup.notice_text(private, st.events, st.settings, T0, root=root)
    assert ev["kind"] == "check"
    assert any("retention" in r and "empty" in r for r in ev["payload"]["reasons"]), ev["payload"]["reasons"]


def test_the_notice_is_blocked_for_a_profile_element_the_template_does_not_carry(world):
    private, root = world

    def add_element(d):
        d["notice_elements"].append({"id": "ghost-element", "requirement": "Something new.", "citation": "s.99"})

    edit_yaml(profile_path(root), add_element)
    tick(private, root)
    for step in (STEP_VERIFIED, STEP_DPIA, STEP_RETENTION):
        sign_step(private, root, step)
    st = app.load_state(private, root)
    (ev,) = setup.notice_text(private, st.events, st.settings, T0, root=root)
    assert ev["kind"] == "check" and any("ghost-element" in r for r in ev["payload"]["reasons"])


def test_the_real_template_carries_a_marker_for_every_element_of_the_real_base_profile():
    template = (ROOT / "standards" / "templates" / "privacy-notice.md").read_text(encoding="utf-8")
    _, doc = privacy.base_profile(ROOT)
    for element in doc["notice_elements"]:
        assert f"<!-- element: {element['id']} -->" in template, element["id"]


def test_notice_drafts_need_the_approval_to_cover_the_current_profile(world, example_roster):
    private, root = world
    cover_roster(root)  # one notice for every instructor of the example roster
    to_notice_text(private, root)
    seed_check(private, "tm:step/library-exists")
    app.do_import_roster(private, example_roster, now=T0, root=root)
    sign_step(private, root, STEP_NOTICE_APPROVED, at="2026-10-26T10:00:00+00:00")
    st = app.load_state(private, root)
    drafts = setup.notice_drafts(private, st.events, st.settings, T0, root=root)
    assert [e["kind"] for e in drafts] == ["step"] * 4
    touch_profile(root)
    blocked = setup.notice_drafts(private, st.events, st.settings, LATER, root=root)
    assert blocked and all(e["kind"] == "check" for e in blocked)


# --- base codes reach the engine ---------------------------------------------------------------------


def test_the_base_profiles_codes_decide_which_jurisdictions_get_a_subject(world, example_roster):
    private, root = world
    ready_for_roster(private, root)
    app.do_import_roster(private, example_roster, now=T0, root=root)
    jurisdictions = lambda st: {u for u, i in st.subjects.items() if i["kind"] == "jurisdiction"}  # noqa: E731
    # the fictional base covers XX only: the roster's IE, US-CA and DE are all overlay subjects
    assert jurisdictions(app.load_state(private, root)) == {
        "tm:jurisdiction/ie", "tm:jurisdiction/us-ca", "tm:jurisdiction/de"}
    # the real base is Ireland
    assert jurisdictions(app.load_state(private)) == {"tm:jurisdiction/us-ca", "tm:jurisdiction/de"}


def test_load_state_names_a_missing_base_profile(world):
    private, root = world
    profile_path(root).unlink()
    with pytest.raises(app.AppError, match="no base profile"):
        app.load_state(private, root)


# --- ingest keeps what a bound sign-off covered, so the next review can show a diff -------------------


def receipt_for(private, page_name, sender, *, sid, now=T0):
    page = tm_data(private / "pages" / page_name)
    doc = {
        "schema": "tm:contract/signoff@1", "id": sid, "step": page["step"], "subject_uri": page["subject_uri"],
        "input_sha256": page["input_sha256"], "decision": "approve", "fields": {}, "signer": page["signer"],
        "signed_at": (now + timedelta(minutes=30)).isoformat(),
        "page_template_sha256": page["page_template_sha256"],
    }
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    (tagged,) = [o for o in plan["ops"] if o["op"] == "mail.tagged"]
    msg = {"sender": sender, "subject": f"[tm-signoff {sid}]", "received": (now + timedelta(minutes=40)).isoformat(),
           "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]}
    receipt = {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": (private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
        "driver": "fixture", "run_at": (now + timedelta(hours=1)).isoformat(),
        "results": [{"op_id": tagged["op_id"], "status": "ok", "data": {"messages": [msg]}}],
    }
    path = private / "receipts" / f"{sid}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_an_accepted_profile_verification_keeps_its_inputs_and_the_next_page_shows_the_diff(world):
    private, root = world
    tick(private, root)
    sid = "1234567890abcdef"
    rep = app.do_ingest(private, receipt_for(private, "base-profile-verified--teachermodel--legal-1.html", LEGAL,
                                             sid=sid), now=LATER, allowed_drivers=("fixture",), root=root)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary
    kept = json.loads((private / "signoffs" / f"{sid}.inputs.json").read_text(encoding="utf-8"))
    assert kept["step"] == STEP_VERIFIED and kept["inputs"]["profile"]["id"] == "tm:jurisdiction/xx"
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, TODAY)

    # a later edit: the verification reopens and its page shows what changed since the verified version
    edit_yaml(profile_path(root), lambda d: d["laws"][0].__setitem__("name", "Fictional Data Protection Act 2027"))
    tick(private, root, now=T0 + timedelta(days=1))
    html = (private / "pages" / "base-profile-verified--teachermodel--legal-1.html").read_text(encoding="utf-8")
    assert "first verification" not in html
    assert "@@" in html and "+  - name: Fictional Data Protection Act 2027" in html
    assert "-  - name: Fictional Data Protection Act" in html


def test_only_bound_steps_keep_their_inputs(world):
    private, root = world
    tick(private, root)
    sid = "fedcba0987654321"
    app.do_ingest(private, receipt_for(private, "it-done--teachermodel--it-1.html", "pat.it@example.com", sid=sid),
                  now=LATER, allowed_drivers=("fixture",), root=root)
    assert (private / "signoffs" / f"{sid}.json").is_file()
    assert not (private / "signoffs" / f"{sid}.inputs.json").exists()


def test_every_human_step_of_the_base_workflow_has_a_page_builder():
    human = {sid for sid, s in _steps()["tm:workflow/privacy-base"].items() if s["type"] == "human"}
    assert human == {STEP_VERIFIED, STEP_ROPA_APPROVED, STEP_DPIA, STEP_RETENTION, STEP_NOTICE_APPROVED}
    assert human <= set(app.PAGE_SPECS)


def test_the_ropa_lists_purposes_with_their_bases_and_the_retention_table(world):
    private, root = world
    tick(private, root)
    ropa = (private / "generated" / "ropa.md").read_text(encoding="utf-8")
    assert "Clearance decisions" in ropa and "Reuse of a recording in teaching material" in ropa
    assert "tm:jurisdiction/xx" in ropa and "legitimate interests" in ropa
    assert "Fictional reason for keeping performance-data that long." in ropa and "24 months" in ropa
    assert "Fictional Data Protection Act" in ropa  # the base profile's law, in the lawful-basis section
