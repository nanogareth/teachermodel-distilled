"""The fictional end-to-end script (scripts/e2e_fictional.py) runs in-process and passes."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e2e_fictional.py"


@pytest.fixture(scope="module")
def e2e():
    spec = importlib.util.spec_from_file_location("e2e_fictional", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def test_main_runs_every_stage(e2e, tmp_path, capsys):
    work = tmp_path / "work"
    assert e2e.main(["--work-dir", str(work), "--keep"]) == 0
    out = capsys.readouterr().out.splitlines()
    stages = [line for line in out if line.startswith("ok  ")]
    assert len(stages) >= 15 and stages[-1].split()[2] == "final:"
    private = work / "private"
    assert (private / "events" / "events.jsonl").is_file() and (private / "signoffs").is_dir()


def test_main_refuses_a_work_dir_inside_the_repo(e2e, capsys):
    inside = Path(__file__).resolve().parent / "e2e-work"
    assert e2e.main(["--work-dir", str(inside)]) == 1
    assert "inside the git working tree" in capsys.readouterr().err
    assert not inside.exists()


def test_a_failed_expectation_exits_nonzero(e2e, tmp_path, monkeypatch, capsys):
    # the first stage, so the failure path costs one setup and no stages (the full run is the test above)
    monkeypatch.setattr(e2e, "stage_setup_steps", lambda h: e2e.expect(False, "forced failure"))
    assert e2e.main(["--work-dir", str(tmp_path / "w")]) == 1
    assert "forced failure" in capsys.readouterr().err
