"""Drive generated sign-off pages in headless chromium and feed the download to `signoff.accept`.

Skipped cleanly when playwright or its chromium build is missing:
    py -m pip install -e ".[browser]"
    py -m playwright install chromium
Inputs are fictional (decision 0003).
"""

from __future__ import annotations

import email
import functools
import http.server
import json
import threading
from email import policy

import pytest
from jsonschema import Draft202012Validator

from teachermodel import pages, signoff
from teachermodel.standards import load_schema, load_standards

pytestmark = pytest.mark.browser

sync_api = pytest.importorskip("playwright.sync_api", reason="playwright not installed (pip install -e '.[browser]')")

HINT = "run `py -m playwright install chromium`"
STD = load_standards()
MAIL = {"kind": "mail", "to": "programme@example.test"}
INSTRUCTOR = "tm:instructor/example-a"
INSTRUCTOR_EMAIL = "example.a@example.test"
IT_PERSON = "tm:person/example-it"
IT_EMAIL = "example.it@example.test"
DPO_PERSON = "tm:person/example-dpo"
DPO_EMAIL = "example.dpo@example.test"
OWNER_PERSON = "tm:person/example-owner"
OWNER_EMAIL = "example.owner@example.test"
IDS = {
    INSTRUCTOR_EMAIL: [{"uri": INSTRUCTOR, "roles": {"instructor"}}],
    IT_EMAIL: [{"uri": IT_PERSON, "roles": {"it"}}],
    DPO_EMAIL: [{"uri": DPO_PERSON, "roles": {"dpo"}}],
    OWNER_EMAIL: [{"uri": OWNER_PERSON, "roles": {"programme-owner"}}],
}


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except Exception as exc:  # missing browser build, sandbox failure, ...
            pytest.skip(f"chromium cannot launch ({str(exc).splitlines()[0]}); {HINT}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(accept_downloads=True)
    pg = ctx.new_page()
    yield pg
    ctx.close()


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture
def serve(tmp_path):
    handler = functools.partial(_Quiet, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _render(tmp_path, stem, template, **kw):
    html, digest = pages.render(template, channel=MAIL, **kw)
    _, sidecar = pages.write_page(tmp_path, stem, html, kw["inputs"])
    return digest, sidecar


def _self_assessment(tmp_path):
    inputs = {"instructor": INSTRUCTOR, "framework_version": STD["framework"]["version"]}
    digest, sidecar = _render(
        tmp_path, "self-assessment", "self_assessment",
        step="tm:step/baseline-self-assessment", subject_uri=INSTRUCTOR, signer=INSTRUCTOR,
        role="instructor", inputs=inputs, fields=pages.self_assessment_fields(STD),
        title="Baseline self-assessment", intro="Rate yourself honestly.",
    )
    return digest, sidecar


def _approve(tmp_path):
    inputs = {"library": "Example Library", "group": "example-group", "sharing_links": "none"}
    digest, sidecar = _render(
        tmp_path, "it-done", "approve",
        step="tm:step/it-done", subject_uri="tm:programme/teachermodel", signer=IT_PERSON,
        role="it", inputs=inputs,
        fields=[
            {"name": "note", "label": "Note", "kind": "textarea", "required": False},
            {"name": "attested", "label": "Permissions are set as requested", "kind": "bool", "required": True},
        ],
        title="IT done", intro="Confirm the library is set up.",
    )
    return digest, sidecar


def _save_and_read(page, tmp_path):
    """Save, open the mail channel's draft as a mail client would, and return the sign-off file attached to it."""
    with page.expect_download(timeout=5000) as dl:
        page.click("#tm-save")
    assert dl.value.suggested_filename.endswith(".eml")
    path = tmp_path / "downloaded.eml"
    dl.value.save_as(path)
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    files = list(msg.iter_attachments())
    assert len(files) == 1 and msg["To"] == MAIL["to"] and msg["X-Unsent"] == "1"
    doc = json.loads(files[0].get_payload(decode=True).decode("utf-8"))
    assert msg["Subject"] == f"[tm-signoff {doc['id']}]" and files[0].get_filename().endswith(f"{doc['id']}.json")
    with page.expect_download(timeout=5000) as alone:  # the file alone, for a client that does not open the draft
        page.click("#tm-json")
    alone_path = tmp_path / "alone.json"
    alone.value.save_as(alone_path)
    assert alone_path.read_bytes() == files[0].get_payload(decode=True)
    return doc


def _assert_valid(doc):
    errors = [e.message for e in Draft202012Validator(load_schema("signoff.schema.json")).iter_errors(doc)]
    assert errors == []


def test_self_assessment_download_is_accepted(page, serve, tmp_path):
    digest, sidecar = _self_assessment(tmp_path)
    page.goto(f"{serve}/self-assessment.html")
    for dom in STD["framework"]["domains"]:
        page.check(f"#f-{dom['id']}-3")
    doc = _save_and_read(page, tmp_path)

    _assert_valid(doc)
    assert doc["decision"] == "record"
    assert doc["step"] == "tm:step/baseline-self-assessment"
    assert set(doc["fields"]) == {d["id"] for d in STD["framework"]["domains"]}
    assert all(v == 3 for v in doc["fields"].values())

    current = signoff.input_sha256(json.loads(sidecar.read_text(encoding="utf-8")))
    assert current == digest
    result = signoff.accept(
        doc, current_input_sha256=current, sender_email=INSTRUCTOR_EMAIL, identities=IDS,
        step_role="instructor", expected_signer=INSTRUCTOR,
    )
    assert result.accepted and result.reasons == [] and not result.duplicate
    assert page.is_visible("#tm-status")


def test_self_assessment_missing_score_blocks_download(page, serve, tmp_path):
    _self_assessment(tmp_path)
    page.goto(f"{serve}/self-assessment.html")
    domains = [d["id"] for d in STD["framework"]["domains"]]
    for dom in domains[1:]:  # leave the first required score empty
        page.check(f"#f-{dom}-2")
    with pytest.raises(sync_api.TimeoutError):
        with page.expect_download(timeout=1500):
            page.click("#tm-save")
    assert page.is_visible("#tm-errors")
    assert "required" in page.inner_text("#tm-errors")
    assert STD["framework"]["domains"][0]["name"] in page.inner_text("#tm-errors")
    assert not page.is_visible("#tm-status")


def test_approve_download_is_accepted(page, serve, tmp_path):
    digest, sidecar = _approve(tmp_path)
    page.goto(f"{serve}/it-done.html")
    page.check("#f-attested")
    page.select_option("#tm-decision", "approve")
    doc = _save_and_read(page, tmp_path)

    _assert_valid(doc)
    assert doc["decision"] == "approve"
    assert doc["fields"]["attested"] is True

    current = signoff.input_sha256(json.loads(sidecar.read_text(encoding="utf-8")))
    assert current == digest
    result = signoff.accept(
        doc, current_input_sha256=current, sender_email=IT_EMAIL, identities=IDS,
        step_role="it", expected_signer=IT_PERSON,
    )
    assert result.accepted and result.reasons == []


def test_review_ticks_and_answers_survive_a_reload_until_cleared(page, serve, tmp_path):
    """Legal and IT, 2026-10-26: a reviewer can stop and come back; the page keeps their ticks and answers."""
    _approve(tmp_path)
    page.goto(f"{serve}/it-done.html")
    assert page.inner_text("#tm-progress-text").startswith("Reviewed 0 of 1 sections.")
    page.check("[data-review='part-summary']")
    page.fill("#f-note", "half done")
    page.select_option("#tm-decision", "changes")
    page.reload()
    assert page.is_checked("[data-review='part-summary']")
    assert page.input_value("#f-note") == "half done" and page.input_value("#tm-decision") == "changes"
    assert page.inner_text("#tm-progress-text").startswith("Reviewed 1 of 1 sections.")
    page.click("#tm-clear")
    page.wait_for_load_state()
    assert not page.is_checked("[data-review='part-summary']") and page.input_value("#f-note") == ""


def test_approve_without_decision_blocks_download(page, serve, tmp_path):
    _approve(tmp_path)
    page.goto(f"{serve}/it-done.html")
    page.check("#f-attested")  # decision left unchosen
    with pytest.raises(sync_api.TimeoutError):
        with page.expect_download(timeout=1500):
            page.click("#tm-save")
    assert "Decision: required" in page.inner_text("#tm-errors")


# --- DPIA screening: the decision is derived from the DPO's answer ----------------------------------


def _dpia(tmp_path):
    inputs = {"purpose": "Instructor clearance and coaching", "categories": ["identity reference", "scores"]}
    return _render(
        tmp_path, "dpia", "dpia_screening",
        step="tm:step/dpia-screening", subject_uri="tm:programme/teachermodel", signer=DPO_PERSON,
        role="dpo", inputs=inputs, fields=pages.dpia_fields(), title="DPIA screening", intro="Screen the processing.",
    )


@pytest.mark.parametrize("answer, decision, completes", [
    ("dpia-not-required", "approve", True),
    ("dpia-required", "changes", False),
    ("needs-more-information", "changes", False),
])
def test_dpia_decision_follows_the_dpo_answer(page, serve, tmp_path, answer, decision, completes):
    digest, _ = _dpia(tmp_path)
    page.goto(f"{serve}/dpia.html")
    page.select_option("#f-dpo-decision", answer)
    page.fill("#f-rationale", "Fictional rationale.")
    doc = _save_and_read(page, tmp_path)

    _assert_valid(doc)
    assert doc["decision"] == decision and doc["fields"]["dpo-decision"] == answer
    result = signoff.accept(
        doc, current_input_sha256=digest, sender_email=DPO_EMAIL, identities=IDS, step_role="dpo",
    )
    assert result.accepted
    # what ingest additionally requires before the sign-off can complete the step
    approving = doc["decision"] in ("approve", "record")
    assert (approving and signoff.content_reasons(doc) == []) is completes


def test_dpia_without_a_dpo_decision_blocks_download(page, serve, tmp_path):
    _dpia(tmp_path)
    page.goto(f"{serve}/dpia.html")
    page.fill("#f-rationale", "Fictional rationale.")
    with pytest.raises(sync_api.TimeoutError):
        with page.expect_download(timeout=1500):
            page.click("#tm-save")
    assert "DPO decision: required" in page.inner_text("#tm-errors")


# --- batch approval: Approve needs every row approved ----------------------------------------------

ROWS = [
    {"key": "row-a", "summary": "Changed row A", "changed": True},
    {"key": "row-b", "summary": "Changed row B", "changed": True},
    {"key": "row-c", "summary": "Unchanged row C", "changed": False},
]


def _batch(tmp_path):
    return _render(
        tmp_path, "batch", "batch_approve",
        step="tm:step/gap-list-approved", subject_uri="tm:programme/teachermodel", signer=OWNER_PERSON,
        role="programme-owner", inputs={"rows": ROWS}, fields=[], title="Gap list", intro="Decide each changed row.",
    )


def _no_download(page):
    with pytest.raises(sync_api.TimeoutError):
        with page.expect_download(timeout=1500):
            page.click("#tm-save")


def test_batch_approve_with_a_rejected_row_blocks_download(page, serve, tmp_path):
    _batch(tmp_path)
    page.goto(f"{serve}/batch.html")
    page.check('[data-row="0"] input[value="approve"]')
    page.check('[data-row="1"] input[value="reject"]')
    page.check("#tm-approve-unchanged")
    page.select_option("#tm-decision", "approve")
    _no_download(page)
    assert "needs every row approved" in page.inner_text("#tm-errors")


def test_batch_approve_with_unreviewed_unchanged_rows_blocks_download(page, serve, tmp_path):
    _batch(tmp_path)
    page.goto(f"{serve}/batch.html")
    page.check('[data-row="0"] input[value="approve"]')
    page.check('[data-row="1"] input[value="approve"]')
    page.select_option("#tm-decision", "approve")  # the unchanged row was never approved
    _no_download(page)
    assert "needs every row approved" in page.inner_text("#tm-errors")


def test_batch_approve_with_every_row_approved_is_accepted(page, serve, tmp_path):
    digest, _ = _batch(tmp_path)
    page.goto(f"{serve}/batch.html")
    page.check('[data-row="0"] input[value="approve"]')
    page.check('[data-row="1"] input[value="approve"]')
    page.check("#tm-approve-unchanged")
    page.select_option("#tm-decision", "approve")
    doc = _save_and_read(page, tmp_path)
    _assert_valid(doc)
    assert doc["fields"]["rows"] == {"row-a": "approve", "row-b": "approve", "row-c": "approve"}
    assert signoff.content_reasons(doc, {"row-a", "row-b", "row-c"}) == []
    assert signoff.accept(doc, current_input_sha256=digest, sender_email=OWNER_EMAIL, identities=IDS,
                          step_role="programme-owner").accepted


def test_batch_request_changes_may_carry_rejected_rows(page, serve, tmp_path):
    _batch(tmp_path)
    page.goto(f"{serve}/batch.html")
    page.check('[data-row="0"] input[value="approve"]')
    page.check('[data-row="1"] input[value="reject"]')
    page.select_option("#tm-decision", "changes")
    doc = _save_and_read(page, tmp_path)
    assert doc["decision"] == "changes" and doc["fields"]["rows"]["row-b"] == "reject"
    assert doc["fields"]["rows"]["row-c"] == "unreviewed"
    assert signoff.content_reasons(doc) == []  # not approving, so nothing to check: it completes nothing


# --- evidence_score, checklist and number (increment 2 field kinds) -----------------------------------------

OBSERVER_PERSON = "tm:instructor/example-obs"
OBSERVER_EMAIL = "example.obs@example.test"
CLEARER_PERSON = "tm:person/example-clearer"
CLEARER_EMAIL = "example.clearer@example.test"
IDS_NEW = {
    OBSERVER_EMAIL: [{"uri": OBSERVER_PERSON, "roles": {"observer-in-training"}}],
    CLEARER_EMAIL: [{"uri": CLEARER_PERSON, "roles": {"clearer"}}],
}
DOMAINS = [d["id"] for d in STD["framework"]["domains"]]


def _evidence(tmp_path):
    return _render(
        tmp_path, "observe", "approve",
        step="tm:step/observe", subject_uri="tm:assignment/0123456789abcdef", signer=OBSERVER_PERSON,
        role="observer-in-training", inputs={"unit": "sl:unit/example-agent-loop@1"},
        fields=pages.evidence_score_fields(STD), title="Observation", intro="Score what you saw.",
    )


def _answer_all_domains(page, skip=None, note_skip=None):
    for dom in DOMAINS:
        if dom == skip:
            continue
        page.check(f"#f-{dom}-3")
        if dom != note_skip:
            page.fill(f"#f-{dom}-note", f"Evidence for {dom}.")


def test_evidence_score_save_produces_score_note_and_timestamp(page, serve, tmp_path):
    digest, _ = _evidence(tmp_path)
    page.goto(f"{serve}/observe.html")
    _answer_all_domains(page)
    page.fill(f"#f-{DOMAINS[0]}-ts", "12:30")
    page.select_option("#tm-decision", "approve")
    doc = _save_and_read(page, tmp_path)

    _assert_valid(doc)
    assert set(doc["fields"]) == set(DOMAINS)
    assert doc["fields"][DOMAINS[0]] == {"score": 3, "note": f"Evidence for {DOMAINS[0]}.", "timestamp": "12:30"}
    assert doc["fields"][DOMAINS[1]] == {"score": 3, "note": f"Evidence for {DOMAINS[1]}."}  # no timestamp key
    assert signoff.accept(doc, current_input_sha256=digest, sender_email=OBSERVER_EMAIL, identities=IDS_NEW,
                          step_role="observer-in-training").accepted


def test_evidence_score_without_its_note_blocks_download(page, serve, tmp_path):
    _evidence(tmp_path)
    page.goto(f"{serve}/observe.html")
    _answer_all_domains(page, note_skip=DOMAINS[1])
    page.select_option("#tm-decision", "approve")
    _no_download(page)
    text = page.inner_text("#tm-errors")
    assert "evidence note required" in text and STD["framework"]["domains"][1]["name"] in text


def test_evidence_score_note_without_a_score_blocks_download(page, serve, tmp_path):
    _evidence(tmp_path)
    page.goto(f"{serve}/observe.html")
    _answer_all_domains(page, skip=DOMAINS[0])
    page.fill(f"#f-{DOMAINS[0]}-note", "A note but no score.")
    page.select_option("#tm-decision", "approve")
    _no_download(page)
    assert "choose a score" in page.inner_text("#tm-errors")


def test_required_evidence_score_left_empty_blocks_download(page, serve, tmp_path):
    _evidence(tmp_path)
    page.goto(f"{serve}/observe.html")
    _answer_all_domains(page, skip=DOMAINS[0])
    page.select_option("#tm-decision", "approve")
    _no_download(page)
    assert "required" in page.inner_text("#tm-errors")


def _checklist(tmp_path):
    fields = [
        {"name": "preflight", "label": "Preflight", "kind": "checklist", "required": True, "items": [
            {"id": "keys-scoped", "label": "API keys are scoped"}, {"id": "model-pinned", "label": "Model is pinned"}]},
        {"name": "minutes", "label": "Minutes over plan", "kind": "number", "required": False, "min": 0, "max": 60},
    ]
    return _render(
        tmp_path, "dry-run", "approve",
        step="tm:step/dry-run", subject_uri="tm:candidate/example-a--example-agent-loop-1--remote",
        signer=CLEARER_PERSON, role="clearer", inputs={"unit": "sl:unit/example-agent-loop@1"}, fields=fields,
        title="Dry run", intro="Walk the checklist.",
    )


def test_checklist_save_produces_result_and_note_per_item(page, serve, tmp_path):
    digest, _ = _checklist(tmp_path)
    page.goto(f"{serve}/dry-run.html")
    page.check("#f-preflight-keys-scoped-pass")
    page.check("#f-preflight-model-pinned-fail")
    page.fill("#f-preflight-model-pinned-note", "Pinned to the alias, not a version.")
    page.fill("#f-minutes", "7.5")
    page.select_option("#tm-decision", "changes")
    doc = _save_and_read(page, tmp_path)

    _assert_valid(doc)
    assert doc["fields"]["preflight"] == {
        "keys-scoped": {"result": "pass", "note": ""},
        "model-pinned": {"result": "fail", "note": "Pinned to the alias, not a version."},
    }
    assert doc["fields"]["minutes"] == 7.5 and isinstance(doc["fields"]["minutes"], float)
    assert signoff.accept(doc, current_input_sha256=digest, sender_email=CLEARER_EMAIL, identities=IDS_NEW,
                          step_role="clearer").accepted


def test_checklist_failed_item_without_a_note_blocks_download(page, serve, tmp_path):
    _checklist(tmp_path)
    page.goto(f"{serve}/dry-run.html")
    page.check("#f-preflight-keys-scoped-pass")
    page.check("#f-preflight-model-pinned-fail")  # no note
    page.select_option("#tm-decision", "changes")
    _no_download(page)
    assert "note required for a failed item" in page.inner_text("#tm-errors")


def test_checklist_with_an_unanswered_item_blocks_download(page, serve, tmp_path):
    _checklist(tmp_path)
    page.goto(f"{serve}/dry-run.html")
    page.check("#f-preflight-keys-scoped-pass")  # the second item is left open
    page.select_option("#tm-decision", "approve")
    _no_download(page)
    assert "Model is pinned: choose pass or fail" in page.inner_text("#tm-errors")


def test_required_checklist_left_empty_blocks_download(page, serve, tmp_path):
    _checklist(tmp_path)
    page.goto(f"{serve}/dry-run.html")
    page.select_option("#tm-decision", "approve")
    _no_download(page)
    assert "Preflight: required" in page.inner_text("#tm-errors")


@pytest.mark.parametrize("typed, message", [("sixty", "enter a number"), ("61", "at most 60"), ("-1", "at least 0")])
def test_number_out_of_range_or_not_a_number_blocks_download(page, serve, tmp_path, typed, message):
    _checklist(tmp_path)
    page.goto(f"{serve}/dry-run.html")
    page.check("#f-preflight-keys-scoped-pass")
    page.check("#f-preflight-model-pinned-pass")
    page.fill("#f-minutes", typed) if typed.lstrip("-").replace(".", "").isdigit() else page.evaluate(
        "v => { const el = document.getElementById('f-minutes'); el.type = 'text'; el.value = v; }", typed)
    page.select_option("#tm-decision", "approve")
    _no_download(page)
    assert message in page.inner_text("#tm-errors")


def test_number_left_empty_is_omitted(page, serve, tmp_path):
    _checklist(tmp_path)
    page.goto(f"{serve}/dry-run.html")
    page.check("#f-preflight-keys-scoped-pass")
    page.check("#f-preflight-model-pinned-pass")
    page.select_option("#tm-decision", "approve")
    doc = _save_and_read(page, tmp_path)
    assert "minutes" not in doc["fields"] and set(doc["fields"]) == {"preflight"}
