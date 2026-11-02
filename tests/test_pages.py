import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from teachermodel import mdlite, pages
from teachermodel.signoff import input_sha256
from teachermodel.standards import PAGE_TEMPLATES, load_standards

SNAPSHOTS = Path(__file__).parent / "snapshots"
STD = load_standards()

LIBRARY = {"kind": "library", "path": "Instructor Development Library/inbox"}
MAIL = {"kind": "mail", "to": "programme@example.test"}

# Fictional inputs only (decision 0003): no real people, no real recipients.
CASES = {
    "approve": dict(
        step="tm:step/it-done",
        subject_uri="tm:programme/teachermodel",
        signer="tm:person/example-it",
        role="it",
        inputs={"library": "Instructor Development Library", "group": "example-group", "sharing_links": "none"},
        fields=[
            {"name": "note", "label": "Note", "kind": "textarea", "required": False, "help": "Optional."},
            {"name": "attested", "label": "Permissions are set as requested", "kind": "bool", "required": True},
        ],
        channel=MAIL,
        title="IT done: confirm the library is set up",
        intro="Confirm the library, group and permissions match the request.",
    ),
    "self_assessment": dict(
        step="tm:step/baseline-self-assessment",
        subject_uri="tm:instructor/example-a",
        signer="tm:instructor/example-a",
        role="instructor",
        inputs={"instructor": "tm:instructor/example-a", "framework_version": STD["framework"]["version"]},
        fields=pages.self_assessment_fields(STD),
        channel=MAIL,
        title="Baseline self-assessment",
        intro="Rate yourself honestly.\n\nNothing here decides your level.",
    ),
    "dpia_screening": dict(
        step="tm:step/dpia-screening",
        subject_uri="tm:programme/teachermodel",
        signer="tm:person/example-dpo",
        role="dpo",
        inputs={
            "purpose": "Instructor clearance and coaching",
            "data_subjects": "Instructors (employees and partner staff)",
            "categories": ["identity reference", "observation scores", "clearance level"],
        },
        fields=pages.dpia_fields(),
        channel=MAIL,
        title="DPIA screening",
        intro="Screen the programme's processing.",
    ),
    "batch_approve": dict(
        step="tm:step/gap-list-approved",
        subject_uri="tm:programme/teachermodel",
        signer="tm:person/example-owner",
        role="programme-owner",
        inputs={
            "list": "Gap list",
            "rows": [
                {"key": "tm:instructor/example-a|sl:unit/example-agent-loop@1", "summary": "No clearance on file", "changed": True},
                {"key": "tm:instructor/example-b|sl:unit/example-agent-loop@1", "summary": "Clearance lapsed", "changed": True},
                {"key": "tm:instructor/example-c|sl:unit/example-agent-loop@1", "summary": "Cleared", "changed": False},
                {"key": "tm:instructor/example-d|sl:unit/example-agent-loop@1", "summary": "Cleared", "changed": False},
            ],
        },
        fields=[{"name": "note", "label": "Note", "kind": "text", "required": False}],
        channel=LIBRARY,
        title="Gap list: agree the rows",
        intro="Approve the unchanged rows in one step; decide each changed row.",
    ),
    # Pages using the field kinds of increment 2; the template is the shared `approve` layout.
    "evidence_score": dict(
        template="approve",
        step="tm:step/observe",
        subject_uri="tm:assignment/0123456789abcdef",
        signer="tm:instructor/example-obs",
        role="observer-in-training",
        inputs={"assignment": "tm:assignment/0123456789abcdef", "unit": "sl:unit/example-agent-loop@1"},
        fields=pages.evidence_score_fields(STD),
        channel=MAIL,
        title="Observation: score each domain",
        intro="Score what you saw against the anchors. Every score needs an evidence note.",
    ),
    "checklist": dict(
        template="approve",
        step="tm:step/dry-run",
        subject_uri="tm:candidate/example-a--example-agent-loop-1--remote",
        signer="tm:person/example-clearer",
        role="clearer",
        inputs={"unit": "sl:unit/example-agent-loop@1", "mode": "remote"},
        fields=[
            {"name": "preflight", "label": "Preflight", "kind": "checklist", "required": True,
             "help": "Mark each item.", "items": [
                 {"id": "keys-scoped", "label": "API keys are scoped to the sandbox"},
                 {"id": "model-pinned", "label": "Model version is pinned"},
                 {"id": "fallback-ready", "label": "Pre-computed outputs are loaded"}]},
            {"name": "minutes", "label": "Minutes over plan", "kind": "number", "required": False, "min": 0, "max": 60,
             "help": "Whole minutes."},
        ],
        channel=MAIL,
        title="Dry run: walk the checklist",
        intro="Run the unit as the learners will.",
    ),
}


def build(name: str, **overrides):
    case = {**CASES[name], **overrides}
    return pages.render(case.pop("template", name), **case)


def check_snapshot(template: str) -> None:
    got, _ = build(template)
    path = SNAPSHOTS / f"{template}.html"
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_bytes(got.encode("utf-8"))
    assert path.exists(), f"missing snapshot {path}; run with UPDATE_SNAPSHOTS=1"
    assert got == path.read_bytes().decode("utf-8"), f"{template} changed; run with UPDATE_SNAPSHOTS=1 if intended"


def tm_data(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="tm-data">(.*?)</script>', page, re.S)
    assert m, "no tm-data block"
    return json.loads(m.group(1))


def test_snapshot_approve():
    check_snapshot("approve")


def test_snapshot_self_assessment():
    check_snapshot("self_assessment")


def test_snapshot_dpia_screening():
    check_snapshot("dpia_screening")


def test_snapshot_batch_approve():
    check_snapshot("batch_approve")


def test_snapshot_evidence_score_page():
    check_snapshot("evidence_score")


def test_snapshot_checklist_and_number_page():
    check_snapshot("checklist")


def test_render_is_deterministic():
    for t in CASES:
        assert build(t) == build(t)


@pytest.mark.parametrize("template", list(CASES))
def test_no_external_urls(template):
    page, _ = build(template)
    for m in re.finditer(r'\b(?:src|href|action)\s*=\s*"([^"]*)"', page):
        assert not re.match(r"(?i)(https?:)?//", m.group(1)), m.group(0)
    assert "http://" not in page and "https://" not in page
    assert "<link" not in page


@pytest.mark.parametrize("template", list(CASES))
def test_hash_embedded_matches(template):
    page, digest = build(template)
    data = tm_data(page)
    assert data["input_sha256"] == digest == input_sha256(data["inputs"]) == input_sha256(CASES[template]["inputs"])
    file = CASES[template].get("template", template)
    expect = hashlib.sha256((PAGE_TEMPLATES / "base.html").read_bytes() + (PAGE_TEMPLATES / f"{file}.html").read_bytes())
    assert data["page_template_sha256"] == expect.hexdigest()
    assert data["step"] == CASES[template]["step"]
    assert data["subject_uri"] == CASES[template]["subject_uri"]
    assert data["signer"] == CASES[template]["signer"]
    assert data["schema"] == "tm:contract/signoff@1"
    assert [f["name"] for f in data["fields"]] == [f["name"] for f in CASES[template]["fields"]]


def test_changed_input_changes_hash():
    _, a = build("approve")
    _, b = build("approve", inputs={**CASES["approve"]["inputs"], "sharing_links": "some"})
    assert a != b


def test_write_page_sidecar_hash(tmp_path):
    page, digest = build("dpia_screening")
    html_path, sidecar = pages.write_page(tmp_path, "dpia-screening", page, CASES["dpia_screening"]["inputs"])
    assert html_path.read_bytes().decode("utf-8") == page
    assert input_sha256(json.loads(sidecar.read_text(encoding="utf-8"))) == digest == tm_data(page)["input_sha256"]
    assert hashlib.sha256(sidecar.read_bytes()).hexdigest() == digest  # canonical bytes, no trailing newline


def test_dpia_has_nine_criteria():
    fields = pages.dpia_fields()
    criteria = [f for f in fields if f["kind"] == "enum" and f["options"] == ["yes", "no", "unsure"]]
    assert len(criteria) == 9
    assert all(f["required"] and f["value"] in ("yes", "no") and f["help"] for f in criteria)
    prefill = {f["name"]: f["value"] for f in criteria}
    assert prefill["evaluation-scoring"] == "yes"
    assert prefill["vulnerable-subjects"] == "yes"
    assert prefill["systematic-monitoring"] == "yes"
    assert sum(v == "no" for v in prefill.values()) == 6
    decision = next(f for f in fields if f["name"] == "dpo-decision")
    assert decision["options"] == ["dpia-required", "dpia-not-required", "needs-more-information"]
    rationale = next(f for f in fields if f["name"] == "rationale")
    assert rationale["kind"] == "textarea" and rationale["required"]
    page, _ = build("dpia_screening")
    assert "Two or more criteria usually indicate a DPIA is required (WP248 rev.01)." in page


def test_self_assessment_one_field_per_domain():
    fields = pages.self_assessment_fields(STD)
    scores = [f for f in fields if f["kind"] == "score"]
    assert [f["name"] for f in scores] == [d["id"] for d in STD["framework"]["domains"]]
    for f in scores:
        assert f["required"]
        assert [a["point"] for a in f["anchors"]] == [1, 2, 3, 4]
        assert [a["text"] for a in f["anchors"]] == [STD["rubric"]["anchors"][f["name"]][p] for p in (1, 2, 3, 4)]
    assert len([f for f in fields if f["kind"] == "textarea" and not f["required"]]) == len(scores)
    page, _ = build("self_assessment")
    for dom in STD["framework"]["domains"]:
        for p in (1, 2, 3, 4):
            assert STD["rubric"]["anchors"][dom["id"]][p].replace("'", "&#x27;") in page


def test_batch_unchanged_collapsed_changed_expanded():
    page, _ = build("batch_approve")
    details = re.search(r"<details>(.*?)</details>", page, re.S).group(1)
    assert "instructor/example-c|" in details and "instructor/example-d|" in details
    assert "instructor/example-a|" not in details and "instructor/example-b|" not in details
    assert 'id="tm-approve-unchanged"' in page
    assert page.count('name="row-0"') == 2 and page.count('name="row-1"') == 2  # approve/reject per changed row
    assert 'name="row-2"' not in page


def test_mail_channel_has_tagged_mailto():
    page, _ = build("approve")
    assert 'href="mailto:programme@example.test?subject=%5Btm-signoff%20%3Cid%3E%5D"' in page
    assert "tm-signoff" in page


def test_mail_channel_offers_the_draft_and_the_file_alone():
    page, _ = build("approve")
    assert "email draft" in page and 'id="tm-json"' in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_draft_carries_the_signoff_file_byte_for_byte(tmp_path):
    # the page's own emlDraft, run in node; Outlook opens an X-Unsent message as a draft to send
    import email
    import subprocess
    from email import policy

    template = (PAGE_TEMPLATES / "base.html").read_text(encoding="utf-8")
    fn = re.search(r"\n  function emlDraft\(.*?\n  }\n", template, re.S).group(0)
    text = json.dumps({"schema": "tm:contract/signoff@1", "id": "ab" * 16, "fields": {"note": "é ✓ " + "x" * 200}},
                      indent=2, ensure_ascii=False)
    script = tmp_path / "eml.js"
    script.write_text(fn + "\nprocess.stdout.write(emlDraft(process.argv[2], process.argv[3], process.argv[4], "
                           "require('fs').readFileSync(process.argv[5], 'utf8')));\n", encoding="utf-8")
    (tmp_path / "s.json").write_text(text, encoding="utf-8", newline="")
    subject = "[tm-signoff " + "ab" * 16 + "]"
    out = subprocess.run(["node", str(script), "signoffs@example.com", subject, "it-done-x.json",
                          str(tmp_path / "s.json")], capture_output=True, check=True).stdout
    lines = out.split(b"\r\n")
    assert all(len(line) <= 998 for line in lines) and b"\n" not in out.replace(b"\r\n", b"")  # RFC 5322 2.1.1
    b64 = lines[lines.index(b"Content-Transfer-Encoding: base64") + 2:-2]
    assert len(b64) > 1 and all(0 < len(line) <= 76 for line in b64)
    msg = email.message_from_bytes(out, policy=policy.default)
    assert (msg["To"], msg["Subject"], msg["X-Unsent"]) == ("signoffs@example.com", subject, "1")
    files = list(msg.iter_attachments())
    assert [f.get_filename() for f in files] == ["it-done-x.json"]
    assert files[0].get_content_type() == "application/json"
    assert files[0].get_payload(decode=True) == text.encode("utf-8")
    assert "unchanged" in msg.get_body(("plain",)).get_content()


def test_library_channel_shows_path():
    page, _ = build("batch_approve")
    assert "Instructor Development Library/inbox" in page
    assert 'id="tm-mailto"' not in page


def test_markup_in_values_is_escaped():
    evil = "</script><b>x</b>"
    page, _ = build("approve", title=evil, intro=evil, inputs={"k": evil})
    assert "<b>x</b>" not in page
    assert page.count("</script>") == 2  # only the two real script blocks
    assert tm_data(page)["inputs"] == {"k": evil}


@pytest.mark.parametrize(
    "override",
    [
        {"step": "it-done"},
        {"signer": "someone@example.test"},
        {"channel": {"kind": "mail", "to": "not-an-address"}},
        {"channel": {"kind": "pigeon"}},
        {"fields": [{"name": "x", "label": "X", "kind": "enum"}]},
        {"fields": [{"name": "x", "label": "X", "kind": "wat"}]},
        {"fields": [{"name": "x", "label": "X", "kind": "text"}, {"name": "x", "label": "Y", "kind": "text"}]},
    ],
)
def test_bad_specs_rejected(override):
    with pytest.raises(ValueError):
        build("approve", **override)


def test_unknown_template_rejected():
    with pytest.raises(ValueError):
        pages.render("nope", **CASES["approve"])


def test_batch_needs_unique_rows():
    dup = {"rows": [{"key": "a", "summary": "x"}, {"key": "a", "summary": "y"}]}
    with pytest.raises(ValueError):
        build("batch_approve", inputs=dup)


# --- preformatted intro blocks (the profile diff) and DPIA citations -------------------------------------


def test_a_fenced_intro_paragraph_is_preformatted_and_escaped():
    out = mdlite.to_html("Changes:\n\n```\n- old <b>\n+ new\n```\n\nAfter.")
    assert out == "<p>Changes:</p><pre>- old &lt;b&gt;\n+ new</pre><p>After.</p>"
    assert mdlite.to_html("plain\n\nlines") == "<p>plain</p><p>lines</p>"
    assert mdlite.to_html("```not closed") == "<p>```not closed</p>"


def test_dpia_fields_cite_only_matching_criteria_and_keep_the_answers():
    base = pages.dpia_fields()
    cited = pages.dpia_fields([{"criterion": "large-scale", "citation": "s.5"},
                               {"criterion": "free text, not an id", "citation": "s.6"}])
    by = {f["name"]: f for f in cited}
    assert by["large-scale"]["help"].endswith(" Base profile: s.5")
    assert [f.get("value") for f in cited] == [f.get("value") for f in base]
    assert [f["help"] for f in cited if f["name"] != "large-scale"] == [f["help"] for f in base if f["name"] != "large-scale"]


def test_dpia_delta_fields_ask_one_question_per_delta_criterion_with_its_citations():
    delta = [{"criterion": "ca-sell-or-share", "citations": ["s.21", "s.22"]}]
    fields = pages.dpia_delta_fields(delta)
    assert [f["name"] for f in fields] == ["ca-sell-or-share", "dpo-decision", "rationale"]
    q = fields[0]
    assert q["kind"] == "enum" and q["options"] == ["yes", "no", "unsure"] and q["required"] is True
    assert q.get("value") is None  # nothing is pre-answered: the programme has no standing answer to a new criterion
    assert "s.21" in q["help"] and "s.22" in q["help"]
    decision = fields[1]
    assert decision["options"] == pages.DPIA_DECISIONS and decision["required"] is True
    for f in fields:
        pages._normalise_field(f)  # every field is one the page can render


# --- field kinds of increment 2: evidence_score, checklist, number -------------------------------------------


def _field(**kw):
    return {"name": "x", "label": "X", **kw}


def test_new_kinds_are_known():
    assert {"evidence_score", "checklist", "number"} <= set(pages.KINDS)


def test_evidence_score_fields_one_required_field_per_domain_with_anchors():
    fields = pages.evidence_score_fields(STD)
    assert [f["name"] for f in fields] == [d["id"] for d in STD["framework"]["domains"]]
    for f in fields:
        assert f["kind"] == "evidence_score" and f["required"]
        assert [a["point"] for a in f["anchors"]] == [1, 2, 3, 4]
        assert [a["text"] for a in f["anchors"]] == [STD["rubric"]["anchors"][f["name"]][p] for p in (1, 2, 3, 4)]
        pages._normalise_field(f)


def test_evidence_score_renders_anchors_a_required_note_and_an_optional_timestamp():
    page, _ = build("evidence_score")
    dom = STD["framework"]["domains"][0]["id"]
    for p in (1, 2, 3, 4):
        assert f'id="f-{dom}-{p}"' in page
        assert STD["rubric"]["anchors"][dom][p].replace("'", "&#x27;") in page
    assert f'id="f-{dom}-note"' in page and f'id="f-{dom}-ts"' in page
    note = re.search(rf'<textarea id="f-{dom}-note"[^>]*>', page).group(0)
    assert 'aria-required="true"' in note
    assert 'aria-required' not in re.search(rf'<input type="text" id="f-{dom}-ts"[^>]*>', page).group(0)
    data = tm_data(page)
    assert [f["kind"] for f in data["fields"]] == ["evidence_score"] * len(STD["framework"]["domains"])


@pytest.mark.parametrize("value", [0, 5, "3", True, {"score": 5, "note": "x"}, {"note": "x"}, {"score": 3, "note": ""}])
def test_evidence_score_rejects_a_malformed_prefill(value):
    with pytest.raises(ValueError):
        pages._normalise_field(_field(kind="evidence_score", value=value))


def test_evidence_score_accepts_a_prefill():
    f = pages._normalise_field(_field(kind="evidence_score", value={"score": 3, "note": "Asked a probing question."}))
    assert f["value"] == {"score": 3, "note": "Asked a probing question."}


def test_evidence_score_may_offer_not_observable_with_its_own_id():
    plain = pages._normalise_field(_field(kind="evidence_score"))
    assert "not_observable" not in plain  # a field without the flag is unchanged
    f = pages._normalise_field(_field(kind="evidence_score", not_observable=True))
    assert f["not_observable"] is True and "f-x-no" in pages._element_ids(f)
    html = pages._field_html(f)
    assert 'id="f-x-no"' in html and 'value="no"' in html and "Not observable in this slice" in html
    assert 'id="f-x-no"' not in pages._field_html(plain)


@pytest.mark.parametrize("value, ok", [
    ({"not_observable": True, "note": "No remote learners in the slice."}, True),
    ({"not_observable": True, "note": ""}, False),
    ({"not_observable": True, "score": 3, "note": "x"}, False),
])
def test_a_not_observable_prefill_needs_its_note_and_no_score(value, ok):
    spec = _field(kind="evidence_score", not_observable=True, value=value)
    if ok:
        assert pages._normalise_field(spec)["value"] == value
    else:
        with pytest.raises(ValueError):
            pages._normalise_field(spec)
    with pytest.raises(ValueError):  # without the flag, not observable is no answer
        pages._normalise_field(_field(kind="evidence_score", value={"not_observable": True, "note": "x"}))


def test_checklist_renders_a_pass_fail_pair_and_a_note_per_item():
    page, _ = build("checklist")
    for item in ("keys-scoped", "model-pinned", "fallback-ready"):
        assert f'name="f-preflight-{item}"' in page and page.count(f'name="f-preflight-{item}"') == 2
        assert f'id="f-preflight-{item}-note"' in page
    assert "API keys are scoped to the sandbox" in page
    data = tm_data(page)
    assert data["fields"][0]["items"] == CASES["checklist"]["fields"][0]["items"]


@pytest.mark.parametrize("items", [
    None, [], "keys", [{"id": "a"}], [{"label": "A"}], [{"id": "A", "label": "A"}], [{"id": "a", "label": ""}],
    [{"id": "a", "label": "A"}, {"id": "a", "label": "B"}], ["a"], [{"id": "rows", "label": "A"}, 3],
])
def test_checklist_rejects_malformed_items(items):
    with pytest.raises(ValueError):
        pages._normalise_field(_field(kind="checklist", items=items))


def test_checklist_item_labels_are_escaped():
    evil = "<b>x</b>"
    page, _ = build("checklist", fields=[
        {"name": "c", "label": "C", "kind": "checklist", "items": [{"id": "a", "label": evil}]}])
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page


def test_number_renders_bounds_and_keeps_them_in_the_data():
    page, _ = build("checklist")
    assert re.search(r'<input type="number" id="f-minutes"[^>]*min="0"[^>]*max="60"', page)
    number = next(f for f in tm_data(page)["fields"] if f["kind"] == "number")
    assert (number["min"], number["max"]) == (0, 60)


@pytest.mark.parametrize("spec", [
    {"min": "0"}, {"max": True}, {"min": 5, "max": 1}, {"value": "7"}, {"min": 0, "max": 10, "value": 11},
    {"min": 0, "value": -1}, {"value": True}, {"max": float("inf")},
])
def test_number_rejects_malformed_bounds_or_value(spec):
    with pytest.raises(ValueError):
        pages._normalise_field(_field(kind="number", **spec))


def test_number_accepts_no_bounds_and_a_value_within_them():
    assert pages._normalise_field(_field(kind="number"))["value"] is None
    f = pages._normalise_field(_field(kind="number", min=0, max=10, value=3.5))
    assert (f["min"], f["max"], f["value"]) == (0, 10, 3.5)


def test_ids_derived_from_one_field_may_not_clash_with_another_fields():
    with pytest.raises(ValueError, match="clash"):
        build("evidence_score", fields=[
            {"name": "depth", "label": "D", "kind": "evidence_score"},
            {"name": "depth-note", "label": "N", "kind": "text"}])
