"""Integration-review fixes 6 and 8: the notice says what the instructor is told (`notice_text`), never the reasoning
legal reads (`reason`), and it cannot be sent while any text in it is still a draft. Fictional fixtures only, except
the checks of the real standards."""

import shutil
from datetime import datetime, timezone

import yaml
from conftest import EXAMPLE_ROSTER_PATH
from privacy_helpers import STEP_DPIA, STEP_RETENTION, STEP_VERIFIED, add_overlay, sign_step
from test_privacy_overlay_workflow import tick, to_overlay, verify_overlay  # the world the overlay tests use

from teachermodel import app, notice, privacy, setup
from teachermodel.standards import ROOT, check_standards, validate

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
SETTINGS = {
    "schema": "tm:contract/settings@1", "library": "TeacherModel Private", "mailbox": "signoffs@example.com",
    "it_email": "it.requests@example.com", "dpo_email": "dpo@example.com", "notice_version": "2026-11",
}
BASE = "tm:jurisdiction/xx"
TEMPLATES = ("privacy-notice.md", "privacy-notice-us-ca.md")


def purposes_doc(**basis):
    return {"purposes": [{"id": "tm:purpose/a", "name": "Alpha", "description": "We do alpha.",
                          "proposed_basis": {BASE: {"basis": "legitimate-interests", **basis}}}]}


# --- 6: the notice prints notice_text, never reason --------------------------------------------------------


def test_the_purposes_contract_requires_notice_text_for_every_proposed_basis(privacy_root):
    doc = yaml.safe_load((privacy_root / privacy.PURPOSES_FILE).read_text(encoding="utf-8"))
    assert validate(doc, "purposes.schema.json") == []
    del doc["purposes"][0]["proposed_basis"][BASE]["notice_text"]
    assert any("notice_text" in e for e in validate(doc, "purposes.schema.json"))
    doc["purposes"][0]["proposed_basis"][BASE]["notice_text"] = ""
    assert validate(doc, "purposes.schema.json")


def test_purposes_md_prints_notice_text_and_not_the_reason():
    text, reasons = notice.purposes_md(purposes_doc(reason="LEGAL REASONING Art 6(1)(f)", notice_text="Plain words."), BASE)
    assert reasons == []
    assert "Plain words." in text and "LEGAL REASONING" not in text and "Art 6" not in text
    assert "Legal basis: legitimate interests" in text


def test_the_legitimate_interests_section_prints_notice_text_too():
    text = notice.legitimate_interests_md(purposes_doc(reason="LEGAL REASONING", notice_text="Plain words."), BASE)
    assert "Plain words." in text and "LEGAL REASONING" not in text


def test_the_record_of_processing_keeps_the_reason_for_legal(privacy_root):
    purposes = privacy.load_purposes(privacy_root)
    text = notice.purposes_ropa_md(purposes, {}, {BASE: "Fictionland"})
    reason = purposes["purposes"][0]["proposed_basis"][BASE]["reason"]
    assert reason in " ".join(text.split())


def test_no_reason_string_appears_in_a_rendered_notice_or_variant(fictional_store, privacy_root):
    add_overlay(privacy_root)
    purposes = privacy.load_purposes(privacy_root)
    reasons = [b["reason"] for p in purposes["purposes"] for b in p["proposed_basis"].values()]
    assert reasons and all(len(r) > 20 for r in reasons)
    for p in purposes["purposes"]:
        for b in p["proposed_basis"].values():
            assert b["notice_text"] not in reasons
    roster = fictional_store.parent / "roster-in.yaml"
    shutil.copy(EXAMPLE_ROSTER_PATH, roster)
    to_overlay(fictional_store, privacy_root, roster)
    verify_overlay(fictional_store, privacy_root)
    tick(fictional_store, privacy_root, hours=5)
    rendered = sorted((fictional_store / "generated").glob("notice-2026-11*.md"))
    assert len(rendered) == 2  # the base notice and the US-CA variant
    for path in rendered:
        text = " ".join(path.read_text(encoding="utf-8").split())
        for r in reasons:
            assert " ".join(r.split()) not in text, (path.name, r)
        assert "Fictional notice sentence" in text


def test_the_real_purposes_have_plain_notice_text_for_both_jurisdictions():
    doc = yaml.safe_load((ROOT / privacy.PURPOSES_FILE).read_text(encoding="utf-8"))
    assert validate(doc, "purposes.schema.json") == []
    for p in doc["purposes"]:
        assert set(p["proposed_basis"]) == {"tm:jurisdiction/ie", "tm:jurisdiction/us-ca"}, p["id"]
        for uri, b in p["proposed_basis"].items():
            assert b["notice_text"].strip() and b["notice_text"] != b["reason"], (p["id"], uri)
            assert "Art." not in b["notice_text"] and "1798." not in b["notice_text"], (p["id"], uri)


# --- 8: nothing renders while any text is still a draft ----------------------------------------------------


def test_a_draft_marker_is_a_problem():
    found = notice.draft_problems("Text.\n\n<!-- draft -->\nMore.\n")
    assert len(found) == 1 and "draft marker" in found[0]


def test_the_banner_line_is_a_draft_marker():
    text = "DRAFT for legal review. Do not send until counsel has reviewed it.\n\n# Notice\n"
    assert any("draft" in p.lower() for p in notice.draft_problems(text))


def test_a_to_be_placeholder_in_an_element_section_is_a_problem():
    text = "<!-- element: retention -->\nNo retention entries yet (to be set with legal advice).\n"
    problems = notice.element_problems(text, ["retention"])
    assert any("(to be " in p and "retention" in p for p in problems)


def test_a_finished_text_has_no_draft_problems():
    text = "# Notice\n\n<!-- element: retention -->\nWe keep records for 24 months.\n\nIt is to be read carefully.\n"
    assert notice.draft_problems(text) == []
    assert notice.element_problems(text, ["retention"]) == []


def test_strip_markers_removes_draft_markers_as_well():
    assert "draft" not in notice.strip_markers("A\n\n<!-- draft -->\nB\n")


def test_the_fixture_templates_are_finished(privacy_root):
    add_overlay(privacy_root)
    for name in TEMPLATES:
        text = (privacy_root / "standards" / "templates" / name).read_text(encoding="utf-8")
        assert notice.draft_problems(text) == [], name


def real_templates(root):
    for name in TEMPLATES:
        shutil.copy(ROOT / "standards" / "templates" / name, root / "standards" / "templates" / name)


def test_notice_text_is_blocked_on_a_template_that_is_still_a_draft(fictional_store, privacy_root):
    app.do_tick(fictional_store, now=NOW, root=privacy_root)
    for step in (STEP_VERIFIED, STEP_DPIA, STEP_RETENTION):
        sign_step(fictional_store, privacy_root, step)
    real_templates(privacy_root)
    st = app.load_state(fictional_store, privacy_root)
    (blocked,) = setup.notice_text(fictional_store, st.events, st.settings, NOW, root=privacy_root)
    assert blocked["kind"] == "check" and blocked["payload"]["result"] == "blocked"
    assert any("draft" in r.lower() for r in blocked["payload"]["reasons"]), blocked["payload"]["reasons"]
    assert not (fictional_store / "generated" / "notice-2026-11.md").exists()


def test_the_real_templates_still_carry_their_banner_and_draft_markers():
    for name in TEMPLATES:
        text = (ROOT / "standards" / "templates" / name).read_text(encoding="utf-8")
        assert notice.draft_problems(text), name


def test_validate_passes_on_the_real_standards_although_the_real_templates_are_drafts():
    assert check_standards(ROOT) == []
