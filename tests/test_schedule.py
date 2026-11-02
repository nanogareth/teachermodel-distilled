"""schedule.py: the session schedule from a calendar export (tm:contract/schedule@1, decision 0027). The loader on its
own first, then `import-schedule` on a one-week simulated store. Generated data only."""

from datetime import date

import pytest
import yaml

from teachermodel import cli, schedule, simulate

UNIT = "sl:unit/example-agent-loop@1"


def session(**over):
    s = {"ref": "cohort12-agg-lab", "programme": "cohort-12", "unit": UNIT, "lab": "aggregates-only-export",
         "mode": "hybrid", "from": "2026-11-12", "to": "2026-11-12", "region": "IE", "lead": "tm:instructor/g1x9d",
         "observer": "tm:instructor/d7h2k", "expected_learners": 24, "status": "confirmed"}
    s.update(over)
    return s


def export(*sessions):
    return {"schema": "tm:contract/schedule@1", "exported_at": "2026-10-28T07:00:00Z", "sessions": list(sessions)}


def write(folder, doc):
    (folder / "inputs").mkdir(parents=True, exist_ok=True)
    (folder / "inputs" / "schedule.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def test_a_valid_export_loads(tmp_path):
    write(tmp_path, export(session(), session(ref="onboarding-c4", programme="platform-onboarding-c4", lab=None,
                                              mode="in-person", **{"from": "2026-11-09", "to": "2026-11-13"},
                                              lead="tm:instructor/r6w2c", observer=None, status="held")))
    got = schedule.load(tmp_path, {"simulated": True})
    assert got.exported_at == "2026-10-28T07:00:00Z"
    first, second = got.sessions
    assert (first.ref, first.start, first.end, first.expected_learners, first.lab) == (
        "cohort12-agg-lab", date(2026, 11, 12), date(2026, 11, 12), 24, "aggregates-only-export")
    assert (second.lab, second.observer, second.co, second.status) == (None, None, (), "held")
    assert schedule.load(tmp_path / "empty", {"simulated": True}) is None


def test_every_problem_in_a_bad_export_is_listed_at_once():
    problems = schedule.problems(export(
        session(ref="late", **{"from": "2026-11-05", "to": "2026-11-01"}),
        session(ref="twice"), session(ref="twice"),
        session(ref="lost", unit="sl:unit/nothing@1"),
        session(ref="online", mode="online")))
    assert any(p.startswith("sessions/4/mode") for p in problems)
    assert "late: ends before it starts" in problems
    assert "twice: the ref is used more than once" in problems
    assert any(p.startswith("lost: unknown unit sl:unit/nothing@1") for p in problems)
    assert len(problems) == 4


def test_a_real_store_reads_no_schedule_without_a_retention_entry(tmp_path):
    write(tmp_path, export(session()))
    with pytest.raises(schedule.ScheduleError, match="schedule-records"):
        schedule.load(tmp_path, {"simulated": False})


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("schedule") / "store"
    try:
        simulate.simulate(s, weeks=1, end=date(2026, 10, 23))
        yield s
    finally:
        mp.undo()


def test_import_schedule_copies_a_good_export_and_refuses_a_bad_one(store, tmp_path, capsys):
    bad, good = tmp_path / "bad.yaml", tmp_path / "good.yaml"
    bad.write_text(yaml.safe_dump(export(session(ref="x", **{"from": "2026-11-05", "to": "2026-11-01"}))),
                   encoding="utf-8")
    assert cli.main(["import-schedule", "--private-dir", str(store), str(bad)]) == 1
    assert "x: ends before it starts" in capsys.readouterr().err
    assert not (store / "inputs" / "schedule.yaml").exists()
    good.write_text(yaml.safe_dump(export(session(), session(ref="b"))), encoding="utf-8")
    assert cli.main(["import-schedule", "--private-dir", str(store), str(good)]) == 0
    assert "2 session(s), exported 2026-10-28T07:00:00Z" in capsys.readouterr().out
    assert len(schedule.load(store, {"simulated": True}).sessions) == 2
