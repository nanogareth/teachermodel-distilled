"""The record adapters (docs/plans/2026-10-24-increment-2-plan.md, "Record adapters"): events -> rules.py data.

K0 fixes the names and signatures; streams B, C, E and D each fill in their own module. Until then a body raises
NotImplementedError. This test pins the import paths and signatures so no stream renames them.
"""

import inspect

import pytest

from teachermodel.records import (
    audits, bench, calibrations, clearances, cpd, cycles, dry_runs, lapses, observations, outcomes,
)

ADAPTERS = {
    "observations": (observations, ["events"], "list[rules.Observation]"),
    "dry_runs": (dry_runs, ["events", "units"], "list[rules.DryRun]"),
    "calibrations": (calibrations, ["events"], "dict[str, list[date]]"),
    "clearances": (clearances, ["events"], "list[rules.Clearance]"),
    # increment 3 (decision 0014): K1 fixed the signatures; streams F, G, H and I write the bodies
    "audits": (audits, ["events"], "list[dict]"),
    "cycles": (cycles, ["events"], "list[dict]"),
    "cpd": (cpd, ["events"], "list[dict]"),
    "outcomes": (outcomes, ["events"], "list[rules.Outcome]"),
    "bench": (bench, ["events"], "list[dict]"),
    # the increment 3 integration (decision 0015): audit referrals, read beside calibrations by rules.is_calibrated
    "lapses": (lapses, ["events"], "dict[str, list[date]]"),
}


def test_each_module_exposes_one_function_of_the_same_name():
    import importlib

    assert all(callable(f) for f in (observations, dry_runs, calibrations, clearances, audits, cycles, cpd, outcomes, bench,
                                     lapses))

    for name in ADAPTERS:
        module = importlib.import_module(f"teachermodel.records.{name}")
        public = [n for n, v in vars(module).items() if inspect.isfunction(v) and not n.startswith("_")
                  and v.__module__ == module.__name__]
        assert public == [name], (name, public)


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_signature_is_fixed(name):
    fn, params, returns = ADAPTERS[name]
    sig = inspect.signature(fn)
    assert list(sig.parameters) == params
    assert sig.return_annotation == returns


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_docstring_states_the_input_events_and_the_output_dataclasses(name):
    fn = ADAPTERS[name][0]
    doc = inspect.getdoc(fn) or ""
    assert "Input events" in doc and "Output" in doc, name


def test_docstrings_name_the_event_kinds_and_dataclasses():
    assert "`observation`" in inspect.getdoc(observations) and "rules.Observation" in inspect.getdoc(observations)
    assert "`dry_run`" in inspect.getdoc(dry_runs) and "rules.DryRun" in inspect.getdoc(dry_runs)
    assert "environment" in inspect.getdoc(dry_runs)
    assert "`calibration`" in inspect.getdoc(calibrations) and "rules.is_calibrated" in inspect.getdoc(calibrations)
    assert "`clearance`" in inspect.getdoc(clearances) and "rules.Clearance" in inspect.getdoc(clearances)


# Increment 3: every adapter now has its body (K1 wrote the stubs, F/G/H/I the bodies), so none is a stub any more.
IMPLEMENTED = {"observations", "dry_runs", "calibrations", "clearances", "outcomes", "audits", "cycles", "cpd", "bench",
               "lapses"}


def test_every_adapter_is_implemented():
    assert IMPLEMENTED == set(ADAPTERS)


def test_every_implemented_adapter_runs_on_no_events():
    # None raises (NotImplementedError or otherwise) on no events.
    for name in IMPLEMENTED:
        fn, params, _ = ADAPTERS[name]
        fn(*([[]] * len(params)))


def test_increment_3_docstrings_name_the_event_kinds_and_outputs():
    assert "`audit`" in inspect.getdoc(audits) and "audit@1" in inspect.getdoc(audits)
    assert "`coaching_cycle`" in inspect.getdoc(cycles) and "coaching-cycle@1" in inspect.getdoc(cycles)
    assert "`cpd`" in inspect.getdoc(cpd) and "cpd@1" in inspect.getdoc(cpd)
    assert "`outcome`" in inspect.getdoc(outcomes) and "rules.Outcome" in inspect.getdoc(outcomes)
    assert "`bench_decision`" in inspect.getdoc(bench) and "bench-decision@1" in inspect.getdoc(bench)
