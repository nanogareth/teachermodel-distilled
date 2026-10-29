"""Pinpoint citations of repository documents, and the table of authorities that lists them.

Generated documents (the record of processing, the IT request) cite their sources the way a legal document does: a
short citation in the text that names the document, the section and the paragraph, and a table of authorities at the
end that gives each document's full title, status, date and path. The DPO asked for this on 2026-10-26: a bare
"decision 0006" names a source without saying where it is.

Format, in markdown:
- in the text: `[Decision 0006 § Decision ¶3](docs/decisions/0006-private-store-location-and-backup.md#decision)`;
  the link target is the document's path relative to the repository root, with the section's heading anchor;
- paragraphs (¶) count the paragraphs, top-level list items and tables of a section in order, from 1. A paragraph may
  be named by its bold lead ("**Access.**") or its label ("Retention:") instead of its number; the number is looked up
  so that the citation stays right when paragraphs are added above it.

A citation of a section or paragraph that does not exist raises CitationError: a generated document never cites a
place that is not there.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .mdlite import slug

DECISIONS = "docs/decisions"
# Short names for documents that are not decision records (the spec snapshot and the design specs).
SHORT_NAMES = {
    "docs/specs/2026-10-23-instructor-development-spec-v0.2.md": "Spec v0.2",
    "docs/specs/2026-10-24-workflow-automation-design.md": "Workflow-automation design",
    "docs/specs/2026-10-24-privacy-jurisdictions-design.md": "Privacy-jurisdictions design",
}
PARAGRAPH_RULE = ("¶ numbers count the paragraphs, top-level list items and tables of a section in order, from 1. "
                  "Paths are relative to the root of the teachermodel repository.")

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_H2 = re.compile(r"^##\s+(.*?)\s*$")
_H1 = re.compile(r"^#\s+(.*?)\s*$")
_ITEM = re.compile(r"^([-*]|\d+[.)])\s+")
_BOLD_LEAD = re.compile(r"^(?:[-*]|\d+[.)])?\s*\*\*(.+?)[.:]?\*\*")
_LABEL_LEAD = re.compile(r"^(?:[-*]|\d+[.)])?\s*([A-Z][^:.]{0,60}):\s")


class CitationError(ValueError):
    """A citation names a document, section or paragraph that does not exist."""


@dataclass(frozen=True)
class Document:
    path: str  # relative to the repository root, forward slashes
    short: str
    title: str
    status: str
    date: str
    sections: dict[str, list[str]]  # heading -> paragraphs (first line of each)


def _blocks(lines: list[str]) -> list[str]:
    """The first line of each paragraph, top-level list item, table and code block, in order: the blocks
    mdlite.to_html(numbered=True) numbers, so a ¶ in a citation is the ¶ shown beside the rendered document."""
    out: list[str] = []
    kind: str | None = None  # the block being read: "p", "item", "table", "pre" or None
    for line in lines:
        if kind == "pre":
            if line.lstrip().startswith("```"):
                kind = None
            continue
        if line.lstrip().startswith("```"):
            out.append(line)
            kind = "pre"
            continue
        if not line.strip() or line.startswith("#"):
            kind = None
            continue
        if _ITEM.match(line):
            out.append(line)
            kind = "item"
        elif line.lstrip().startswith("|"):
            if kind != "table":
                out.append(line)
            kind = "table"
        elif kind is None or kind == "table" or (kind == "item" and not line.startswith(" ")):
            out.append(line)
            kind = "p"
    return out


_CACHE: dict[tuple[str, int, int], Document] = {}


def load(root: Path, rel: str) -> Document:
    path = Path(root) / rel
    try:
        stat = path.stat()
    except OSError as exc:
        raise CitationError(f"cited document {rel} does not exist") from exc
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    found = _CACHE.get(key)
    if found is not None:
        return found
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    status = date = ""
    front = _FRONT.match(text)
    if front:
        for line in front.group(1).splitlines():
            k, _, v = line.partition(":")
            if k.strip() == "status":
                status = v.strip()
            elif k.strip() == "date":
                date = v.strip()
        text = text[front.end():]
    title = rel
    sections: dict[str, list[str]] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.split("\n"):
        h1 = _H1.match(line)
        if h1 and title == rel:
            title = h1.group(1)
            continue
        h2 = _H2.match(line)
        if h2:
            if current is not None:
                sections[current] = _blocks(buf)
            current, buf = h2.group(1), []
            continue
        if current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = _blocks(buf)
    m = re.match(r"^docs/decisions/(\d{4})-", rel)
    if m:
        short = f"Decision {m.group(1)}"
        title = re.sub(r"^\d{4}\s+", "", title)
    else:
        short = SHORT_NAMES.get(rel, rel)
    doc = Document(path=rel, short=short, title=title, status=status, date=date, sections=sections)
    _CACHE[key] = doc
    return doc


def decision_path(root: Path, number: str) -> str:
    found = sorted((Path(root) / DECISIONS).glob(f"{number}-*.md"))
    if len(found) != 1:
        raise CitationError(f"decision {number}: expected one file {DECISIONS}/{number}-*.md, found {len(found)}")
    return f"{DECISIONS}/{found[0].name}"


def _section(doc: Document, section: str) -> str:
    if section in doc.sections:
        return section
    # A numbered heading ("7. Setup workflow (...)") may be cited by its number.
    numbered = [h for h in doc.sections if re.match(rf"^{re.escape(section)}\.\s", h)]
    if len(numbered) == 1:
        return numbered[0]
    raise CitationError(f"{doc.path}: no section {section!r}; sections are {list(doc.sections)}")


def _paragraph(doc: Document, heading: str, para: int | str) -> int:
    blocks = doc.sections[heading]
    if isinstance(para, int):
        if not 1 <= para <= len(blocks):
            raise CitationError(f"{doc.path} § {heading}: no ¶{para}; the section has {len(blocks)}")
        return para
    hits = []
    for n, b in enumerate(blocks, start=1):
        m = _BOLD_LEAD.match(b) or _LABEL_LEAD.match(b)
        if m and m.group(1).strip().lower() == para.strip().lower():
            hits.append(n)
    if len(hits) != 1:
        raise CitationError(f"{doc.path} § {heading}: {len(hits)} paragraphs named {para!r}, expected one")
    return hits[0]


@dataclass
class Citer:
    """Builds citations for one generated document and remembers what it cited, for the table of authorities."""

    root: Path
    cited: list[str] = field(default_factory=list)

    def _doc(self, ref: str) -> Document:
        rel = decision_path(self.root, ref) if re.fullmatch(r"\d{4}", ref) else ref
        doc = load(self.root, rel)
        if rel not in self.cited:
            self.cited.append(rel)
        return doc

    def __call__(self, ref: str, section: str | None = None, para: int | str | None = None) -> str:
        """A markdown short citation. `ref` is a decision number ("0006") or a path relative to the root."""
        doc = self._doc(ref)
        text, anchor = doc.short, ""
        if section is not None:
            heading = _section(doc, section)
            shown = heading.split(". ", 1)[0] if re.match(r"^\d+\.\s", heading) else heading
            text += f" § {shown}"
            anchor = "#" + slug(heading)
            if para is not None:
                n = _paragraph(doc, heading, para)
                text += f" ¶{n}"
                if isinstance(para, str):
                    text += f" ({para})"
        elif para is not None:
            raise CitationError("a paragraph needs a section")
        return f"[{text}]({doc.path}{anchor})"

    def path(self, rel: str) -> str:
        """A link to a whole document that is not prose (a contract schema), listed in the table of authorities."""
        if rel.endswith(".md"):
            self._doc(rel)
        else:
            self._contract(rel)
        return f"[{rel}]({rel})"

    def _contract(self, rel: str) -> None:
        if not (Path(self.root) / rel).is_file():
            raise CitationError(f"cited file {rel} does not exist")
        if rel not in self.cited:
            self.cited.append(rel)

    def mentions(self, text: str) -> str:
        """Replace bare mentions ("decision 0005", "decisions 0004 and 0006") with citations of each decision's
        Decision section (and its ¶1 when that section is one paragraph). Text inside a markdown link is left alone."""
        def cite_decision(n: str) -> str:
            single = len(self._doc(n).sections.get("Decision", [])) == 1
            return self(n, "Decision", 1 if single else None)

        def one(m: re.Match[str]) -> str:
            return " and ".join(cite_decision(n) for n in re.findall(r"\d{4}", m.group(0)))
        pattern = re.compile(r"\b[Dd]ecisions?(?: records?)? \d{4}(?:(?:, | and )\d{4})*")

        def line(s: str) -> str:
            if s.lstrip().startswith("|"):  # a table row: the table of authorities names documents, it cites none
                return s
            parts = re.split(r"(\[[^\]]*\]\([^)]*\))", s)
            return "".join(p if p.startswith("[") else pattern.sub(one, p) for p in parts)
        return "\n".join(line(s) for s in text.split("\n"))

    def table(self) -> str:
        """The table of authorities, in the order the documents were first cited."""
        rows = ["| Short citation | Title | Status | Path |", "| --- | --- | --- | --- |"]
        for rel in self.cited:
            if rel.endswith(".md"):
                doc = load(self.root, rel)
                status = " ".join(x for x in (doc.status, doc.date) if x) or "-"
                rows.append(f"| {doc.short} | {doc.title} | {status} | [{rel}]({rel}) |")
            else:
                schema = json.loads((Path(self.root) / rel).read_text(encoding="utf-8"))
                title = schema.get("title") or "-"
                rows.append(f"| {rel} | {title} | {schema.get('$id', '-')} | [{rel}]({rel}) |")
        return "\n".join(rows) + "\n\n" + PARAGRAPH_RULE
