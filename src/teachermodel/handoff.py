"""`teachermodel handoff --unit <uri>`: the expert-to-session handoff for a unit (spec v0.2, Build phases 6; increment 4
item 7). Renders standards/templates/expert-to-session.md with the unit file's content into
`generated/handoff/<unit>.md` in the store, and lists what the unit still lacks before a dry run. Deterministic; no person's
data (authors are instructor ids)."""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any

from . import app, units
from .standards import ROOT

TEMPLATE = Path("standards") / "templates" / "expert-to-session.md"


def _list(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (none in the unit file)"


def missing(unit: dict[str, Any]) -> list[str]:
    """What a unit needs before an expert can take it to a dry run: outcomes, an environment, a pre-check, misconceptions,
    a failure catalogue and at least one author."""
    out = []
    for key, what in (("learning_outcomes", "learning outcomes"), ("environment", "the lab environment"),
                      ("pre_check", "a diagnostic pre-check"), ("misconceptions", "misconceptions"),
                      ("failure_catalogue", "a failure catalogue"), ("authors", "an author (the expert's instructor id)")):
        if not unit.get(key):
            out.append(f"{what} (`{key}` in the unit file)")
    return out


def render(unit: dict[str, Any], root: Path = ROOT) -> str:
    text = (Path(root) / TEMPLATE).read_text(encoding="utf-8")
    gaps = missing(unit)
    return Template(text).substitute(
        title=unit.get("title", unit["id"]), unit_id=unit["id"],
        outcomes=_list(unit.get("learning_outcomes", [])),
        modes=", ".join(unit.get("delivery_modes", [])) or "(none)",
        environment=unit.get("environment") or "(not stated)",
        pre_check=_list([f"{p.get('topic')}: {p.get('question')}" for p in unit.get("pre_check", [])]),
        misconceptions=_list([f"{m.get('id')}: {m.get('statement')}" for m in unit.get("misconceptions", [])]),
        failure_catalogue=_list([f"{f.get('id')}: inject {f.get('inject')}; handling: {f.get('expected_handling')}"
                                 for f in unit.get("failure_catalogue", [])]),
        missing=_list(gaps) if gaps else "Nothing: the unit file is complete for a dry run.")


def write(private_dir: Path | str, unit_uri: str, *, root: Path = ROOT) -> app.Report:
    try:
        unit = units.load(unit_uri, root)
    except units.UnitError as exc:
        raise app.AppError(str(exc)) from exc
    private = Path(private_dir)
    target = private / "generated" / "handoff" / f"{unit_uri.split('/', 1)[1].replace('@', '-')}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(render(unit, root).encode("utf-8"))
    gaps = missing(unit)
    return app.Report(lines=[f"file: {target.relative_to(private).as_posix()}", *[f"missing: {g}" for g in gaps]],
                      summary=f"handoff: {unit_uri}, {len(gaps)} item(s) missing before the dry run")
