"""Units: a local, pinned mirror of the curriculum units teachermodel reads (standards/units/<slug>@<ver>.yaml).

`units.load(uri)` returns the validated document (contracts/unit-requirements.schema.json);
`units.environment_sha256(unit)` is the hash a dry run is bound to. Fictional data only.
"""

import copy
import hashlib
import json
import shutil

import pytest
import yaml

from teachermodel import roster, units
from teachermodel.standards import ROOT, check_standards, validate

UNIT = "sl:unit/example-agent-loop@1"


def example():
    return units.load(UNIT)


def test_the_example_unit_loads_and_is_valid():
    unit = example()
    assert unit["id"] == UNIT and unit["failure_catalogue"] and unit["environment"]
    assert validate(unit, "unit-requirements.schema.json") == []


def test_the_example_moved_out_of_templates():
    assert (ROOT / "standards" / "units" / "example-agent-loop@1.yaml").is_file()
    assert not (ROOT / "standards" / "templates" / "unit-requirements.yaml").exists()


def test_every_unit_the_example_roster_delivers_loads():
    doc = roster.load(ROOT / "standards" / "templates" / "roster.example.yaml")
    wanted = {d["unit"] for row in doc["instructors"] for d in row.get("delivers", [])}
    assert wanted and {units.load(u)["id"] for u in wanted} == wanted


def test_load_returns_a_fresh_document_each_time():
    a = example()
    a["environment"] = "changed by the caller"
    assert example()["environment"] != "changed by the caller"


def test_a_unit_file_is_parsed_and_validated_once_per_content(tmp_path, monkeypatch):
    # integration review finding 8: a dry-run page asked for the same unit file once per candidate and mode
    from teachermodel import standards

    root = tmp_path / "root"
    shutil.copytree(ROOT / "standards" / "units", root / "standards" / "units")
    shutil.copytree(ROOT / "contracts", root / "contracts")
    path = root / "standards" / "units" / "example-agent-loop@1.yaml"
    path.write_bytes(path.read_bytes() + b"# a content nobody has loaded\n")
    parsed = []
    real = standards.parse_yaml
    monkeypatch.setattr(standards, "parse_yaml", lambda data: (parsed.append(len(data)), real(data))[1])
    first = units.load(UNIT, root)
    for _ in range(5):
        assert units.load(UNIT, root) == first
    assert len(parsed) == 1
    first["environment"] = "changed by the caller"  # the cache hands out copies, not its own document
    assert units.load(UNIT, root)["environment"] != "changed by the caller"
    path.write_bytes(path.read_bytes().replace(b"environment:", b"environment: edited ", 1))  # an edit is seen at once
    assert "edited" in units.load(UNIT, root)["environment"] and len(parsed) == 2


def test_a_unit_that_fails_validation_is_not_cached(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(ROOT / "standards" / "units", root / "standards" / "units")
    shutil.copytree(ROOT / "contracts", root / "contracts")
    path = root / "standards" / "units" / "example-agent-loop@1.yaml"
    good = path.read_bytes()
    path.write_bytes(b"id: sl:unit/example-agent-loop@1\n")
    with pytest.raises(units.UnitError):
        units.load(UNIT, root)
    with pytest.raises(units.UnitError):
        units.load(UNIT, root)
    path.write_bytes(good)
    assert units.load(UNIT, root)["id"] == UNIT


@pytest.mark.parametrize("uri", [
    "", "example-agent-loop@1", "tm:unit/example-agent-loop@1", "sl:unit/example-agent-loop", "sl:unit/example-agent-loop@",
    "sl:unit/example-agent-loop@x", "sl:unit/../standards@1", "sl:unit/a/b@1", "sl:unit/Example@1", "sl:unit/a@1/../..",
    "sl:unit/example-agent-loop@1\n", None, 7,
])
def test_a_malformed_uri_is_refused(uri):
    with pytest.raises(units.UnitError, match="unit URI"):
        units.load(uri)


def test_an_unknown_unit_is_refused_naming_it():
    with pytest.raises(units.UnitError, match="sl:unit/no-such-unit@1"):
        units.load("sl:unit/no-such-unit@1")


def test_another_version_is_another_file():
    with pytest.raises(units.UnitError):
        units.load("sl:unit/example-agent-loop@2")


def _root_with(tmp_path, mutate=None, name="example-agent-loop@1.yaml"):
    shutil.copytree(ROOT / "standards", tmp_path / "standards")
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    path = tmp_path / "standards" / "units" / name
    if mutate is not None:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        mutate(doc)
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return tmp_path


def test_a_file_whose_id_is_not_its_name_is_refused(tmp_path):
    root = _root_with(tmp_path, lambda d: d.__setitem__("id", "sl:unit/example-agent-loop@2"))
    with pytest.raises(units.UnitError, match="id"):
        units.load(UNIT, root)


NEGATIVES = {
    "no failure catalogue": lambda d: d.pop("failure_catalogue"),
    "empty failure catalogue": lambda d: d.__setitem__("failure_catalogue", []),
    "failure without an id": lambda d: d["failure_catalogue"][0].pop("id"),
    "failure without an injection": lambda d: d["failure_catalogue"][0].pop("inject"),
    "failure without a handling": lambda d: d["failure_catalogue"][0].pop("expected_handling"),
    "repeated failure id": lambda d: d["failure_catalogue"].append(copy.deepcopy(d["failure_catalogue"][0])),
    "no environment": lambda d: d.pop("environment"),
    "empty environment": lambda d: d.__setitem__("environment", ""),
    "no delivery modes": lambda d: d.__setitem__("delivery_modes", []),
    "unknown delivery mode": lambda d: d.__setitem__("delivery_modes", ["telepathy"]),
    "no learning outcomes": lambda d: d.__setitem__("learning_outcomes", []),
    "module id": lambda d: d.__setitem__("id", "tm:module/example"),
    "unit id without version": lambda d: d.__setitem__("id", "sl:unit/example-agent-loop"),
    "wrong schema version": lambda d: d.__setitem__("schema_version", 2),
    "run sheet step without an action": lambda d: d.__setitem__("run_sheet", [{"id": "open"}]),
    "run sheet as text": lambda d: d.__setitem__("run_sheet", "open the sandbox"),
    "run sheet with a repeated id": lambda d: d.__setitem__(
        "run_sheet", [{"id": "open", "action": "a"}, {"id": "open", "action": "b"}]),
    "misconception without a statement": lambda d: d["misconceptions"][0].pop("statement"),
    "pre-check without routes": lambda d: d["pre_check"][0].pop("routes"),
    "unknown top-level field": lambda d: d.__setitem__("owner", "me"),
}


@pytest.mark.parametrize("case", sorted(NEGATIVES))
def test_schema_rejects(case):
    doc = example()
    NEGATIVES[case](doc)
    assert units.document_errors(doc), case


def test_load_refuses_a_file_that_fails_the_schema(tmp_path):
    root = _root_with(tmp_path, lambda d: d.pop("failure_catalogue"))
    with pytest.raises(units.UnitError, match="failure_catalogue"):
        units.load(UNIT, root)


def test_a_run_sheet_is_optional_and_accepted():
    doc = example()
    doc["run_sheet"] = [{"id": "open-sandbox", "action": "Open the sandbox project"},
                        {"id": "run-lab", "action": "Run the lab", "minutes": 20}]
    assert validate(doc, "unit-requirements.schema.json") == []


# --- the environment hash -----------------------------------------------------------------------------------------


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_environment_sha256_is_the_hash_of_environment_failures_and_run_sheet():
    unit = example()
    want = hashlib.sha256(_canonical(
        {"environment": unit["environment"], "failure_catalogue": unit["failure_catalogue"]}).encode("utf-8")).hexdigest()
    assert units.environment_sha256(unit) == want
    unit["run_sheet"] = [{"id": "a", "action": "Do a"}]
    want = hashlib.sha256(_canonical({"environment": unit["environment"], "failure_catalogue": unit["failure_catalogue"],
                                      "run_sheet": unit["run_sheet"]}).encode("utf-8")).hexdigest()
    assert units.environment_sha256(unit) == want


def test_environment_sha256_is_stable_and_a_64_hex_string():
    a, b = units.environment_sha256(example()), units.environment_sha256(example())
    assert a == b and len(a) == 64 and set(a) <= set("0123456789abcdef")


def test_environment_sha256_changes_with_environment_failures_and_run_sheet():
    base = units.environment_sha256(example())
    for edit in (
        lambda d: d.__setitem__("environment", d["environment"] + " v2"),
        lambda d: d["failure_catalogue"][0].__setitem__("inject", "Something else"),
        lambda d: d["failure_catalogue"].append({"id": "extra", "inject": "x", "expected_handling": "y"}),
        lambda d: d.__setitem__("run_sheet", [{"id": "a", "action": "Do a"}]),
    ):
        unit = example()
        edit(unit)
        assert units.environment_sha256(unit) != base


def test_environment_sha256_ignores_the_rest_of_the_unit():
    base = units.environment_sha256(example())
    for edit in (
        lambda d: d.__setitem__("title", "A new title"),
        lambda d: d.__setitem__("learning_outcomes", ["Something new"]),
        lambda d: d.__setitem__("status", "active"),
        lambda d: d["misconceptions"][0].__setitem__("statement", "Reworded"),
        lambda d: d["pre_check"][0].__setitem__("question", "Reworded?"),
        lambda d: d.__setitem__("delivery_modes", ["remote"]),
    ):
        unit = example()
        edit(unit)
        assert units.environment_sha256(unit) == base


def test_environment_sha256_does_not_depend_on_key_order():
    unit = example()
    shuffled = {k: unit[k] for k in reversed(list(unit))}
    shuffled["failure_catalogue"] = [dict(reversed(list(f.items()))) for f in unit["failure_catalogue"]]
    assert units.environment_sha256(shuffled) == units.environment_sha256(unit)


# --- validate covers the units --------------------------------------------------------------------------------------


def test_validate_checks_every_unit_file(tmp_path):
    assert check_standards() == []
    root = _root_with(tmp_path, lambda d: d.pop("failure_catalogue"))
    errors = check_standards(root)
    assert any("units/example-agent-loop@1.yaml" in e and "failure_catalogue" in e for e in errors), errors


def test_validate_refuses_a_unit_file_named_for_another_id(tmp_path):
    root = _root_with(tmp_path)
    shutil.copy2(root / "standards" / "units" / "example-agent-loop@1.yaml", root / "standards" / "units" / "other@1.yaml")
    errors = check_standards(root)
    assert any("other@1.yaml" in e and "id" in e for e in errors), errors
