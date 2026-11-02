"""Offline sign-off page generator.

A page is one self-contained HTML file (it loads nothing from outside) that shows pre-filled facts, collects the
answers described by a field spec, and downloads a `tm:contract/signoff@1` JSON file. Output is
deterministic: no timestamps or ids are created at render time (the browser creates them on save).

Presentation (legal and IT, 2026-10-26):
- inputs are laid out as sections with headings; lists of records are tables; text that is markdown is rendered;
- every section has a "Reviewed" checkbox, and the page keeps the reviewer's ticks and answers in the browser
  (localStorage, keyed by step, subject, signer and input hash) until they save or clear them;
- a repository document the page cites (a decision record, a spec, a contract) is copied into a "Referenced
  documents" appendix with its paragraph numbers, and the citation links to it inside the page: the reader has no
  access to the repository. Web links open in a new tab and show the date they were accessed where the source
  records one.

Hashes embedded in every page:
- `input_sha256`: `signoff.input_sha256(inputs)`, the inputs the page showed.
- `page_template_sha256`: SHA-256 of `base.html` bytes followed by the template file's bytes, so a
  change to the shared layout or script changes it as well as a change to the template itself.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import quote

from . import events, mdlite
from .citations import CitationError, Citer, load as load_document
from .signoff import input_sha256
from .standards import PAGE_TEMPLATES
from .util import esc as _esc, write_if_changed

SIGNOFF_SCHEMA = "tm:contract/signoff@1"
TEMPLATES = ("approve", "self_assessment", "dpia_screening", "batch_approve", "revoke", "assign")  # revoke: decision 0019
KINDS = ("text", "textarea", "enum", "score", "bool", "date", "evidence_score", "checklist", "number")

_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_STEP = re.compile(r"^tm:step/")
_SUBJECT = re.compile(r"^(tm|sl):")
_SIGNER = re.compile(r"^tm:(person|instructor)/")
_MAIL = re.compile(r"^[^\s@<>\"]+@[^\s@<>\"]+$")

DPIA_DECISIONS = ["dpia-required", "dpia-not-required", "needs-more-information"]

# (field name, WP248 rev.01 criterion, prefilled answer, one-line reason). The DPO confirms each.
_DPIA_CRITERIA = [
    ("evaluation-scoring", "Evaluation or scoring, including profiling and predicting", "yes",
     "Instructors are scored against a rubric and given clearance levels."),
    ("automated-decision", "Automated decision-making with legal or similarly significant effect", "no",
     "Rules compute eligibility; a named person signs every clearance and level change."),
    ("systematic-monitoring", "Systematic monitoring", "yes",
     "Observations of delivery are recorded on a schedule (observation design)."),
    ("sensitive-data", "Sensitive data or data of a highly personal nature", "no",
     "No special-category or criminal-offence data; records hold references, roles, scores and dates."),
    ("large-scale", "Data processed on a large scale", "no",
     "A small cohort of instructors in one organisation."),
    ("dataset-matching", "Matching or combining datasets", "no",
     "Observations, roster and clearance events come from this programme only; nothing is joined to HR or external data."),
    ("vulnerable-subjects", "Data concerning vulnerable data subjects", "yes",
     "Employees are listed as vulnerable data subjects because of the employer power imbalance."),
    ("innovative-technology", "Innovative use or applying new technological or organisational solutions", "no",
     "Rules are deterministic; no model scores or profiles people."),
    ("prevents-rights-or-service", "Processing that prevents data subjects from exercising a right or using a service or contract", "no",
     "Clearance decides teaching assignments, not access to a service, benefit or contract."),
]

DPIA_CRITERION_IDS = frozenset(name for name, _, _, _ in _DPIA_CRITERIA)  # what the base screening covers


# --- field spec helpers --------------------------------------------------------------------------


def _anchors(standards: dict[str, dict[str, Any]], domain: str) -> list[dict[str, Any]]:
    scale = standards["rubric"]["scale"]
    return [{"point": p, "label": scale[p], "text": standards["rubric"]["anchors"][domain][p]} for p in (1, 2, 3, 4)]


def evidence_score_fields(standards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One required `evidence_score` field per framework domain, with the rubric anchors. An observer (W2) or a
    calibration scorer (W5) answers each with a score, an evidence note and, optionally, a recording timestamp."""
    return [
        {
            "name": dom["id"],
            "label": dom["name"],
            "kind": "evidence_score",
            "required": True,
            "help": dom["covers"],
            "anchors": _anchors(standards, dom["id"]),
        }
        for dom in standards["framework"]["domains"]
    ]


def self_assessment_fields(standards: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One required 1-4 score per framework domain (with rubric anchors) plus an optional note."""
    fields: list[dict[str, Any]] = []
    for dom in standards["framework"]["domains"]:
        did = dom["id"]
        fields.append({
            "name": did,
            "label": dom["name"],
            "kind": "score",
            "required": True,
            "help": dom["covers"],
            "anchors": _anchors(standards, did),
        })
        fields.append({
            "name": f"{did}-note",
            "label": f"{dom['name']}: evidence or comment",
            "kind": "textarea",
            "required": False,
            "help": "Optional. A specific moment that supports your score.",
        })
    return fields


def dpia_fields(triggers: Sequence[Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The nine WP29/EDPB screening criteria (WP248 rev.01), pre-answered, plus the DPO decision.

    `triggers` are the base profile's dpia_triggers. A trigger whose `criterion` is one of the nine criterion ids puts
    its citation beside that criterion; the answer stays the programme's own, because a trigger says what the law
    counts, not what this processing does. A trigger in free text is not a criterion id and is ignored."""
    cited: dict[str, list[str]] = {}
    for t in triggers or ():
        cited.setdefault(t["criterion"], []).append(t["citation"])
    fields: list[dict[str, Any]] = []
    for i, (name, label, value, reason) in enumerate(_DPIA_CRITERIA, start=1):
        fields.append({
            "name": name,
            "label": f"{i}. {label}",
            "kind": "enum",
            "options": ["yes", "no", "unsure"],
            "required": True,
            "help": reason + (" Base profile: " + " ".join(cited[name]) if name in cited else ""),
            "value": value,
        })
    fields.append({
        "name": "dpo-decision",
        "label": "DPO decision",
        "kind": "enum",
        "options": list(DPIA_DECISIONS),
        "required": True,
        "help": "Two or more criteria usually indicate a DPIA is required.",
    })
    fields.append({
        "name": "rationale",
        "label": "Rationale",
        "kind": "textarea",
        "required": True,
        "help": "Why this decision, in a sentence or two.",
    })
    return fields


def dpia_delta_fields(delta: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The questions of an overlay's DPIA delta: one per criterion the base screening does not cover (nothing is
    pre-answered, the programme has no standing answer to it), with the overlay's citations, plus the DPO decision."""
    fields: list[dict[str, Any]] = []
    for i, d in enumerate(delta, start=1):
        fields.append({
            "name": d["criterion"],
            "label": f"{i}. {d['criterion']}",
            "kind": "enum",
            "options": ["yes", "no", "unsure"],
            "required": True,
            "help": "Does this processing meet this criterion of the overlay profile? " + " ".join(d["citations"]),
        })
    return [*fields, *dpia_fields()[-2:]]


# --- rendering -----------------------------------------------------------------------------------


def template_sha256(template: str) -> str:
    """Hash of the shared layout plus the named template file (raw bytes)."""
    if template not in TEMPLATES:
        raise ValueError(f"unknown page template {template!r}; expected one of {list(TEMPLATES)}")
    key = (_template_bytes("base"), _template_bytes(template))
    if key not in _TEMPLATE_HASHES:
        _TEMPLATE_HASHES[key] = hashlib.sha256(key[0] + key[1]).hexdigest()
    return _TEMPLATE_HASHES[key]


_TEMPLATE_FILES: dict[str, tuple[tuple[int, int], bytes, float]] = {}
_TEMPLATE_RECHECK_SECONDS = 1.0  # a template file is looked at again (size and mtime) after this long
_TEMPLATE_HASHES: dict[tuple[bytes, bytes], str] = {}


def _template_bytes(name: str) -> bytes:
    """The bytes of the template file `name`, kept while the file's size and modification time stay the same (looked at
    again at most once a second): a page is rendered for every due step on every tick, and templates are read for each."""
    path = PAGE_TEMPLATES / f"{name}.html"
    now = time.monotonic()
    cached = _TEMPLATE_FILES.get(name)
    if cached is not None and now - cached[2] < _TEMPLATE_RECHECK_SECONDS:
        return cached[1]
    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    data = cached[1] if cached is not None and cached[0] == stamp else path.read_bytes()
    _TEMPLATE_FILES[name] = (stamp, data, now)
    return data


def _normalise_field(spec: dict[str, Any]) -> dict[str, Any]:
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ValueError(f"field {spec.get('name')!r}: kind {kind!r} not in {list(KINDS)}")
    name = spec.get("name", "")
    if not _NAME.match(name):
        raise ValueError(f"field name {name!r} must match {_NAME.pattern}")
    if name == "rows":
        raise ValueError("field name 'rows' is reserved")
    out: dict[str, Any] = {
        "name": name,
        "label": spec.get("label") or name,
        "kind": kind,
        "required": bool(spec.get("required", False)),
        "help": spec.get("help") or "",
        "value": spec.get("value"),
    }
    if kind == "enum":
        options = spec.get("options") or []
        if not options:
            raise ValueError(f"field {name!r}: enum needs options")
        out["options"] = [str(o) for o in options]
        if out["value"] is not None and out["value"] not in out["options"]:
            raise ValueError(f"field {name!r}: value {out['value']!r} is not one of the options")
    if kind == "score":
        out["anchors"] = list(spec.get("anchors") or [])
        if out["value"] is not None and out["value"] not in (1, 2, 3, 4):
            raise ValueError(f"field {name!r}: score value must be 1-4")
    if kind == "evidence_score":
        out["anchors"] = list(spec.get("anchors") or [])
        if spec.get("not_observable"):
            out["not_observable"] = True  # decision 0031: a fifth choice, saved as {not_observable: true, note}
        v = out["value"]
        unseen = (out.get("not_observable") and isinstance(v, dict) and v.get("not_observable") is True
                  and "score" not in v and isinstance(v.get("note"), str) and v["note"].strip())
        if v is not None and not unseen and not (
            isinstance(v, dict) and "not_observable" not in v and type(v.get("score")) is int and v["score"] in (1, 2, 3, 4)
            and isinstance(v.get("note"), str) and v["note"].strip()
            and isinstance(v.get("timestamp", ""), str)
        ):
            raise ValueError(f"field {name!r}: an evidence_score value is {{score: 1-4, note: text, timestamp?: text}}"
                             + (" or {not_observable: true, note: text}" if out.get("not_observable") else ""))
    if kind == "checklist":
        out["items"] = _checklist_items(name, spec.get("items"))
        if out["value"] is not None:
            raise ValueError(f"field {name!r}: a checklist cannot be pre-filled")
    if kind == "number":
        for bound in ("min", "max"):
            if spec.get(bound) is not None:
                if not _is_number(spec[bound]):
                    raise ValueError(f"field {name!r}: {bound} must be a finite number")
                out[bound] = spec[bound]
        if "min" in out and "max" in out and out["min"] > out["max"]:
            raise ValueError(f"field {name!r}: min is above max")
        v = out["value"]
        if v is not None and not (_is_number(v) and ("min" not in out or v >= out["min"])
                                  and ("max" not in out or v <= out["max"])):
            raise ValueError(f"field {name!r}: value must be a number within min and max")
    return out


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _checklist_items(name: str, items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list) or not items:
        raise ValueError(f"field {name!r}: a checklist needs a non-empty list of items")
    out: list[dict[str, str]] = []
    for item in items:
        if not (isinstance(item, dict) and isinstance(item.get("id"), str) and _NAME.match(item["id"])
                and isinstance(item.get("label"), str) and item["label"].strip()):
            raise ValueError(f"field {name!r}: each checklist item needs an id matching {_NAME.pattern} and a label")
        out.append({"id": item["id"], "label": item["label"]})
    if len({i["id"] for i in out}) != len(out):
        raise ValueError(f"field {name!r}: checklist item ids must be unique")
    return out


def _element_ids(f: dict[str, Any]) -> list[str]:
    """Every HTML id a normalised field puts on the page, so two fields cannot clash."""
    fid = f"f-{f['name']}"
    ids = [fid, f"h-{fid}"]
    if f["kind"] in ("score", "evidence_score"):
        ids += [f"{fid}-{p}" for p in (1, 2, 3, 4)]
    if f["kind"] == "evidence_score":
        ids += [f"{fid}-note", f"{fid}-ts"] + ([f"{fid}-no"] if f.get("not_observable") else [])
    if f["kind"] == "checklist":
        for item in f["items"]:
            base = f"{fid}-{item['id']}"
            ids += [f"{base}-pass", f"{base}-fail", f"{base}-note"]
    return ids


def _field_html(f: dict[str, Any]) -> str:
    name, fid = f["name"], f"f-{f['name']}"
    star = ' <span class="req" aria-hidden="true">*</span>' if f["required"] else ""
    req = ' aria-required="true"' if f["required"] else ""
    help_html = f'<p class="help" id="h-{fid}">{_esc(f["help"])}</p>' if f["help"] else ""
    described = f' aria-describedby="h-{fid}"' if f["help"] else ""
    value = f["value"]
    kind = f["kind"]
    if kind == "score":
        return (
            f'<fieldset class="field"{described}><legend>{_esc(f["label"])}{star}</legend>{help_html}'
            + _score_options(f, value, "") + "</fieldset>"
        )
    if kind == "evidence_score":
        return _evidence_html(f, star, described, help_html)
    if kind == "checklist":
        return _checklist_html(f, star, described, help_html)
    if kind == "bool":
        checked = " checked" if value else ""
        return (
            f'<div class="field">{help_html}<label class="check" for="{fid}"><input type="checkbox" id="{fid}" '
            f'data-f="{name}"{req}{checked}> {_esc(f["label"])}{star}</label></div>'
        )
    if kind == "enum":
        options = ['<option value="">-- choose --</option>']
        for o in f["options"]:
            sel = " selected" if o == value else ""
            options.append(f'<option value="{_esc(o)}"{sel}>{_esc(o)}</option>')
        control = f'<select id="{fid}" data-f="{name}"{req}{described}>' + "".join(options) + "</select>"
    elif kind == "textarea":
        control = f'<textarea id="{fid}" data-f="{name}" rows="4"{req}{described}>{_esc(value or "")}</textarea>'
    elif kind == "number":
        bounds = "".join(f' {b}="{_esc(f[b])}"' for b in ("min", "max") if b in f)
        shown = "" if value is None else _esc(value)
        control = f'<input type="number" id="{fid}" data-f="{name}" step="any"{bounds} value="{shown}"{req}{described}>'
    else:
        itype = "date" if kind == "date" else "text"
        control = f'<input type="{itype}" id="{fid}" data-f="{name}" value="{_esc(value or "")}"{req}{described}>'
    return f'<div class="field"><label for="{fid}">{_esc(f["label"])}{star}</label>{help_html}{control}</div>'


def _score_options(f: dict[str, Any], selected: Any, part: str) -> str:
    """The 1-4 radio buttons of a score field, each with its rubric anchor. `part` is an extra attribute for the input."""
    name, fid = f["name"], f"f-{f['name']}"
    opts = []
    for p in (1, 2, 3, 4):
        anchor = next((a for a in f["anchors"] if a.get("point") == p), None)
        text = f"{p}" if anchor is None else f"{p} - {_esc(anchor['label'])}"
        sub = f'<span class="anchor">{_esc(anchor["text"])}</span>' if anchor else ""
        checked = " checked" if selected == p else ""
        opts.append(
            f'<label class="opt" for="{fid}-{p}"><input type="radio" id="{fid}-{p}" name="{fid}" '
            f'data-f="{name}"{part} value="{p}"{checked}>{text}{sub}</label>'
        )
    return "".join(opts)


def _evidence_html(f: dict[str, Any], star: str, described: str, help_html: str) -> str:
    """A 1-4 score with its anchors, a required evidence note and an optional recording timestamp."""
    name, fid = f["name"], f"f-{f['name']}"
    value = f["value"] or {}
    note = (
        f'<label class="sub" for="{fid}-note">Evidence note <span class="req" aria-hidden="true">*</span></label>'
        f'<textarea id="{fid}-note" data-f="{name}" data-part="note" rows="3" aria-required="true">'
        f'{_esc(value.get("note", ""))}</textarea>'
    )
    stamp = (
        f'<label class="sub" for="{fid}-ts">Recording timestamp (optional)</label>'
        f'<input type="text" id="{fid}-ts" data-f="{name}" data-part="timestamp" maxlength="40" '
        f'value="{_esc(value.get("timestamp", ""))}">'
    )
    unseen = ""
    if f.get("not_observable"):
        checked = " checked" if value.get("not_observable") is True else ""
        unseen = (f'<label class="opt" for="{fid}-no"><input type="radio" id="{fid}-no" name="{fid}" '
                  f'data-f="{name}" data-part="score" value="no"{checked}>Not observable in this slice'
                  '<span class="anchor">The slice did not show this domain. Say why in the note; it is kept out of '
                  'every average.</span></label>')
    return (
        f'<fieldset class="field"{described}><legend>{_esc(f["label"])}{star}</legend>{help_html}'
        + _score_options(f, value.get("score"), ' data-part="score"') + unseen + note + stamp + "</fieldset>"
    )


def _checklist_html(f: dict[str, Any], star: str, described: str, help_html: str) -> str:
    """Each item is passed or failed, with a note (required for a failed item)."""
    name, fid = f["name"], f"f-{f['name']}"
    rows = []
    for item in f["items"]:
        base = f"{fid}-{item['id']}"
        pills = "".join(
            f'<label class="opt" for="{base}-{v}"><input type="radio" id="{base}-{v}" name="{base}" data-f="{name}" '
            f'data-part="result" data-item="{item["id"]}" value="{v}"> {v.capitalize()}</label>'
            for v in ("pass", "fail")
        )
        rows.append(
            f'<div class="row"><span class="key">{_esc(item["label"])}</span><div class="pills">{pills}</div>'
            f'<label class="sub" for="{base}-note">Note (required for a failed item)</label>'
            f'<textarea id="{base}-note" data-f="{name}" data-part="note" data-item="{item["id"]}" rows="2"></textarea></div>'
        )
    return (
        f'<fieldset class="field"{described}><legend>{_esc(f["label"])}{star}</legend>{help_html}'
        + "".join(rows) + "</fieldset>"
    )


_REPO_PATH = re.compile(r"^(?:docs|contracts|standards)/[\w./-]+\.(?:md|json|yaml)$")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_PARA = re.compile(r"\u00b6(\d+)")


class _Links:
    """Resolves the links of one page: a repository path becomes an anchor in the page's appendix, and every document
    and web address the page links to is remembered for the appendix."""

    def __init__(self, root: Path | None) -> None:
        self.root = root
        self.citer = Citer(root) if root is not None else None
        self.docs: list[str] = []
        self.web: dict[str, str] = {}  # url -> access date ("" when the source records none)

    def _exists(self, rel: str) -> bool:
        return self.root is not None and (self.root / rel).is_file()

    def href(self, target: str, text: str) -> str:
        if target.startswith(("http://", "https://")):
            self.web.setdefault(target, "")
            return target
        path, _, anchor = target.partition("#")
        if not (_REPO_PATH.match(path) and self._exists(path)):
            return target
        if path not in self.docs:
            self.docs.append(path)
        out = "#" + _ref_id(path)
        if anchor:
            out += "-" + anchor
            para = _PARA.search(text)
            if para:
                out += f"-p{para.group(1)}"
        return out

    def text(self, s: str) -> str:
        """Markdown for a text value: bare decision mentions become citations when the repository is known."""
        if self.citer is None:
            return s
        try:
            return self.citer.mentions(s)
        except CitationError:
            return s


def _ref_id(path: str) -> str:
    return "ref-" + re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")


def _label(key: str) -> str:
    """A heading for an input key: "it_request_text" -> "It request text"; a URI key stays as written."""
    if ":" in key or "/" in key:
        return key
    words = [_ACRONYMS.get(w, w) for w in key.replace("_", " ").replace("-", " ").split()]
    s = " ".join(words)
    return s[:1].upper() + s[1:]


_ACRONYMS = {"dpia": "DPIA", "id": "ID", "url": "URL", "sha256": "SHA-256", "dpo": "DPO", "it": "IT", "ropa": "ROPA",
             "eea": "EEA", "uri": "URI"}


def _review(part_id: str) -> str:
    return f'<label class="review"><input type="checkbox" data-review="{_esc(part_id)}"> Reviewed</label>'


def _is_markdown(s: str) -> bool:
    return "\n" in s


def _scalar_html(value: Any, links: _Links) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if not isinstance(value, str):
        return _esc(value)
    if _HEX.match(value):
        return f"<code>{value}</code>"
    if _REPO_PATH.match(value) and links._exists(value):
        return mdlite.inline(f"[{value}]({value})", links.href)
    if _is_markdown(value):
        return mdlite.to_html(links.text(value), heading_offset=3, href=links.href)
    return mdlite.inline(links.text(value), links.href)


def _record_table(rows: list[dict[str, Any]], links: _Links) -> str | None:
    """A list of flat records as a table, or None when the records are not flat. A record with a `url` and an
    `accessed` date records when that web source was read."""
    if not rows or not all(isinstance(r, dict) and r for r in rows):
        return None
    keys: list[str] = []
    for r in rows:
        for k, v in r.items():
            if isinstance(v, (dict, list)) and not (isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v)):
                return None
            if k not in keys:
                keys.append(k)
    for r in rows:
        if isinstance(r.get("url"), str):
            links.web[r["url"]] = str(r.get("accessed") or links.web.get(r["url"], ""))
    head = "".join(f"<th>{_esc(_label(k))}</th>" for k in keys)
    body = []
    for r in rows:
        cells = []
        for k in keys:
            v = r.get(k)
            cells.append("<td>" + (", ".join(_scalar_html(x, links) for x in v) if isinstance(v, list)
                                   else ("" if v is None else _scalar_html(v, links))) + "</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _value_html(value: Any, links: _Links | None = None) -> str:
    links = links or _Links(None)
    if isinstance(value, dict):
        if not value:
            return "(none)"
        rows = "".join(f"<tr><th>{_esc(_label(k))}</th><td>{_value_html(v, links)}</td></tr>" for k, v in value.items())
        return f'<table class="kv"><tbody>{rows}</tbody></table>'
    if isinstance(value, list):
        if not value:
            return "(none)"
        table = _record_table(value, links)
        if table is not None:
            return table
        return "<ul>" + "".join(f"<li>{_value_html(v, links)}</li>" for v in value) + "</ul>"
    return _scalar_html(value, links)


def _inputs_html(inputs: dict[str, Any], links: _Links) -> tuple[str, list[tuple[str, str]]]:
    """The inputs as reviewable sections: (html, [(section id, title)]).

    Scalars at the top level form a "Summary" table. Every other top-level key is a section; inside a record, each
    key that holds a list or a record is a sub-section. A single markdown text is laid out by its own headings."""
    parts: list[tuple[str, str]] = []
    out: list[str] = []

    def section(level: int, pid: str, title: str, body: str) -> None:
        parts.append((pid, title))
        out.append(f'<section class="part" id="{_esc(pid)}"><h{level}>{_esc(title)}{_review(pid)}</h{level}>{body}'
                   "</section>")

    texts = [k for k, v in inputs.items() if isinstance(v, str) and _is_markdown(v)]
    if len(inputs) == 1 and texts:
        def extra(level: int, title: str) -> str:
            if level > 4:
                return ""
            pid = "part-" + mdlite.slug(title)
            parts.append((pid, title))
            return _review(pid)
        body = mdlite.to_html(links.text(inputs[texts[0]]), heading_offset=2, href=links.href, heading_extra=extra,
                              id_prefix="part-")
        if not parts:
            parts.append(("part-text", _label(texts[0])))
            body = f'<h3>{_esc(_label(texts[0]))}{_review("part-text")}</h3>' + body
        return f'<div class="doc">{body}</div>', parts

    scalars = {k: v for k, v in inputs.items() if not isinstance(v, (dict, list)) and not (isinstance(v, str) and _is_markdown(v))}
    if scalars:
        section(3, "part-summary", "Summary", _value_html(scalars, links))
    for k, v in inputs.items():
        if k in scalars:
            continue
        pid = "part-" + mdlite.slug(_label(k))
        if isinstance(v, dict) and any(isinstance(x, (dict, list)) for x in v.values()):
            flat = {kk: vv for kk, vv in v.items() if not isinstance(vv, (dict, list))}
            parts.append((pid, _label(k)))
            inner = [_value_html(flat, links)] if flat else []
            for kk, vv in v.items():
                if kk in flat:
                    continue
                sub = f"{pid}-{mdlite.slug(_label(kk))}"
                parts.append((sub, f"{_label(k)}: {_label(kk)}"))
                inner.append(f'<section class="part" id="{_esc(sub)}"><h4>{_esc(_label(kk))}{_review(sub)}</h4>'
                             f"{_value_html(vv, links)}</section>")
            out.append(f'<section class="part" id="{_esc(pid)}"><h3>{_esc(_label(k))}{_review(pid)}</h3>'
                       + "".join(inner) + "</section>")
        else:
            section(3, pid, _label(k), _value_html(v, links))
    return "".join(out), parts


def _contents_html(parts: list[tuple[str, str]], has_refs: bool) -> str:
    if len(parts) < 3 and not has_refs:
        return ""
    items = "".join(f'<li><a href="#{_esc(pid)}">{_esc(title)}</a></li>' for pid, title in parts)
    if has_refs:
        items += '<li><a href="#references">Referenced documents</a></li>'
    return f'<nav class="contents" aria-label="Contents"><h3>Contents</h3><ol>{items}</ol></nav>'


_APPENDIX: dict[tuple[str, str], str] = {}


def _document_html(root: Path, rel: str) -> str:
    """One referenced repository document, numbered as citations number it; cached per file content."""
    data = (root / rel).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    key = (str(root / rel), digest)
    cached = _APPENDIX.get(key)
    if cached is not None:
        return cached
    rid = _ref_id(rel)
    text = data.decode("utf-8").replace("\r\n", "\n")
    if rel.endswith(".md"):
        doc = load_document(root, rel)
        body_text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
        body_text = re.sub(r"\A\s*#\s+.*\n", "", body_text)
        body = mdlite.to_html(body_text, heading_offset=2, id_prefix=rid + "-", numbered=True)
        title = f"{doc.short}: {doc.title}" if doc.short != rel else doc.title
        status = " ".join(x for x in (doc.status, doc.date) if x)
    else:
        body = f"<pre>{_esc(text)}</pre>"
        title, status = rel, ""
        if rel.endswith(".json"):
            try:
                schema = json.loads(text)
                title = f"{rel}: {schema.get('title', '')}".rstrip(": ")
                status = str(schema.get("$id", ""))
            except ValueError:
                pass
    meta = f"<code>{_esc(rel)}</code>" + (f" &middot; {_esc(status)}" if status else "") + \
        f" &middot; sha256 <code>{digest[:12]}</code>"
    html_ = (f'<details class="ref" id="{rid}"><summary>{_esc(title)}</summary>'
             f'<p class="help">Copied from the repository: {meta}</p>{body}</details>')
    _APPENDIX[key] = html_
    return html_


def _references_html(links: _Links) -> str:
    if not links.docs and not links.web:
        return ""
    out = ['<section class="card" id="references"><h2>Referenced documents</h2>']
    if links.docs and links.root is not None:
        out.append('<p class="help">Each repository document cited on this page, as it stands in the repository. '
                   "Citations name the section (§) and paragraph (¶); paragraphs are numbered in each section in "
                   "order, from 1.</p>")
        out += [_document_html(links.root, rel) for rel in links.docs]
    if links.web:
        rows = "".join(
            f'<tr><td><a href="{_esc(u)}" target="_blank" rel="noopener">{_esc(u)}</a></td>'
            f"<td>{_esc(d) if d else 'not recorded in the source'}</td></tr>"
            for u, d in links.web.items())
        out.append('<h3>Web sources</h3><div class="scroll"><table><thead><tr><th>Address</th><th>Accessed</th></tr>'
                   f"</thead><tbody>{rows}</tbody></table></div>")
    out.append("</section>")
    return "".join(out)


def _row_html(i: int, row: dict[str, Any]) -> str:
    key, summary = _esc(row["key"]), _esc(row.get("summary", ""))
    head = f'<span class="key">{key}</span><br>{summary}'
    if row.get("changed", True) is False:
        return f'<div class="row">{head}</div>'
    pills = "".join(
        f'<label class="opt"><input type="radio" name="row-{i}" value="{v}"> {v.capitalize()}</label>'
        for v in ("approve", "reject")
    )
    return f'<div class="row" data-row="{i}">{head}<div class="pills">{pills}</div></div>'


def _rows(inputs: dict[str, Any]) -> tuple[str, str, int, int]:
    rows = inputs.get("rows")
    if not isinstance(rows, list):
        raise ValueError("batch_approve inputs need a 'rows' list of {key, summary, changed}")
    keys = [r.get("key") for r in rows]
    if any(not k for k in keys) or len(set(keys)) != len(keys):
        raise ValueError("batch_approve rows need unique non-empty keys")
    changed = [(i, r) for i, r in enumerate(rows) if r.get("changed", True) is not False]
    unchanged = [(i, r) for i, r in enumerate(rows) if r.get("changed", True) is False]
    return (
        "".join(_row_html(i, r) for i, r in changed) or '<p class="help">No rows changed.</p>',
        "".join(_row_html(i, r) for i, r in unchanged) or '<p class="help">No unchanged rows.</p>',
        len(changed),
        len(unchanged),
    )


def _channel_html(channel: dict[str, Any]) -> str:
    kind = channel.get("kind")
    if kind == "library":
        path = channel.get("path")
        if not path:
            raise ValueError("library channel needs a path")
        return (
            '<section class="card"><h2>Where to send it</h2>'
            f"<p>Save the downloaded file, unchanged, into the library folder <code>{_esc(path)}</code>.</p></section>"
        )
    if kind == "mail":
        to = channel.get("to", "")
        if not _MAIL.match(to):
            raise ValueError(f"mail channel needs a valid 'to' address, got {to!r}")
        href = f"mailto:{quote(to, safe='@')}?subject={quote('[tm-signoff <id>]', safe='')}"
        return (
            '<section class="card"><h2>Where to send it</h2>'
            "<p>Saving downloads an email draft (<code>.eml</code>) addressed to "
            f"<code>{_esc(to)}</code>, with the subject <code data-subject>[tm-signoff &lt;id&gt;]</code> and the "
            "sign-off file attached. Open it in Outlook from your own work mailbox and press Send.</p>"
            "<p>If the draft does not open as a new message: download the sign-off file alone, then email it as an "
            "attachment with that subject.</p>"
            '<p><button type="button" id="tm-json" hidden>Download the sign-off file alone</button> '
            f'<a id="tm-mailto" href="{_esc(href)}" hidden>Open an email with the subject filled in</a></p></section>'
        )
    raise ValueError(f"channel kind must be 'library' or 'mail', got {kind!r}")


def _json_for_script(obj: Any) -> str:
    """JSON safe inside a <script> block: every '<', '>' and '&' becomes a \\u escape."""
    text = json.dumps(obj, ensure_ascii=True, sort_keys=False, indent=1)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render(
    template: str,
    *,
    step: str,
    subject_uri: str,
    signer: str,
    role: str,
    inputs: dict[str, Any],
    fields: list[dict[str, Any]],
    channel: dict[str, Any],
    title: str,
    intro: str = "",
    root: Path | None = None,
) -> tuple[str, str]:
    """Render one sign-off page. Returns (html, input_sha256).

    `root` is the repository the inputs come from; with it, the repository documents the page cites are copied into
    the page. Neither it nor the intro is part of the input hash."""
    template_hash = template_sha256(template)  # also validates the template name
    if not _STEP.match(step):
        raise ValueError(f"step {step!r} must start with tm:step/")
    if not _SUBJECT.match(subject_uri):
        raise ValueError(f"subject_uri {subject_uri!r} must start with tm: or sl:")
    if not _SIGNER.match(signer):
        raise ValueError(f"signer {signer!r} must be tm:person/... or tm:instructor/...")
    norm = [_normalise_field(f) for f in fields]
    names = [f["name"] for f in norm]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate field names in {names}")
    ids = [i for f in norm for i in _element_ids(f)]
    clashes = sorted({i for i in ids if ids.count(i) > 1})
    if clashes:
        raise ValueError(f"field ids clash on the page: {clashes}")
    digest = input_sha256(inputs)

    changed_html = unchanged_html = ""
    changed_n = unchanged_n = 0
    shown = inputs
    if template == "batch_approve":
        changed_html, unchanged_html, changed_n, unchanged_n = _rows(inputs)
        shown = {k: v for k, v in inputs.items() if k != "rows"}

    links = _Links(Path(root) if root is not None else None)
    intro_html = mdlite.to_html(links.text(intro), heading_offset=2, href=links.href)
    inputs_html = ""
    if shown:
        parts_html, parts = _inputs_html(shown, links)
        inputs_html = _contents_html(parts, bool(links.docs or links.web)) + parts_html
    references = _references_html(links)

    data = {
        "schema": SIGNOFF_SCHEMA,
        "template": template,
        "step": step,
        "subject_uri": subject_uri,
        "signer": signer,
        "role": role,
        "input_sha256": digest,
        "page_template_sha256": template_hash,
        "channel": channel,
        "fields": norm,
        "inputs": inputs,
    }
    body = Template(_template_bytes(template).decode("utf-8")).substitute(
        intro_html=intro_html,
        inputs_html=inputs_html,
        fields_html="".join(_field_html(f) for f in norm),
        changed_rows_html=changed_html,
        unchanged_rows_html=unchanged_html,
        changed_count=changed_n,
        unchanged_count=unchanged_n,
    )
    meta = (
        f"Step <code>{_esc(step)}</code> &middot; subject <code>{_esc(subject_uri)}</code> &middot; "
        f"signing as <code>{_esc(signer)}</code> ({_esc(role)})"
    )
    page = Template(_template_bytes("base").decode("utf-8")).substitute(
        title=_esc(title),
        meta_html=meta,
        content_html=body + references,
        channel_html=_channel_html(channel),
        data_json=_json_for_script(data),
    )
    return page, digest


def write_page(out_dir: Path, filename_stem: str, page_html: str, inputs: dict[str, Any]) -> tuple[Path, Path]:
    """`write_page_if_changed`, returning the two paths."""
    return write_page_if_changed(out_dir, filename_stem, page_html, inputs)[:2]


def write_page_if_changed(
    out_dir: Path, filename_stem: str, page_html: str, inputs: dict[str, Any]
) -> tuple[Path, Path, bool]:
    """Write `<stem>.html` and `<stem>.input.json` (canonical inputs, LF, no trailing newline), each only if the file does
    not already hold exactly those bytes. Returns (page, sidecar, whether either was written): a tick renders every due page
    and most are the same as the last tick's.

    The sidecar is a written record of what the page showed, for a human to read. Ingest never reads it:
    it re-derives the current inputs from the store with the same builder `pages` used (app.py), so a
    stale or edited sidecar cannot make a sign-off current.
    Callers pass a directory under the private store; this module does not resolve configuration.
    """
    if not _NAME.match(filename_stem):
        raise ValueError(f"filename stem {filename_stem!r} must be lowercase letters, digits, '-' or '_'")
    out_dir = Path(out_dir)
    html_path = out_dir / f"{filename_stem}.html"
    sidecar = out_dir / f"{filename_stem}.input.json"
    wrote_html = write_if_changed(html_path, page_html.encode("utf-8"))
    wrote_sidecar = write_if_changed(sidecar, events.canonical(inputs).encode("utf-8"))
    return html_path, sidecar, wrote_html or wrote_sidecar
