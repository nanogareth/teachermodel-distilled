"""`teachermodel dev-simulate` (simulate.py, decision 0020): a simulated store built by weeks of generated use on the real
standards. A one-week run is enough to check the mechanics; the full run is checked by hand (handover). Generated data only.
"""

import json
from datetime import date

import pytest

from teachermodel import app, cli, notice, setup, simulate
from teachermodel.standards import ROOT, validate

END = date(2026, 10, 23)


@pytest.fixture(scope="module")
def week(tmp_path_factory):
    """One simulated week, run once for the module (it takes about a minute)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")  # conftest's guard, for a module-scoped fixture
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    store = tmp_path_factory.mktemp("sim") / "store"
    try:
        yield store, simulate.simulate(store, weeks=1, end=END)
    finally:
        mp.undo()


def kinds(store):
    return {e["kind"] for e in app.read_events(store)}


def test_a_week_runs_the_setup_privacy_and_onboarding_through_the_real_ingest(week):
    store, rep = week
    assert rep.ok and "rejected" not in " ".join(rep.lines), rep.all_lines()
    assert {"registration", "notice", "signoff", "level_change", "subject"} <= kinds(store)
    # a week back from Friday 23 October starts on Monday 12 October: ten weekdays
    assert (store / simulate.LOG).read_text(encoding="utf-8").count("\n") == 10


def test_the_store_is_a_simulated_pilot_store_with_generated_people_only(week):
    store, _ = week
    settings = setup.load_settings(store)
    assert settings["pilot"] is True and settings["simulated"] is True
    people = [p["email"] for p in app.load_state(store).people]
    assert people and all(e.endswith("@example.com") for e in people)
    import yaml

    roster = yaml.safe_load((store / "inputs" / "roster.yaml").read_text(encoding="utf-8"))["instructors"]
    assert {r["jurisdiction"] for r in roster} == {"IE", "US-CA"}


def test_the_notice_text_renders_with_the_simulation_line_and_no_draft_markers(week):
    store, _ = week
    text = (store / "generated" / "notice-2026-11.md").read_text(encoding="utf-8")
    assert text.startswith(notice.SIMULATED_LINE)
    assert notice.draft_problems(text) == []


def test_every_receipt_is_the_fixture_drivers_and_every_sign_off_is_an_event(week):
    store, _ = week
    receipts = sorted((store / "receipts").glob("sim-*.json"))
    assert len(receipts) == 20  # two rounds a weekday
    assert all(json.loads(p.read_text(encoding="utf-8"))["driver"] == "fixture" for p in receipts)
    assert all(validate(json.loads(p.read_text(encoding="utf-8")), "receipt.schema.json") == [] for p in receipts)


def test_the_same_arguments_write_the_same_log(week, tmp_path):
    store, _ = week
    again = tmp_path / "again"
    simulate.simulate(again, weeks=1, end=END)
    def content(p):  # every field but the event id, which hashes the store it was written in
        return [{k: v for k, v in json.loads(line).items() if k != "id"}
                for line in (p / app.EVENT_LOG).read_text(encoding="utf-8").splitlines()]

    assert content(store) == content(again)


def test_a_store_that_is_not_empty_or_inside_the_repo_is_refused(tmp_path):
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(simulate.SimulationError, match="not empty"):
        simulate.init_store(busy, date(2026, 10, 5), END)
    with pytest.raises(simulate.SimulationError):
        simulate.init_store(ROOT / "sim-store", date(2026, 10, 5), END)
    assert not (ROOT / "sim-store").exists()


def test_a_previous_simulation_is_replaced_only_with_reset(tmp_path):
    store = tmp_path / "s"
    simulate.init_store(store, date(2026, 10, 5), END)
    with pytest.raises(simulate.SimulationError, match="--reset"):
        simulate.init_store(store, date(2026, 10, 5), END)
    (store / "events" / "x.txt").write_text("old", encoding="utf-8")
    simulate.init_store(store, date(2026, 10, 5), END, reset=True)
    assert not (store / "events" / "x.txt").exists()


def test_a_simulated_flag_needs_a_pilot_store():
    doc = {"schema": "tm:contract/settings@1", "library": "x", "mailbox": "a@example.com", "it_email": "a@example.com",
           "dpo_email": "a@example.com", "notice_version": "2026-11", "simulated": True}
    assert validate(doc, "settings.schema.json")
    assert validate({**doc, "pilot": True}, "settings.schema.json") == []


def test_a_pilot_store_that_is_not_simulated_still_refuses_the_draft_notice():
    text = "DRAFT for legal review\n\nSome text.\n<!-- draft -->\n"
    assert notice.draft_problems(text)  # what notice_text blocks on outside a simulated store
    assert notice.draft_problems(notice.simulated(text)) == []
    assert notice.simulated(text).startswith(notice.SIMULATED_LINE)


def test_the_cli_refuses_bad_arguments(tmp_path, capsys):
    assert cli.main(["dev-simulate", "--store", str(tmp_path / "x"), "--weeks", "0"]) == 1
    assert "weeks" in capsys.readouterr().err
    assert cli.main(["dev-simulate", "--store", str(tmp_path / "y"), "--end", "soon"]) == 1
