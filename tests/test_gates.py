"""`teachermodel gates` (gates.py, increment 4 item 1): the phase gates and acceptance criteria computed from a store.
Run on a one-week simulated store (generated data only)."""

import subprocess
from datetime import date

import pytest

from teachermodel import cli, gates, simulate

IDS = ["G1", "G2", "G3", "G4", "G5", "G6", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11", "A12",
       "A13"]


@pytest.fixture(scope="module")
def week(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    store = tmp_path_factory.mktemp("gates") / "store"
    try:
        simulate.simulate(store, weeks=1, end=date(2026, 10, 23))
        yield store
    finally:
        mp.undo()


def test_every_gate_and_criterion_is_reported_once_with_a_known_status(week):
    found = gates.report(week)
    assert [c.id for c in found] == IDS
    assert {c.status for c in found} <= {gates.MET, gates.UNMET, gates.ATTESTED, gates.NOT_BUILT}
    by = {c.id: c for c in found}
    assert by["A13"].status == by["A6"].status == gates.ATTESTED
    assert by["A12"].status == gates.ATTESTED and by["A9"].status in (gates.MET, gates.UNMET)
    assert all(c.detail for c in found)


def test_a_young_store_shows_what_it_cannot_meet_yet(week):
    by = {c.id: c for c in gates.report(week)}
    assert by["G5"].status == gates.UNMET and "none" in by["G5"].detail  # no closed quarter with a sample in one week
    assert by["G6"].status == gates.UNMET and "partner clearances from recordings: 0" in by["G6"].detail
    assert by["A10"].status == gates.MET  # whatever clearances exist trace to their rounds


def test_the_report_is_read_only(week):
    log = (week / "events" / "events.jsonl").read_bytes()
    gates.report(week)
    assert (week / "events" / "events.jsonl").read_bytes() == log


def test_the_gates_command(week, capsys):
    assert cli.main(["gates", "--private-dir", str(week)]) == 0
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1].startswith("gates: ") and "G1" in out and "A13" in out


def _repo(tmp_path, files):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    return tmp_path


def test_personal_data_scan_flags_real_looking_addresses_outside_tests(tmp_path):
    root = _repo(tmp_path, {
        "docs/a.md": "Mail jane.doe@company.ie about it.",
        "docs/b.md": "Fictional: owner@example.com, x@example.test, unit sl:unit/example-agent-loop@1.yaml",
        "tests/fixture.py": "REFUSED = 'olive@gmail.com'  # a fictional address the test refuses",
    })
    assert gates.personal_data_in_git(root) == ["docs/a.md (1 address(es))"]


def test_phase_6_reads_the_framework_version_and_the_attestation():
    """Decision 0023: framework 1.1.0 and the head of training's attestation of an SME module taken to delivery."""
    assert gates._version_at_least("1.1.0", (1, 1)) and gates._version_at_least("2.0", (1, 1))
    assert not gates._version_at_least("0.2.0", (1, 1)) and not gates._version_at_least("x", (1, 1))
    found = gates.attestations()
    assert found["G6-sme-module-delivered"]["role"] == "head-of-training"
    assert found["G6-sme-module-delivered"]["decision"] == "0023" and "G6-standard-v1.1" in found
