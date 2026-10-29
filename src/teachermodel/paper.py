"""`teachermodel paper --unit <uri>`: the printable run sheet and rubric for running a session with the system down
(spec v0.2, Acceptance: "a session can run from the paper run sheet and rubric with the system down, and its record is
entered afterwards without loss"; increment 4 item 6; decision 0022).

Writes `generated/paper/<unit slug>/run-sheet.html` (the unit's outcomes, modes, environment, pre-check with its routes,
misconceptions and failure catalogue, each with a tick box) and `rubric.html` (the observer's sheet: the session header,
each framework domain with its four anchors and boxes for the score and the evidence note). Both print on A4 and hold no
person's data: the header fields are filled by hand with ids. Entering the record afterwards: the coordinator opens an
ad-hoc assignment with `held_on` (the session's date, at most observation.PAPER_BACKDATE_DAYS back) and the observer
copies the sheet onto the observation page with that date.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import app, units
from .standards import ROOT, load_standards, load_yaml
from .util import esc as _e, slug, write_if_changed

STYLE = (
    "@page{size:A4;margin:14mm}body{font-family:Arial,Helvetica,sans-serif;color:#262838;font-size:10.5pt;line-height:1.35}"
    "h1{font-size:15pt;color:#12193E;margin:0 0 4mm}h2{font-size:12pt;color:#434D9E;border-bottom:1px solid #999;"
    "margin:5mm 0 2mm}table{border-collapse:collapse;width:100%}th,td{border:1px solid #999;padding:1.5mm 2mm;"
    "vertical-align:top;text-align:left}th{background:#eee}.box{display:inline-block;width:4mm;height:4mm;border:1px solid "
    "#333;margin-right:2mm}.line{border-bottom:1px solid #333;min-width:45mm;display:inline-block}.note{height:16mm}"
    ".domain{break-inside:avoid}footer{margin-top:5mm;font-size:8.5pt;color:#555}"
)


def _page(title: str, body: str, footer: str) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>{_e(title)}</title><style>{STYLE}</style>'
            f"</head><body><h1>{_e(title)}</h1>{body}<footer>{_e(footer)}</footer></body></html>\n")


def _header(fields: list[str]) -> str:
    return "<p>" + "&nbsp;&nbsp; ".join(f"{_e(f)}: <span class=\"line\"></span>" for f in fields) + "</p>"


def run_sheet(unit: dict[str, Any]) -> str:
    parts = [_header(["Date", "Delivery reference", "Instructor id", "Mode"])]
    parts.append("<h2>Learning outcomes</h2><ul>" + "".join(f"<li>{_e(o)}</li>" for o in unit.get("learning_outcomes", []))
                 + "</ul>")
    parts.append(f"<p>Modes: {_e(', '.join(unit.get('delivery_modes', [])))}. Environment: {_e(unit.get('environment'))}</p>")
    rows = [[f'<span class="box"></span>{_e(p.get("topic"))}', _e(p.get("question")),
             _e("; ".join(f"{k}: {v}" for k, v in (p.get("routes") or {}).items()))] for p in unit.get("pre_check", [])]
    parts.append("<h2>Pre-check</h2>" + _table(["Topic", "Question", "Routes"], rows))
    rows = [[f'<span class="box"></span>{_e(m.get("id"))}', _e(m.get("statement"))] for m in unit.get("misconceptions", [])]
    parts.append("<h2>Misconceptions to listen for</h2>" + _table(["Id", "Statement"], rows))
    rows = [[f'<span class="box"></span>{_e(f.get("id"))}', _e(f.get("inject")), _e(f.get("expected_handling"))]
            for f in unit.get("failure_catalogue", [])]
    parts.append("<h2>Failure catalogue</h2>" + _table(["Id", "Inject", "Expected handling"], rows))
    parts.append("<h2>Notes</h2><div class=\"note\"></div><div class=\"note\"></div>")
    return _page(f"Run sheet: {unit.get('title')} ({unit['id']})", "".join(parts),
                 "Paper fallback (decision 0022). Keep this sheet with the rubric; enter the record within 14 days.")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "<p>None in the unit file.</p>"
    return ("<table><thead><tr>" + "".join(f"<th>{_e(h)}</th>" for h in headers) + "</tr></thead><tbody>"
            + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>")


def rubric_sheet(unit: dict[str, Any], framework: dict[str, Any], rubric: dict[str, Any]) -> str:
    scale = rubric.get("scale", {})
    parts = [_header(["Date", "Delivery reference", "Instructor id", "Observer id"]),
             _header(["Length (full / 15-minute)", "Instructor led (yes / no)", "Mode", "From a recording (yes / no)"])]
    for d in framework.get("domains", []):
        anchors = rubric.get("anchors", {}).get(d["id"], {})
        rows = [[f'<span class="box"></span>{_e(p)} {_e(scale.get(p, ""))}', _e(anchors.get(p, ""))] for p in (1, 2, 3, 4)]
        parts.append(f'<div class="domain"><h2>{_e(d.get("name"))} ({_e(d["id"])})</h2>'
                     + _table(["Score", "Anchor"], rows) + "<p>Evidence note:</p><div class=\"note\"></div></div>")
    return _page(f"Observation rubric: {unit.get('title')} ({unit['id']})", "".join(parts),
                 "Score blind: do not compare with another observer before both records are entered. Paper fallback "
                 "(decision 0022).")


def write(private_dir: Path | str, unit_uri: str, *, root: Path = ROOT) -> app.Report:
    private = Path(private_dir)
    try:
        unit = units.load(unit_uri, root)
    except units.UnitError as exc:
        raise app.AppError(str(exc)) from exc
    std = load_standards(root)
    rubric = load_yaml(root / "standards" / "rubric.yaml")
    out = private / "generated" / "paper" / slug(unit_uri).replace("@", "-")
    write_if_changed(out / "run-sheet.html", run_sheet(unit).encode("utf-8"))
    write_if_changed(out / "rubric.html", rubric_sheet(unit, std["framework"], rubric).encode("utf-8"))
    rel = out.relative_to(private).as_posix()
    return app.Report(lines=[f"file: {rel}/run-sheet.html", f"file: {rel}/rubric.html"],
                      summary=f"paper: run sheet and rubric for {unit_uri}")
