"""How generated documents and sign-off pages present themselves (DPO, legal and IT requests of 2026-10-26):
markdown rendered as HTML, pinpoint citations with a table of authorities, references copied into the page,
review ticks and the IT checklist."""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from teachermodel import mdlite, pages, setup
from teachermodel.citations import CitationError, Citer, load
from teachermodel.flows.setup import it_checklist
from teachermodel.standards import ROOT

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
SETTINGS = {
    "schema": "tm:contract/settings@1", "library": "TeacherModel Private", "mailbox": "signoffs@example.com",
    "it_email": "it.requests@example.com", "dpo_email": "dpo@example.com", "notice_version": "2026-11",
}
PROSE = sorted([*(ROOT / "docs" / "decisions").glob("*.md"), *(ROOT / "docs" / "specs").glob("*.md")])


# --- mdlite --------------------------------------------------------------------------------------------------------


def test_markdown_blocks_render_and_escape():
    out = mdlite.to_html("# Title\n\nSome <b>text</b> with `code` and **bold**.\n\n- a\n  wrapped\n- b\n  - nested\n\n"
                         "1. one\n2. two\n\n| A | B |\n| --- | --- |\n| x | [y](https://e.example/y) |\n")
    assert '<h1 id="title">Title</h1>' in out
    assert "&lt;b&gt;text&lt;/b&gt;" in out and "<code>code</code>" in out and "<strong>bold</strong>" in out
    assert "<ul><li>a wrapped</li><li>b<ul><li>nested</li></ul></li></ul>" in out
    assert "<ol><li>one</li><li>two</li></ol>" in out
    assert '<a href="https://e.example/y" target="_blank" rel="noopener">y</a>' in out and "<th>A</th>" in out


def test_label_lines_break_only_after_a_sentence_or_another_label():
    header = mdlite.to_html("To: IT (it@example.com)\nReplies and sign-offs: s@example.com\nReference: [x]")
    assert header.count("<br>") == 2
    wrapped = mdlite.to_html("1. A library. Not a personal\n   OneDrive folder: it must not leave.")
    assert "<br>" not in wrapped  # "OneDrive folder:" continues the sentence before it


def test_html_comments_and_unclosed_fences():
    assert mdlite.to_html("<!-- element: x -->\nText") == "<p>Text</p>"
    assert mdlite.to_html("```\nopen") == "<p>``` open</p>"


@pytest.mark.parametrize("path", PROSE, ids=lambda p: p.name)
def test_rendered_paragraph_numbers_match_the_citation_numbers(path):
    """The ¶ a citation names is the ¶ shown beside the document in a page's appendix."""
    rel = path.relative_to(ROOT).as_posix()
    doc = load(ROOT, rel)
    text = re.sub(r"\A---\n.*?\n---\n", "", path.read_text(encoding="utf-8").replace("\r\n", "\n"), flags=re.S)
    out = mdlite.to_html(text, numbered=True)
    for heading, blocks in doc.sections.items():
        shown = re.findall(rf'id="{re.escape(mdlite.slug(heading))}-p(\d+)"', out)
        assert [int(n) for n in shown] == list(range(1, len(blocks) + 1)), heading


# --- citations -----------------------------------------------------------------------------------------------------


def test_a_paragraph_named_by_its_label_resolves_to_its_number():
    cite = Citer(ROOT)
    assert cite("0006", "Decision", "Access") == (
        "[Decision 0006 § Decision ¶3 (Access)](docs/decisions/0006-private-store-location-and-backup.md#decision)")
    assert cite("docs/specs/2026-10-24-workflow-automation-design.md", "7").startswith(
        "[Workflow-automation design § 7](docs/specs/2026-10-24-workflow-automation-design.md#7-")
    assert cite.cited == ["docs/decisions/0006-private-store-location-and-backup.md",
                          "docs/specs/2026-10-24-workflow-automation-design.md"]


@pytest.mark.parametrize("args", [("9999", "Decision"), ("0006", "Nowhere"), ("0006", "Decision", "No such label"),
                                  ("0006", "Decision", 99), ("docs/specs/missing.md", "1")])
def test_a_citation_of_a_place_that_does_not_exist_is_refused(args):
    with pytest.raises(CitationError):
        Citer(ROOT)(*args)


def test_bare_mentions_become_citations_but_links_and_table_rows_are_left_alone():
    cite = Citer(ROOT)
    out = cite.mentions("see decision 0005 and decisions 0004 and 0006.\n| Decision 0006 | title |\n[decision 0004](x)")
    lines = out.split("\n")
    assert lines[0].count("](docs/decisions/") == 3
    assert "[Decision 0005 § Decision ¶1]" in lines[0]  # a one-paragraph Decision section is cited by its ¶
    assert lines[1] == "| Decision 0006 | title |" and lines[2] == "[decision 0004](x)"


def test_the_ropa_cites_its_sources_with_paths_sections_and_paragraphs(tmp_path, privacy_root):
    setup.ropa(tmp_path, [], SETTINGS, NOW, root=privacy_root)
    text = (tmp_path / "generated" / "ropa.md").read_text(encoding="utf-8")
    body, _, authorities = text.partition("## Table of authorities")
    plain = re.sub(r"\[[^\]]*\]\([^)]*\)", "", body)
    assert not re.search(r"\b[Dd]ecisions?(?: records?)? \d{4}", plain), "a decision is named without a citation"
    links = re.findall(r"\]\(((?:docs|contracts)/[^)#]+)(?:#([^)]+))?\)", body)
    assert links
    for path, anchor in links:
        assert (privacy_root / path).is_file(), path
        assert path in authorities, f"{path} is cited but not in the table of authorities"
        if anchor:
            headings = load(privacy_root, path).sections
            assert anchor in {mdlite.slug(h) for h in headings}, (path, anchor)
    assert "¶3 (Access)" in body and "¶ numbers count" in authorities


# --- pages ---------------------------------------------------------------------------------------------------------


def _render(inputs, intro="", root=ROOT, fields=None):
    html_, _ = pages.render(
        "approve", step="tm:step/it-done", subject_uri="tm:programme/teachermodel", signer="tm:person/it-1",
        role="it", inputs=inputs, fields=fields or [], channel={"kind": "mail", "to": "s@example.com"},
        title="IT done", intro=intro, root=root)
    return html_


def test_a_cited_document_is_copied_into_the_page_and_every_internal_link_resolves(tmp_path):
    setup.it_request(tmp_path, [], SETTINGS, NOW)
    text = (tmp_path / "generated" / "it-request.md").read_text(encoding="utf-8")
    page = _render({"it_request_text": text})
    assert 'id="ref-docs-decisions-0006-private-store-location-and-backup-md"' in page
    assert "accepted 2026-10-24" in page and "sha256 <code>" in page
    ids = set(re.findall(r'id="([^"]+)"', page))
    targets = set(re.findall(r'href="#([^"]+)"', page))
    assert targets and targets <= ids, sorted(targets - ids)
    assert "#ref-docs-decisions-0006-private-store-location-and-backup-md-decision-p3" in page  # ¶3 (Access)
    assert 'href="docs/' not in page  # the reader has no repository: every repository link points into the page


def test_without_a_repository_the_page_keeps_its_links_and_copies_nothing():
    page = _render({"text": "Basis: [Decision 0006](docs/decisions/0006-private-store-location-and-backup.md).\n"},
                   root=None)
    assert 'id="references"' not in page and 'href="docs/decisions/0006' in page


def test_every_section_has_a_review_tick_and_the_page_lists_its_contents():
    inputs = {"file": "standards/privacy/purposes.yaml", "sha256": "a" * 64,
              "profile": {"name": "X", "laws": [{"citation": "A", "url": "https://law.example/a", "accessed": "2026-10-24"}],
                          "rights": {"access": "30 days"}},
              "notes": ["one", "two"]}
    page = _render(inputs)
    ticks = re.findall(r'data-review="([^"]+)"', page)
    assert ticks == ["part-summary", "part-profile", "part-profile-laws", "part-profile-rights", "part-notes"]
    assert 'class="contents"' in page and '<th>Accessed</th>' in page
    assert "<td>2026-10-24</td>" in page  # the web source's access date, in the record table and the appendix
    assert '<td><a href="https://law.example/a" target="_blank" rel="noopener">' in page
    assert f"<code>{'a' * 64}</code>" in page
    assert '<a href="#ref-standards-privacy-purposes-yaml">standards/privacy/purposes.yaml</a>' in page


def test_a_web_link_without_a_recorded_access_date_says_so():
    page = _render({"note": "See https://www.dataprotection.ie for the regulator."})
    assert "not recorded in the source" in page


def test_the_it_checklist_follows_the_request_items(tmp_path):
    setup.it_request(tmp_path, [], SETTINGS, NOW)
    items = it_checklist((tmp_path / "generated" / "it-request.md").read_text(encoding="utf-8"))
    assert [i["id"] for i in items] == [f"item-{n}" for n in range(1, 7)]
    assert items[0]["label"] == 'A dedicated document library named "TeacherModel Private" in the Microsoft 365 tenant.'
    assert all("Decision 0006" not in i["label"] for i in items)
    assert it_checklist("no such heading") == []
