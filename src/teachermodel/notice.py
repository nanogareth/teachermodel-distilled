"""Text helpers for the privacy notice and the record of processing (privacy-jurisdictions design section 4).

Pure string work: the callers pass the loaded purposes, profile and retention. The notice template carries one
marker per mandatory element of the base profile, for example `<!-- element: controller-identity -->`, on a line of
its own. An element's section is the text from its marker to the next marker or the next heading. Rendering is
blocked when a mandatory element has no marker or its section renders empty, and the markers are removed from the
text that is sent.

Unfinished text is marked in the template with `<!-- draft -->` on a line of its own, and the "DRAFT for legal review"
banner line is itself a draft marker. Rendering is blocked while any draft marker remains, and while the literal
placeholder "(to be " stands in an element's section (the generated retention text uses it for "not set yet"). The real
templates are drafts, so rendering them is blocked by design; a finished template has neither.

The notice tells the instructor what `notice_text` of each proposed basis says. The `reason` beside it is legal's
reasoning and is never printed here.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

MARKER = re.compile(r"^[ \t]*<!--[ \t]*element:[ \t]*([a-z0-9][a-z0-9-]*)[ \t]*-->[ \t]*$", re.M)
HEADING = re.compile(r"^#{1,6}[ \t]", re.M)
DRAFT_MARKER = re.compile(r"^[ \t]*<!--[ \t]*draft[ \t]*-->[ \t]*$", re.M)
BANNER = re.compile(r"^[ \t]*DRAFT for legal review\b.*$", re.M)
PLACEHOLDER = "(to be "


def basis_label(basis: str) -> str:
    return basis.replace("-", " ")


def _one_line(text: str) -> str:
    return " ".join(text.split())


# --- element markers --------------------------------------------------------------------------------


def sections(text: str) -> dict[str, str]:
    """element id -> the text of its section (stripped), for the first marker of each id."""
    out: dict[str, str] = {}
    marks = list(MARKER.finditer(text))
    for n, m in enumerate(marks):
        if m.group(1) in out:
            continue
        end = marks[n + 1].start() if n + 1 < len(marks) else len(text)
        heading = HEADING.search(text, m.end())
        if heading is not None and heading.start() < end:
            end = heading.start()
        out[m.group(1)] = text[m.end():end].strip()
    return out


def draft_problems(text: str) -> list[str]:
    """One line per kind of unfinished text left in the whole rendered text: `<!-- draft -->` markers and the
    "DRAFT for legal review" banner. (The "(to be " placeholder is checked inside element sections.)"""
    out: list[str] = []
    n = len(DRAFT_MARKER.findall(text))
    if n:
        out.append(f"notice template still has {n} draft marker(s) (<!-- draft -->): finish the text and remove them")
    if BANNER.search(text):
        out.append("notice template still carries its 'DRAFT for legal review' banner (a draft marker): it cannot be "
                   "rendered until legal has reviewed it and the banner is removed")
    return out


def element_problems(text: str, element_ids: Iterable[str]) -> list[str]:
    """One line per problem that stops a rendering: unfinished text (draft markers, the banner), a mandatory element with
    no marker in the rendered template, a section that is empty, and a section that still holds a "(to be " placeholder."""
    found = sections(text)
    out: list[str] = draft_problems(text)
    for eid in element_ids:
        if eid not in found:
            out.append(f"notice template has no marker for mandatory element {eid} (<!-- element: {eid} -->)")
        elif not found[eid]:
            out.append(f"section for mandatory element {eid} renders empty")
        elif PLACEHOLDER in found[eid]:
            out.append(f"section for mandatory element {eid} still holds placeholder text '{PLACEHOLDER}...)'")
    return out


SIMULATED_LINE = "SIMULATED DATA: generated for development. This is not a privacy notice."


def simulated(text: str) -> str:
    """The rendered text of a simulated store (decision 0020): its draft markers and the legal-review banner removed,
    and the SIMULATED DATA line first. Every other check (elements, placeholders) still runs on the result."""
    body = BANNER.sub("", DRAFT_MARKER.sub("", text))
    return SIMULATED_LINE + "\n\n" + re.sub(r"\n{3,}", "\n\n", body).lstrip("\n")


def strip_markers(text: str) -> str:
    """The text without its marker lines (element and draft markers)."""
    return re.sub(r"\n{3,}", "\n\n", DRAFT_MARKER.sub("", MARKER.sub("", text)))


# --- generated sections ------------------------------------------------------------------------------


def purposes_md(purposes: Mapping[str, Any], base_uri: str) -> tuple[str, list[str]]:
    """The notice's purposes with their legal basis for the jurisdiction, each followed by its `notice_text` (never its
    `reason`), and one reason per purpose that has no proposed basis (the notice must say what the basis is)."""
    lines: list[str] = []
    reasons: list[str] = []
    for p in purposes["purposes"]:
        prop = p.get("proposed_basis", {}).get(base_uri)
        if prop is None:
            reasons.append(f"purpose {p['id']} has no proposed basis for {base_uri}")
            continue
        lines.append(f"- {p['name']}: {_one_line(p['description'])} Legal basis: {basis_label(prop['basis'])}. "
                     f"{_one_line(prop['notice_text'])}")
    return "\n".join(lines), reasons


def purposes_ropa_md(
    purposes: Mapping[str, Any], category_titles: Mapping[str, str], profile_names: Mapping[str, str]
) -> str:
    """The record-of-processing view of the purposes: description, categories, workflows and every proposed basis."""
    lines: list[str] = []
    for p in purposes["purposes"]:
        lines.append(f"- {p['name']} ({p['id']}): {_one_line(p['description'])}")
        lines.append("  Data categories: " + ", ".join(category_titles.get(c, c) for c in p["categories"]) + ".")
        served = [*p["workflows"], *[f"{w} (planned)" for w in p.get("planned_workflows", [])]]
        if served:
            lines.append("  Workflows: " + ", ".join(served) + ".")
        for uri, prop in p.get("proposed_basis", {}).items():
            lines.append(f"  Proposed basis, {profile_names.get(uri, uri)} ({uri}): {basis_label(prop['basis'])}. "
                         f"{_one_line(prop['reason'])}")
    return "\n".join(lines) if lines else "No purposes yet."


def legitimate_interests_md(purposes: Mapping[str, Any], base_uri: str) -> str:
    lines = [f"- {p['name']}: {_one_line(p['proposed_basis'][base_uri]['notice_text'])}"
             for p in purposes["purposes"]
             if p.get("proposed_basis", {}).get(base_uri, {}).get("basis") == "legitimate-interests"]
    return "\n".join(lines) or "No purpose relies on legitimate interests."


def consent_md(purposes: Mapping[str, Any], base_uri: str) -> str:
    lines = [f"- {p['name']}" for p in purposes["purposes"]
             if p.get("proposed_basis", {}).get(base_uri, {}).get("basis") == "consent"]
    if not lines:
        return ("No purpose relies on your consent, so there is nothing to withdraw. If that changes you will be "
                "told first.")
    return ("These uses rest on your consent. You can withdraw it at any time, and withdrawing does not affect "
            "earlier use:\n" + "\n".join(lines))


def regulator_md(profile: Mapping[str, Any]) -> str:
    reg = profile["regulator"]
    where = f" ({reg['url']})" if reg.get("url") else ""
    return f"You can complain to the {reg['name']}{where}, the supervisory authority for this processing."


def lawful_basis_md(profile: Mapping[str, Any]) -> str:
    """The record-of-processing statement of the law that applies, from the base profile."""
    laws = "; ".join(law["name"] + (f" ({law['citation']})" if law.get("citation") else "") for law in profile["laws"])
    consent = ("Consent is not valid in employment here, so no purpose rests on it."
               if not profile["consent_valid_in_employment"] else "Consent can be valid in employment here.")
    return (f"Base profile {profile['id']} ({profile.get('name', profile['id'])}, status {profile['status']}): {laws}. "
            f"Regulator: {profile['regulator']['name']}. {consent} The bases above are proposals: internal legal "
            "confirms each when it verifies the profile, and an overlay profile adds the duties of an instructor's "
            "own jurisdiction (legal review).")


def titles(categories: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    return {c["id"]: c["title"] for c in categories}
