"""`teachermodel daily`, `dev-mode` and `schedule-daily` (owner, 2026-10-27): the deterministic daily job, its development
toggle and the Windows task that runs it. Fictional data only."""

from datetime import datetime, timezone

import pytest
import yaml

from teachermodel import cli, daily, pilot, setup

OWNER = {"owner_name": "Olive Owner", "owner_email": "olive.owner@company.ie"}
T0 = datetime(2026, 10, 27, 7, 30, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    s = tmp_path / "pilot"
    pilot.init_pilot(s, **OWNER, set_env=False)
    return s


def _log(store):
    return (store / daily.LOG).read_text(encoding="utf-8").splitlines()


def test_daily_rebuilds_the_read_views_so_they_never_go_stale(store):
    rep = daily.daily(store, now=T0)
    assert rep.ok and _log(store)[0].startswith("2026-10-27T07:30:00+00:00 views ok: views: ")
    for name in ("monthly-outcomes.html", "quality-review.html", "clearance-matrix.html", "coaching-log.html"):
        assert (store / "views" / name).is_file(), name


def test_views_that_cannot_be_built_are_logged_and_the_tick_still_runs(store, monkeypatch):
    def broken(*a, **k):
        raise ValueError("index")

    monkeypatch.setattr(daily.views, "build", broken)
    rep = daily.daily(store, now=T0)
    assert not rep.ok and "views FAILED: ValueError" in _log(store)[0] and " tick ok: " in _log(store)[-1]


def test_daily_runs_dev_autosign_when_the_toggle_is_on(store, monkeypatch):
    from teachermodel import app

    daily.set_dev_mode(store, True)
    monkeypatch.setattr(daily.devsign, "autosign", lambda private, **k: app.Report(summary="dev-autosign: 0 sign-off(s)"))
    rep = daily.daily(store, now=T0)
    assert rep.summary == "dev-autosign: 0 sign-off(s)"
    assert _log(store)[-1].endswith("dev-autosign ok: dev-autosign: 0 sign-off(s)")


def test_the_toggle_keeps_the_settings_file_and_turns_off(store):
    before = (store / "settings.yaml").read_text(encoding="utf-8")
    assert daily.set_dev_mode(store, True) is True and setup.load_settings(store)["dev_autosign"] is True
    assert daily.set_dev_mode(store, True) is True  # idempotent
    text = (store / "settings.yaml").read_text(encoding="utf-8")
    assert text.startswith(before.rstrip("\n").split("\n")[0]) and text.count("dev_autosign") == 1  # header comment kept
    assert daily.set_dev_mode(store, False) is False and setup.load_settings(store)["dev_autosign"] is False


def test_the_toggle_is_refused_outside_a_pilot_store(store):
    path = store / "settings.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump({k: v for k, v in doc.items() if k != "pilot"}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(setup.SetupError, match="pilot"):
        daily.set_dev_mode(store, True)
    assert path.read_text(encoding="utf-8") == before  # nothing written


def test_the_settings_contract_refuses_dev_autosign_without_pilot(store):
    path = store / "settings.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump({**{k: v for k, v in doc.items() if k != "pilot"}, "dev_autosign": True}),
                    encoding="utf-8")
    with pytest.raises(setup.SetupError):
        setup.load_settings(store)


def test_init_pilot_force_keeps_the_toggle(store):
    daily.set_dev_mode(store, True)
    pilot.init_pilot(store, **OWNER, set_env=False, force=True)
    assert setup.load_settings(store)["dev_autosign"] is True


def test_the_scheduled_task_runs_the_daily_command_without_a_window(store):
    create = daily.schtasks_create(store, python=r"C:\Python313\python.exe", at="07:30", weekdays=True)
    assert create[:5] == ["schtasks", "/Create", "/TN", daily.TASK_NAME, "/TR"]
    tr = create[5]
    assert tr.startswith('"C:\\Python313\\pythonw.exe" -m teachermodel.cli daily --private-dir "') and len(tr) <= 261
    assert create[6:] == ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", "07:30", "/F"]
    every = daily.schtasks_create(store, python=r"C:\Python313\python.exe", at="06:00", weekdays=False)
    assert every[6:] == ["/SC", "DAILY", "/ST", "06:00", "/F"]
    assert daily.schtasks_delete() == ["schtasks", "/Delete", "/TN", daily.TASK_NAME, "/F"]
    with pytest.raises(ValueError):
        daily.schtasks_create(store, python="py", at="7:30", weekdays=True)


def test_the_cli_runs_daily_and_dev_mode(store, capsys):
    assert cli.main(["dev-mode", "status", "--private-dir", str(store)]) == 0
    assert "off" in capsys.readouterr().out
    assert cli.main(["dev-mode", "on", "--private-dir", str(store)]) == 0
    assert "on" in capsys.readouterr().out
