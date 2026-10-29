"""Due-rule registry (src/teachermodel/due.py): a workflow step's `due` may name a rule instead of a number of days.

A rule is `(step, subject_uri, subject_info, events, today) -> date | None`, registered with `@due_rule("name")`
(flow modules do so at import). The engine resolves the name through the registry; `validate` refuses a name that is
not registered. Fictional data only.
"""

import shutil
from datetime import date

import pytest
import yaml

from teachermodel import due, rules
from teachermodel.events import make_event
from teachermodel.standards import ROOT, check_standards
from teachermodel.workflow import next_steps
from teachermodel.workflow import subjects as engine_subjects

TODAY = date(2026, 10, 24)
ALICE = "tm:instructor/alice"


@pytest.fixture
def registered():
    """Register rules by name for one test and take them out again."""
    names: list[str] = []

    def add(name, fn):
        due.due_rule(name)(fn)
        names.append(name)
        return fn

    yield add
    for name in names:
        due._RULES.pop(name, None)


def log():
    return [make_event("registration", ALICE, "tm:person/owner", {"type": "professional", "level": "shadow"},
                       at="2026-10-01T09:00:00+00:00")]


def wf(**step_kw):
    st = {"id": "tm:step/a", "name": "a", "type": "human", "role": "coordinator", "subject": "instructor", "needs": [],
          "done_when": {"kind": "signoff", "match": {"step": "tm:step/a"}}, "page": "approve", "basis": "test", **step_kw}
    return {"workflows": [{"id": "tm:workflow/t", "name": "t", "basis": "test", "steps": [st]}]}


# --- the registry ---------------------------------------------------------------------------------------------


def test_due_rule_registers_and_returns_the_function():
    def rule(step, subject_uri, subject_info, events, today):
        return None

    try:
        assert due.due_rule("k0_registers")(rule) is rule
        assert due.resolve("k0_registers") is rule
        assert "k0_registers" in due.names()
    finally:
        due._RULES.pop("k0_registers", None)


def test_a_name_registers_once(registered):
    registered("k0_once", lambda *a: None)
    with pytest.raises(ValueError, match="already registered"):
        due.due_rule("k0_once")(lambda *a: None)


@pytest.mark.parametrize("name", ["", "Upper", "1starts_with_digit", "has-dash", "has space"])
def test_a_rule_name_must_be_a_workflow_rule_name(name):
    with pytest.raises(ValueError, match="rule name"):
        due.due_rule(name)(lambda *a: None)


def test_resolving_an_unknown_name_names_it():
    with pytest.raises(KeyError, match="no_such_rule"):
        due.resolve("no_such_rule")


def test_rules_no_longer_carries_a_due_rules_tuple():
    assert not hasattr(rules, "DUE_RULES")


# --- the engine ----------------------------------------------------------------------------------------------


def test_the_engine_calls_the_rule_with_step_subject_info_events_and_today(registered):
    seen = []

    def rule(step, subject_uri, subject_info, events, today):
        seen.append((step["id"], subject_uri, dict(subject_info), [e["kind"] for e in events], today))
        return date(2026, 11, 1)

    registered("k0_calls", rule)
    events = log()
    (d,) = next_steps(wf(due="k0_calls"), events, engine_subjects(events, ("IE",)), TODAY)
    assert seen == [("tm:step/a", ALICE, {"kind": "instructor", "type": "professional", "level": "shadow"},
                     ["registration"], TODAY)]
    assert d.due == date(2026, 11, 1) and d.overdue is False


def test_a_rule_date_in_the_past_is_overdue_and_today_is_not(registered):
    registered("k0_past", lambda *a: date(2026, 10, 23))
    registered("k0_today", lambda *a: TODAY)
    events = log()
    subj = engine_subjects(events, ("IE",))
    (past,) = next_steps(wf(due="k0_past"), events, subj, TODAY)
    (today,) = next_steps(wf(due="k0_today"), events, subj, TODAY)
    assert past.overdue is True and today.overdue is False


def test_a_rule_returning_none_gives_no_due_date(registered):
    registered("k0_none", lambda *a: None)
    events = log()
    (d,) = next_steps(wf(due="k0_none"), events, engine_subjects(events, ("IE",)), TODAY)
    assert d.due is None and d.overdue is False


def test_the_days_form_still_works():
    events = log()
    (d,) = next_steps(wf(due={"days": 5, "basis": "operational default"}), events, engine_subjects(events, ("IE",)), TODAY)
    assert d.due == date(2026, 10, 6)


def test_an_unregistered_name_at_runtime_is_an_error_not_a_missing_date():
    events = log()
    with pytest.raises(ValueError, match="no_such_rule"):
        next_steps(wf(due="no_such_rule"), events, engine_subjects(events, ("IE",)), TODAY)


# --- validate -----------------------------------------------------------------------------------------------


def _temp_root(tmp_path):
    shutil.copytree(ROOT / "standards", tmp_path / "standards")
    shutil.copytree(ROOT / "contracts", tmp_path / "contracts")
    return tmp_path


def _set_due(root, value):
    path = root / "standards" / "workflows" / "setup.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    next(st for w in doc["workflows"] for st in w["steps"] if st["id"] == "tm:step/it-done")["due"] = value
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return check_standards(root)


def test_validate_accepts_a_registered_rule_name(tmp_path, registered):
    registered("k0_validate_ok", lambda *a: None)
    assert _set_due(_temp_root(tmp_path), "k0_validate_ok") == []


def test_validate_refuses_an_unregistered_rule_name(tmp_path):
    errors = _set_due(_temp_root(tmp_path), "no_such_rule")
    assert any("no_such_rule" in e and "not registered" in e for e in errors), errors


def test_validate_refuses_a_rules_module_function_that_is_not_registered(tmp_path):
    # coaching_overdue is a rule, but it returns a bool and nobody registered it as a due rule
    errors = _set_due(_temp_root(tmp_path), "coaching_overdue")
    assert any("coaching_overdue" in e and "not registered" in e for e in errors), errors


def test_validate_imports_the_flows_so_their_rules_are_registered():
    """Rules are registered by flow modules at import, so validate must import them itself (checked in a fresh process)."""
    import os
    import subprocess
    import sys

    code = (
        "import sys; from teachermodel import standards; "
        "assert 'teachermodel.flows' not in sys.modules; "
        "assert standards.check_standards() == []; "
        "assert 'teachermodel.flows' in sys.modules"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"}
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8")
    assert done.returncode == 0, done.stderr
