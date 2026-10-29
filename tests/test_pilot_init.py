"""`teachermodel init-pilot` (decision 0016; owner, 2026-10-26: automate the setup, with generated data and scaffolding).
Fictional owner only."""

from datetime import datetime, timezone

import pytest
import yaml
from test_roster_gate import seed_all

from teachermodel import app, cli, config, pilot, privacy, roster, setup
from teachermodel.flows.quality import import_outcomes

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
OWNER = {"owner_name": "Olive Owner", "owner_email": "olive.owner@company.ie"}


@pytest.fixture
def store(tmp_path):
    return tmp_path / "OneDrive - Org" / "teachermodel-pilot"


def test_init_writes_the_layout_settings_people_and_generated_inputs(store):
    res = pilot.init_pilot(store, **OWNER, set_env=False)
    for d in pilot.LAYOUT:
        assert (store / d).is_dir()
    settings = setup.load_settings(store)
    assert settings["pilot"] is True and settings["mailbox"] == OWNER["owner_email"]
    assert settings["library"] == "teachermodel-pilot"
    people = config.people(store)
    owner = next(p for p in people if p["person"] == pilot.OWNER)
    assert owner["roles"] == pilot.OWNER_ROLES and owner["email"] == OWNER["owner_email"]
    assert all(p["email"].endswith("@example.com") for p in people if p is not owner)
    doc = roster.load(store / "inputs" / "roster.yaml")
    assert roster.check_roster(doc) == [] and roster.pilot_refusals(doc) == []
    assert sum(r["level"] == "clearer" for r in doc["instructors"]) >= 2  # W4 needs two clearers
    assert (store / "README.md").read_text(encoding="utf-8").startswith("# teachermodel pilot store")
    assert any(line.startswith("wrote") for line in res.lines)


def test_init_is_idempotent_and_keeps_an_edited_file_unless_forced(store):
    pilot.init_pilot(store, **OWNER, set_env=False)
    again = pilot.init_pilot(store, **OWNER, set_env=False)
    assert not any(line.startswith("wrote") for line in again.lines)
    path = store / "settings.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "# my note\n", encoding="utf-8", newline="\n")
    kept = pilot.init_pilot(store, **OWNER, set_env=False)
    assert any(line.startswith("kept       settings.yaml") for line in kept.lines)
    assert path.read_text(encoding="utf-8").endswith("# my note\n")
    pilot.init_pilot(store, **OWNER, set_env=False, force=True)
    assert not path.read_text(encoding="utf-8").endswith("# my note\n")


@pytest.mark.parametrize("email", ["owner@example.com", "not-an-address"])
def test_the_owner_must_give_a_real_mailbox(store, email):
    with pytest.raises(config.ConfigError, match="owner-email"):
        pilot.init_pilot(store, owner_name="Olive", owner_email=email, set_env=False)
    assert not store.exists()


@pytest.mark.parametrize("email", ["olive@gmail.com", "olive@Outlook.com", "olive@googlemail.com."])
def test_the_owner_mailbox_must_be_one_the_connector_reads(store, email):
    # 2026-10-26: a pilot set up with a personal Gmail address; the Microsoft 365 connector never sees its mail
    with pytest.raises(config.ConfigError, match="personal mailbox"):
        pilot.init_pilot(store, owner_name="Olive", owner_email=email, set_env=False)
    assert not store.exists()


def test_init_points_the_user_variable_at_the_store(store, monkeypatch):
    calls = []
    monkeypatch.setattr(pilot, "_user_env", lambda: None)
    monkeypatch.setattr(pilot, "_set_user_env", calls.append)
    monkeypatch.setattr(pilot.sys, "platform", "win32")
    res = pilot.init_pilot(store, **OWNER)
    assert calls == [str(store.resolve())]
    assert any(f"{config.ENV_VAR} set to" in line for line in res.lines)
    monkeypatch.setattr(pilot, "_user_env", lambda: str(store))
    assert any("already points here" in line for line in pilot.init_pilot(store, **OWNER).lines)


def test_the_generated_inputs_import_once_the_workflow_allows(store, privacy_root):
    pilot.init_pilot(store, **OWNER, set_env=False, root=privacy_root)
    seed_all(store, privacy_root)
    rep = app.do_import_roster(store, store / "inputs" / "roster.yaml", now=T0, root=privacy_root)
    assert "import-roster:" in rep.summary
    done = import_outcomes(store, store / "inputs" / "outcomes.yaml", now=T0, root=privacy_root)
    assert done.appended == len(yaml.safe_load((store / "inputs" / "outcomes.yaml").read_text(encoding="utf-8"))
                                ["deliveries"])


def test_a_new_owner_mailbox_reaches_the_it_request_on_the_next_run(store):
    # 2026-10-27: re-run with the work address, the ROPA followed it and the IT request kept the old one
    pilot.init_pilot(store, **OWNER, set_env=False)
    app.do_run(store, now=T0)
    pilot.init_pilot(store, owner_name=OWNER["owner_name"], owner_email="olive@company.ie", force=True, set_env=False)
    app.do_run(store, now=T0.replace(hour=9))
    for rel in ("generated/it-request.md", "generated/it-request.eml", "generated/ropa.md"):
        text = (store / rel).read_text(encoding="utf-8")
        assert "olive@company.ie" in text and OWNER["owner_email"] not in text, rel


def test_init_writes_a_generated_retention_table_that_covers_every_pair(store):
    # owner, 2026-10-27: the pilot stopped at retention-approved; periods for a pilot are generated, never real
    pilot.init_pilot(store, **OWNER, set_env=False)
    path = store / "inputs" / "retention.yaml"
    ret = setup.load_retention(path)
    assert "generated" in ret["basis"] and all("generated" in e["reason"].lower() for e in ret["entries"])
    assert privacy.coverage_gaps(privacy.load_purposes(), ret["entries"], base_only=True) == []
    assert privacy.retention_inputs(setup.ROOT, ret, [])["rows"]  # the approval page has rows to sign


def test_a_pilot_store_reads_its_own_retention_and_any_other_store_the_standard_one(store):
    pilot.init_pilot(store, **OWNER, set_env=False)
    standard = setup.ROOT / "standards" / "retention.yaml"
    settings = setup.load_settings(store)
    assert setup.retention_file(store, settings) == store / "inputs" / "retention.yaml"
    assert setup.retention_file(store, dict(settings, pilot=False)) == standard  # a real store ignores the file
    (store / "inputs" / "retention.yaml").unlink()
    assert setup.retention_file(store, settings) == standard


def test_the_cli_runs_init_pilot(store, capsys):
    code = cli.main(["init-pilot", "--private-dir", str(store), "--owner-name", OWNER["owner_name"],
                     "--owner-email", OWNER["owner_email"], "--no-set-env"])
    assert code == 0 and "is ready" in capsys.readouterr().out
