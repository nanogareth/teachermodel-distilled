"""A small, deterministic markdown-to-HTML renderer for the documents this project writes itself.

It covers what the generated documents use: ATX headings, paragraphs, bullet and numbered lists (nested by indent),
pipe tables, fenced code, `code`, **bold**, [text](href) links and bare http(s) URLs. HTML comments are dropped.
Everything else is escaped text, so the output never carries markup from the source.

Two rules keep hard-wrapped source readable:
- a wrapped line joins the line before it with a space;
- a line that starts with a label ("Basis: ...", "  Data categories: ...") after a line that ends a sentence or is
  itself labelled starts a new line instead (<br>), because generated documents put one labelled fact per line.

Hooks let a caller change links without this module knowing about the repository: `href` maps a link target to the
one used on output (for example a repository path to an anchor inside a page), and `heading_extra` appends HTML to a
heading (a "reviewed" checkbox on a sign-off page).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .util import esc as _esc

Href = Callable[[str, str], str]  # (link target, link text) -> target written to the page
HeadingExtra = Callable[[int, str], str]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^(\s*)([-*]|\d+[.)])\s+(.*)$")
_LABEL = re.compile(r"^[A-Z][^:.!?]{0,80}:\s")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_INLINE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|\[(?P<text>[^\]\n]+)\]\((?P<href>[^)\s]+)\)"
    r"|(?P<url>https?://[^\s<>()\"']+[^\s<>()\"'.,;:!?])"
)
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def slug(text: str) -> str:
    """A GitHub-style heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    s = re.sub(r"[^\w\- ]", "", text.replace("`", "").strip().lower())
    return re.sub(r"\s", "-", s)


def _bold(s: str) -> str:
    """`s` escaped, with its **bold** spans marked up."""
    return _BOLD.sub(r"<strong>\1</strong>", _esc(s))


def _same(target: str, text: str) -> str:
    return target


def _a(target: str, label_html: str) -> str:
    """A link; one that leaves the document opens in a new tab."""
    external = ' target="_blank" rel="noopener"' if target.startswith(("http://", "https://")) else ""
    return f'<a href="{_esc(target)}"{external}>{label_html}</a>'


def inline(text: str, href: Href = _same) -> str:
    """Escape `text` and render its inline markup."""
    out: list[str] = []
    pos = 0
    for m in _INLINE.finditer(text):
        out.append(_bold(text[pos:m.start()]))
        if m.group("code"):
            out.append(f"<code>{_esc(m.group('code')[1:-1])}</code>")
        elif m.group("href"):
            out.append(_a(href(m.group("href"), m.group("text")), _bold(m.group("text"))))
        else:
            url = m.group("url")
            out.append(_a(href(url, url), _esc(url)))
        pos = m.end()
    out.append(_bold(text[pos:]))
    return "".join(out)


def _join(lines: list[str], href: Href) -> str:
    """Wrapped lines joined with a space; a labelled line starts a new line."""
    parts: list[str] = []
    for i, line in enumerate(lines):
        s = line.strip()
        prev = lines[i - 1].strip() if i else ""
        if i and _LABEL.match(s) and (prev.endswith((".", ")", "]", "!", "?", ":")) or _LABEL.match(prev)):
            parts.append("<br>")
        elif i:
            parts.append(" ")
        parts.append(inline(s, href))
    return "".join(parts)


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _list(lines: list[str], i: int, href: Href, mark: Callable[[], str] | None = None) -> tuple[str, int]:
    """The list starting at lines[i]; returns (html, index after it). `mark` prefixes each item of this list (not of
    a nested one) with a paragraph number."""
    first = _ITEM.match(lines[i])
    assert first is not None
    base = len(first.group(1))
    tag = "ol" if first.group(2)[0].isdigit() else "ul"
    items: list[str] = []
    while i < len(lines):
        m = _ITEM.match(lines[i])
        if not m or len(m.group(1)) != base or ("ol" if m.group(2)[0].isdigit() else "ul") != tag:
            break
        body = [m.group(3)]
        nested = ""
        i += 1
        while i < len(lines) and lines[i].strip():
            sub = _ITEM.match(lines[i])
            if sub and len(sub.group(1)) > base:
                html_, i = _list(lines, i, href)
                nested += html_
                continue
            if sub or _indent(lines[i]) <= base:
                break
            body.append(lines[i])
            i += 1
        items.append(f"<li>{mark() if mark else ''}{_join(body, href)}{nested}</li>")
    return f"<{tag}>" + "".join(items) + f"</{tag}>", i


def to_html(text: str, *, heading_offset: int = 0, href: Href = _same,
            heading_extra: HeadingExtra | None = None, id_prefix: str = "", numbered: bool = False) -> str:
    """Render `text`. A heading of level n becomes h(n + heading_offset), at most h6, with id `id_prefix` + its slug.

    With `numbered`, every paragraph, top-level list item, table and code block under a level-2 heading gets a
    paragraph number (¶), counted from 1 in each level-2 section, as citations counts them, with id
    `<id_prefix><section slug>-p<n>`."""
    lines = _COMMENT.sub("", text).replace("\r\n", "\n").split("\n")
    out: list[str] = []
    section: str | None = None  # slug of the level-2 section we are in
    n = 0  # paragraphs numbered so far in it

    def mark() -> str:
        nonlocal n
        if not (numbered and section is not None):
            return ""
        n += 1
        return f'<span class="para" id="{_esc(id_prefix)}{_esc(section)}-p{n}">\u00b6{n}</span> '

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        closing = next((j for j in range(i + 1, len(lines)) if lines[j].lstrip().startswith("```")), None) \
            if line.lstrip().startswith("```") else None
        if closing is not None:  # an unclosed fence is text
            j = closing
            out.append(mark() + "<pre>" + _esc("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        h = _HEADING.match(line)
        if h:
            source_level = len(h.group(1))
            level = min(source_level + heading_offset, 6)
            title = h.group(2)
            if source_level <= 2:
                section, n = (slug(title) if source_level == 2 else None), 0
            extra = heading_extra(level, title) if heading_extra else ""
            out.append(f'<h{level} id="{_esc(id_prefix + slug(title))}">{inline(title, href)}{extra}</h{level}>')
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            head = _cells(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            th = "".join(f"<th>{inline(c, href)}</th>" for c in head)
            body = "".join("<tr>" + "".join(f"<td>{inline(c, href)}</td>" for c in r) + "</tr>" for r in rows)
            out.append(mark() + f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")
            continue
        if _ITEM.match(line):
            html_, i = _list(lines, i, href, mark if numbered and section is not None else None)
            out.append(html_)
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _ITEM.match(lines[i]) and not _HEADING.match(lines[i]) \
                and not lines[i].lstrip().startswith(("```", "|")):
            para.append(lines[i])
            i += 1
        out.append(f"<p>{mark()}{_join(para, href)}</p>")
    return "".join(out)
