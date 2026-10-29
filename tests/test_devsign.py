"""`teachermodel dev-autosign` (owner, 2026-10-27): generated sign-offs walk a pilot store forward. Fictional data only."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from test_roster_gate import seed_all

from teachermodel import app, cli, devsign, pilot, records

OWNER = {"owner_name": "Olive Owner", "owner_email": "olive.owner@company.ie"}
T0 = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
CLEARERS = {"tm:instructor/v6k2r", "tm:instructor/m8t4w", "tm:instructor/h3q9n"}


def _clock():
    t = [T0]

    def tick():
        t[0] += timedelta(minutes=1)
        return t[0]
    return tick


def _store(tmp_path, privacy_root):
    """A pilot store whose privacy base is done (library, profile, DPIA, retention): the roster import is next."""
    s = tmp_path / "pilot"
    pilot.init_pilot(s, **OWNER, set_env=False, root=privacy_root)
    seed_all(s, privacy_root)
    return s


@pytest.fixture(scope="module")
def walked(tmp_path_factory):
    """One full run, shared by the tests that read its result (a run takes about half a minute)."""
    from privacy_helpers import make_privacy_root

    with pytest.MonkeyPatch.context() as mp:  # conftest's AppData redirect is per test; this fixture outlives one
        mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
        mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
        tmp = tmp_path_factory.mktemp("devsign")
        root = make_privacy_root(tmp)
        store = _store(tmp, root)
        yield store, root, devsign.autosign(store, root=root, clock=_clock())


def test_a_run_walks_the_pilot_from_the_roster_import_to_clearance(walked):
    store, root, rep = walked
    assert rep.ok and not [line for line in rep.lines if line.startswith("rejected")], rep.all_lines()
    log = app.read_events(store)
    assert set(records.calibrations(log)) == CLEARERS  # the clearers scored the reference and passed
    issued = {e["subject_uri"] for e in log if e["kind"] == "clearance"}
    candidates = {u for u, info in app.load_state(store, root).subjects.items() if info.get("kind") == "candidate"}
    assert candidates and candidates <= issued  # both clearers decided on every candidate
    clearances = [e["payload"] for e in log if e["kind"] == "clearance"]
    assert any(p.get("founding") is True for p in clearances)  # no seed: the first ones came from founding rounds (0017)
    assert all(e["actor"] == "tm:system/teachermodel" and e["payload"]["candidate"] in candidates
               for e in log if e["kind"] == "clearance")
    assert any(e["kind"] == "signoff" and e["payload"]["step"] == "tm:step/levels-decided" for e in log)
    assert any("only the next coaching cycle is left" in line for line in rep.lines)


def test_optional_records_are_left_alone(walked):
    store, _, _ = walked
    signed = {e["payload"]["step"] for e in app.read_events(store) if e["kind"] == "signoff"}
    assert not signed & devsign.SKIP_STEPS


def test_the_owner_pages_are_signed_unless_generated_only(walked, tmp_path, privacy_root):
    store, _, _ = walked
    assert any(e["kind"] == "signoff" and e["actor"] == pilot.OWNER for e in app.read_events(store))
    fresh = _store(tmp_path, privacy_root)
    before = {e["id"] for e in app.read_events(fresh) if e["kind"] == "signoff" and e["actor"] == pilot.OWNER}
    devsign.autosign(fresh, root=privacy_root, clock=_clock(), rounds=3, generated_only=True)
    after = {e["id"] for e in app.read_events(fresh) if e["kind"] == "signoff" and e["actor"] == pilot.OWNER}
    assert after == before


def test_a_store_that_is_not_a_pilot_refuses(tmp_path, privacy_root):
    store = _store(tmp_path, privacy_root)
    settings = store / "settings.yaml"
    doc = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings.write_text(yaml.safe_dump({k: v for k, v in doc.items() if k != "pilot"}), encoding="utf-8")
    with pytest.raises(devsign.DevSignError, match="only in a pilot store"):
        devsign.autosign(store, root=privacy_root, clock=_clock())


def test_answers_rotate_the_observer_tick_a_domain_and_score_the_reference():
    data = {"template": "approve", "inputs": {}, "fields": [
        {"name": "observer", "kind": "enum", "options": ["tm:instructor/a", "tm:instructor/b"], "required": True},
        {"name": "domain-x", "kind": "bool", "required": False},
        {"name": "domain-y", "kind": "bool", "required": False},
        {"name": "x", "kind": "evidence_score", "required": True},
        {"name": "hours", "kind": "number", "required": True, "min": 0.5},
    ]}
    first = devsign.answers(data, date(2026, 10, 26), scores={"x": 2})
    assert first["observer"] == "tm:instructor/a" and first["domain-x"] is True and "domain-y" not in first
    assert first["x"]["score"] == 2 and first["x"]["note"] and first["hours"] == 0.5
    assert devsign.answers(data, date(2026, 10, 26), turn=1)["observer"] == "tm:instructor/b"
    dpia = {"template": "dpia_screening", "inputs": {}, "fields": [
        {"name": "dpo-decision", "kind": "enum", "options": ["dpia-required", "dpia-not-required"], "required": True}]}
    assert devsign.answers(dpia, date(2026, 10, 26))["dpo-decision"] == "dpia-not-required"  # the 2026-10-27 pilot loop


def test_a_second_run_submits_no_sign_off_the_log_already_holds(walked):
    store, root, _ = walked
    known = devsign._seen_ids(app.load_state(store, root))
    devsign.autosign(store, root=root, clock=_clock(), rounds=3)
    runs = sorted((store / "dev-autosign").iterdir())
    assert len(runs) == 2  # one folder per run
    assert not {json.loads(f.read_text(encoding="utf-8"))["id"] for f in runs[-1].rglob("*.json")} & known


def test_the_cli_refuses_outside_a_pilot_store(fictional_store, capsys):
    assert cli.main(["dev-autosign", "--private-dir", str(fictional_store)]) != 0
    assert "pilot store" in capsys.readouterr().err
