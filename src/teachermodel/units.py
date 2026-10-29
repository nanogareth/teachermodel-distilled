"""Units: the part of a curriculum unit that teachermodel reads, mirrored under standards/units/<slug>@<ver>.yaml.

A unit is `sl:unit/<slug>@<ver>`; its file is `standards/units/<slug>@<ver>.yaml` and validates against
`contracts/unit-requirements.schema.json`. `load(uri)` returns the validated document; `environment_sha256(unit)` is the
hash a dry run is bound to (the unit's environment, failure catalogue and, when present, run sheet), so changing any of
them voids earlier dry runs (see records.dry_runs).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from . import signoff, standards
from .standards import ROOT, load_yaml, memo, sha256_hex, validate

UNITS_DIR = "units"  # under standards/
_URI = re.compile(r"^sl:unit/([a-z0-9-]+)@([0-9]+)\Z")
SCHEMA = "unit-requirements.schema.json"


class UnitError(ValueError):
    """A unit URI is malformed or its file is missing or invalid; the message says which."""


def unit_files(root: Path = ROOT) -> list[Path]:
    """Every unit file, sorted by name."""
    return sorted((Path(root) / "standards" / UNITS_DIR).glob("*.yaml"), key=lambda p: p.name)


def document_errors(doc: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Schema errors of a unit document, plus what the schema cannot say: failure ids and run-sheet step ids are unique."""
    errors = validate(doc, SCHEMA, root)
    if errors:
        return errors
    for key in ("failure_catalogue", "run_sheet"):
        ids = [item["id"] for item in doc.get(key, [])]
        errors += [f"{key}: duplicate id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return errors


def load(uri: str, root: Path = ROOT) -> dict[str, Any]:
    """The unit `uri` (`sl:unit/<slug>@<ver>`), read from standards/units and validated. A fresh dict on every call.

    The parsed, validated document is kept per content (the bytes of the unit file and of the schema, so an edit to either
    is a different key), because a dry-run page asks for the same unit once per candidate and mode; a unit that fails is
    never kept. The caller gets a deep copy, so changing it changes nothing for the next caller."""
    m = _URI.match(uri) if isinstance(uri, str) else None
    if m is None:
        raise UnitError(f"{uri!r} is not a unit URI (sl:unit/<slug>@<version>)")
    path = Path(root) / "standards" / UNITS_DIR / f"{m.group(1)}@{m.group(2)}.yaml"
    if not path.is_file():
        raise UnitError(f"no unit file for {uri} (expected standards/{UNITS_DIR}/{path.name})")
    data = path.read_bytes()
    schema = (Path(root) / "contracts" / SCHEMA).read_bytes()

    def read() -> dict[str, Any]:
        doc = standards.parse_yaml(data)
        errors = document_errors(doc, root) if isinstance(doc, dict) else ["<root>: not a mapping"]
        if errors:
            raise UnitError(f"{path.name}: " + "; ".join(errors))
        if doc["id"] != uri:
            raise UnitError(f"{path.name}: id {doc['id']} is not {uri}")
        return doc

    return copy.deepcopy(memo(("unit", uri, sha256_hex(data), sha256_hex(schema)), read))


def environment_sha256(unit: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of `{environment, failure_catalogue, run_sheet?}` (run_sheet only when the unit has
    one). The rest of the unit (title, outcomes, pre-check, misconceptions, modes, status) does not move it."""
    body = {"environment": unit["environment"], "failure_catalogue": unit["failure_catalogue"]}
    if "run_sheet" in unit:
        body["run_sheet"] = unit["run_sheet"]
    return signoff.input_sha256(body)


def authors(unit: dict[str, Any]) -> list[str]:
    """The unit's SME authors (`tm:instructor/...`), sorted; empty for a unit that lists none (W12)."""
    return sorted(unit.get("authors", []))


def check_units(root: Path = ROOT) -> list[str]:
    """Errors of every unit file: schema, unique ids, and a file name that is its id (`<slug>@<ver>.yaml`)."""
    errors: list[str] = []
    for path in unit_files(root):
        doc = load_yaml(path)
        found = document_errors(doc, root) if isinstance(doc, dict) else ["<root>: not a mapping"]
        errors += [f"units/{path.name}: {e}" for e in found]
        if not found and doc["id"] != "sl:unit/" + path.stem:
            errors.append(f"units/{path.name}: id {doc['id']} does not match the file name")
    return errors
