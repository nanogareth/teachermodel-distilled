from teachermodel.standards import check_standards, load_standards


def test_standards_valid_and_consistent():
    assert check_standards() == []


def test_v02_strong_evidence_rules(rules):
    assert rules["clearance"]["min_distinct_observers"] >= 2
    assert rules["clearance"]["max_coach_observers"] <= 1
    assert rules["bench"]["min_distinct_observers"] >= 2
    assert rules["quality"]["domain_one_needs_second_observer"] is True


def test_framework_has_v02_domains():
    ids = [d["id"] for d in load_standards()["framework"]["domains"]]
    assert "prior-knowledge" in ids and "conceptual-questioning" in ids


# --- standards/workflows/*.yaml cross-checks (each is a known-negative on a temp copy of the repo data) ---

import shutil
import tempfile
from pathlib import Path

import yaml

from teachermodel.standards import ROOT


def _temp_root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "standards", tmp_path / "standards")
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    return tmp_path


def _mutate(root: Path, fn, file: str = "setup") -> list[str]:
    path = root / "standards" / "workflows" / f"{file}.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return check_standards(root)


def _step(doc, slug):
    for wf in doc["workflows"]:
        for st in wf["steps"]:
            if st["id"] == f"tm:step/{slug}":
                return st
    raise KeyError(slug)


def test_workflows_defined():
    ids = [w["id"] for w in load_standards()["workflows"]["workflows"]]
    assert ids == ["tm:workflow/audit", "tm:workflow/bench", "tm:workflow/calibration", "tm:workflow/clearance",
                   "tm:workflow/coaching", "tm:workflow/cpd", "tm:workflow/dry-run", "tm:workflow/levels",
                   "tm:workflow/observation", "tm:workflow/onboarding", "tm:workflow/override", "tm:workflow/pathway",
                   "tm:workflow/privacy-base", "tm:workflow/privacy-overlay", "tm:workflow/quality", "tm:workflow/rights",
                   "tm:workflow/setup"]  # merged in file-name order


def test_merged_workflows_document():
    doc = load_standards()["workflows"]
    assert doc["id"] == "tm:standards/workflows" and doc["schema_version"] == 1
    files = sorted((ROOT / "standards" / "workflows").glob("*.yaml"))
    assert len(files) >= 2
    per_file = [wf["id"] for f in files for wf in yaml.safe_load(f.read_text(encoding="utf-8"))["workflows"]]
    assert [w["id"] for w in doc["workflows"]] == per_file


def test_workflow_cycle_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-request").__setitem__("needs", ["tm:step/library-exists"]))
    assert any("cycle" in e for e in errors), errors


def test_unknown_page_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").__setitem__("page", "no_such_template"))
    assert any("no_such_template" in e and "page" in e for e in errors), errors


def test_unknown_due_rule_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").__setitem__("due", "no_such_rule"))
    assert any("no_such_rule" in e and "due" in e for e in errors), errors


def test_non_due_rule_rejected(tmp_path):
    # coaching_overdue is a rule but returns a bool, not a due date: only registered due rules (teachermodel.due) qualify.
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").__setitem__("due", "coaching_overdue"))
    assert any("not registered" in e for e in errors), errors


def test_unknown_need_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").__setitem__("needs", ["tm:step/ghost"]))
    assert any("ghost" in e for e in errors), errors


def test_unknown_role_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").__setitem__("role", "wizard"))
    assert errors and any("role" in e for e in errors), errors


def test_empty_basis_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").__setitem__("basis", "  "))
    assert errors and any("basis" in e for e in errors), errors


def test_human_step_without_page_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").pop("page"))
    assert errors, errors


def test_event_kind_outside_set_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done")["done_when"].__setitem__("kind", "bogus"))
    assert errors, errors


# --- declared event kinds, and ids unique across files ---

import json


def test_done_when_kind_must_be_declared(tmp_path):
    root = _temp_root(tmp_path)
    # onboarding declares only [signoff]; a `check` completion is undeclared there.
    errors = _mutate(root, lambda d: _step(d, "co-delivery")["done_when"].__setitem__("kind", "check"), "onboarding")
    assert any("co-delivery" in e and "event_kinds" in e and "check" in e for e in errors), errors


def test_declared_event_kind_must_be_in_event_enum(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: d["workflows"][0]["event_kinds"].append("bogus_kind"), "onboarding")
    assert any("bogus_kind" in e and "event" in e for e in errors), errors


def test_event_kinds_required(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: d["workflows"][0].pop("event_kinds"), "onboarding")
    assert any("event_kinds" in e for e in errors), errors


def test_declared_kinds_match_the_event_enum():
    enum = set(json.loads((ROOT / "contracts" / "event.schema.json").read_text(encoding="utf-8"))["properties"]["kind"]["enum"])
    for wf in load_standards()["workflows"]["workflows"]:
        assert set(wf["event_kinds"]) <= enum, wf["id"]


def test_step_id_duplicated_across_files_rejected(tmp_path):
    root = _temp_root(tmp_path)
    path = root / "standards" / "workflows" / "onboarding.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    dup = yaml.safe_load((root / "standards" / "workflows" / "setup.yaml").read_text(encoding="utf-8"))
    doc["workflows"][0]["steps"].append(_step(dup, "it-request"))
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    errors = check_standards(root)
    assert any("duplicate step id tm:step/it-request" in e for e in errors), errors


def test_need_may_cross_files():
    # tm:step/commitment-manager (onboarding) needs tm:step/roster-import (setup)
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}
    assert "tm:step/roster-import" in _step({"workflows": [wf["tm:workflow/onboarding"]]}, "commitment-manager")["needs"]
    assert check_standards() == []


def test_workflow_file_schema_error_names_the_file(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: d.__setitem__("status", "wobbly"), "onboarding")
    assert any("onboarding.yaml" in e for e in errors), errors


# --- bind: input, jurisdiction subjects and filters, the legal role (privacy-jurisdictions design) ---


def test_bind_input_accepted_on_a_signoff_step(tmp_path):
    root = _temp_root(tmp_path)
    assert _mutate(root, lambda d: _step(d, "it-done")["done_when"].__setitem__("bind", "input")) == []


def test_bind_value_other_than_input_rejected(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done")["done_when"].__setitem__("bind", "everything"))
    assert any("bind" in e for e in errors), errors


def test_bind_input_needs_a_signoff_completion(tmp_path):
    root = _temp_root(tmp_path)

    def bind_a_step_output(d):
        _step(d, "ropa")["done_when"]["bind"] = "input"  # an auto step completes on `step`, which carries no input_sha256

    errors = _mutate(root, bind_a_step_output, "privacy-base")
    assert any("ropa" in e and "bind" in e and "signoff" in e for e in errors), errors


def test_jurisdiction_subject_and_filter_accepted(tmp_path):
    root = _temp_root(tmp_path)

    def retarget(d):
        st = _step(d, "it-done")
        st["subject"] = "jurisdiction"
        st["applies_to"] = {"jurisdiction": ["US-CA"]}
        st["role"] = "legal"

    assert _mutate(root, retarget) == []


def test_jurisdiction_filter_must_be_a_code(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done").__setitem__("applies_to", {"jurisdiction": ["California"]}))
    assert any("applies_to" in e for e in errors), errors


# --- retention@2 cross-checks ---


def _retention_errors(tmp_path, entries):
    tmp_path = Path(tempfile.mkdtemp(dir=tmp_path))
    root = _temp_root(tmp_path)
    path = root / "standards" / "retention.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["entries"] = entries
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return [e for e in check_standards(root) if e.startswith("retention")]


def _entry(**kw):
    base = {"category": "performance-data", "purpose": "tm:purpose/coaching", "period_months": 24,
            "starts": "The engagement ends.", "reason": "Fictional reason that is long enough.",
            "basis": "legitimate-interests"}
    return {**base, **kw}


def test_retention_entry_for_an_unknown_category_rejected(tmp_path):
    assert _retention_errors(tmp_path, [_entry()]) == []
    errors = _retention_errors(tmp_path, [_entry(category="observations")])
    assert any("unknown data category 'observations'" in e for e in errors), errors


def test_retention_entry_repeated_for_the_same_category_purpose_jurisdiction_rejected(tmp_path):
    errors = _retention_errors(tmp_path, [_entry(), _entry(period_months=36)])
    assert any("more than one entry" in e for e in errors), errors


# --- skippable, and the notice_variant match template ---


def test_skippable_accepted_on_a_bound_signoff_step(tmp_path):
    root = _temp_root(tmp_path)

    def skippable(d):
        done = _step(d, "it-done")["done_when"]
        done.update(bind="input", skippable=True)

    assert _mutate(root, skippable) == []


def test_skippable_needs_bind_input(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done")["done_when"].__setitem__("skippable", True))
    assert any("it-done" in e and "skippable" in e and "bind" in e for e in errors), errors


def test_skippable_must_be_true(tmp_path):
    root = _temp_root(tmp_path)

    def bad(d):
        _step(d, "it-done")["done_when"].update(bind="input", skippable="yes")

    assert any("skippable" in e for e in _mutate(root, bad))


# --- step.signer (decision 0012) ---------------------------------------------------------------------------------


def test_the_signer_steps_validate():
    assert check_standards() == []
    steps = {s["id"]: s for w in load_standards()["workflows"]["workflows"] for s in w["steps"]}
    assert {sid.split("/")[1]: s["signer"] for sid, s in steps.items() if "signer" in s} == {
        "observe": "attrs.observer", "self-assessment": "attrs.instructor", "calibration-score": "attrs.observers"}


def test_signer_value_outside_the_enum_rejected(tmp_path):
    errors = _mutate(_temp_root(tmp_path), lambda d: _step(d, "observe").__setitem__("signer", "attrs.nobody"),
                     file="observation")
    assert errors


def test_signer_on_a_subject_that_has_no_such_attrs_rejected(tmp_path):
    errors = _mutate(_temp_root(tmp_path), lambda d: _step(d, "observe").__setitem__("signer", "attrs.observers"),
                     file="observation")
    assert any("signer 'attrs.observers' needs a human step on a exercise subject" in e for e in errors), errors


def test_signer_on_an_auto_step_rejected(tmp_path):
    errors = _mutate(_temp_root(tmp_path), lambda d: _step(d, "release").__setitem__("signer", "attrs.observer"),
                     file="observation")
    assert any("signer" in e and "human step" in e for e in errors), errors


# --- purposes: a planned workflow that now exists must move to `workflows` -----------------------------------------


def _edit_purposes(root, fn):
    path = root / "standards" / "privacy" / "purposes.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return check_standards(root)


def test_validate_flags_a_planned_workflow_that_now_exists_as_a_file(tmp_path):
    root = _temp_root(tmp_path)
    assert check_standards(root) == []
    errors = _edit_purposes(root, lambda d: d["purposes"][0].__setitem__(
        "planned_workflows", [*d["purposes"][0].get("planned_workflows", []), "tm:workflow/clearance"]))
    assert any("tm:workflow/clearance" in e and "planned_workflows" in e and "exists" in e for e in errors), errors


def test_validate_still_accepts_a_planned_workflow_that_does_not_exist_yet(tmp_path):
    root = _temp_root(tmp_path)
    assert _edit_purposes(root, lambda d: d["purposes"][0].__setitem__(
        "planned_workflows", ["tm:workflow/not-built-yet"])) == []


def test_the_shipped_purposes_list_no_existing_workflow_as_planned():
    existing = {w["id"] for w in load_standards()["workflows"]["workflows"]}
    doc = yaml.safe_load((ROOT / "standards" / "privacy" / "purposes.yaml").read_text(encoding="utf-8"))
    planned = {w for p in doc["purposes"] for w in p.get("planned_workflows", [])}
    assert planned and not planned & existing, sorted(planned & existing)


# --- revocable (decision 0019) ---


def test_revocable_accepted_on_a_bound_signoff_step(tmp_path):
    root = _temp_root(tmp_path)
    assert _mutate(root, lambda d: _step(d, "it-done")["done_when"].update(bind="input", revocable=True)) == []


def test_revocable_needs_bind_input(tmp_path):
    root = _temp_root(tmp_path)
    errors = _mutate(root, lambda d: _step(d, "it-done")["done_when"].__setitem__("revocable", True))
    assert any("it-done" in e and "revocable" in e and "bind" in e for e in errors), errors
