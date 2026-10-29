"""Decision 0016: a pilot store (settings `pilot: true`, or any store in the user's own OneDrive folder) takes only
generated instructors, whose emails are on reserved domains. Fictional fixtures only."""

from datetime import datetime, timezone

import pytest
import yaml
from test_roster_gate import seed_all

from teachermodel import app, config, roster, setup
from teachermodel.standards import validate

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
REAL = "real-company.ie"  # stands for any domain a real mailbox could be on


@pytest.mark.parametrize("email", ["a@example.com", "a@EXAMPLE.ORG", "a@team.example.net", "a@x.test", "a@x.invalid",
                                   "a@x.example", "a@box.localhost", "a@example.com."])
def test_reserved_domains(email):
    assert roster.is_reserved_email(email)


@pytest.mark.parametrize("email", [f"a@{REAL}", "a@example.co", "a@notexample.com", "a@example.com.evil.io",
                                   "a@testing.io", "no-at-sign", "a@b@example.com", None, 7])
def test_other_domains_are_not_reserved(email):
    assert not roster.is_reserved_email(email)


def test_a_refusal_names_the_instructor_and_domain_but_never_the_address():
    doc = {"instructors": [{"instructor": "tm:instructor/a", "identity": {"name": "A", "email": f"pat.real@{REAL}"}},
                           {"instructor": "tm:instructor/b", "identity": {"name": "B", "email": "b@example.com"}}]}
    assert roster.pilot_refusals(doc) == [f"tm:instructor/a: {REAL} is not a reserved domain"]
    assert roster.pilot_refusals({"no": "instructors"})


def test_the_settings_contract_takes_an_optional_boolean_pilot():
    base = {"schema": "tm:contract/settings@1", "library": "L", "mailbox": "m@example.com",
            "it_email": "i@example.com", "dpo_email": "d@example.com", "notice_version": "2026-11"}
    assert validate(base, "settings.schema.json") == []
    assert validate({**base, "pilot": True}, "settings.schema.json") == []
    assert validate({**base, "pilot": "yes"}, "settings.schema.json")


def _mark_pilot(store):
    path = store / "settings.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    path.write_text(yaml.safe_dump({**doc, "pilot": True}), encoding="utf-8", newline="\n")


def _with_real_instructor(example_roster):
    doc = yaml.safe_load(example_roster.read_text(encoding="utf-8"))
    doc["instructors"][1]["identity"]["email"] = f"someone@{REAL}"
    example_roster.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8", newline="\n")
    return doc["instructors"][1]["instructor"]


def test_a_pilot_store_imports_generated_instructors(fictional_store, privacy_root, example_roster):
    _mark_pilot(fictional_store)
    seed_all(fictional_store, privacy_root)
    rep = app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)
    assert "import-roster:" in rep.summary


def test_a_pilot_store_refuses_a_real_instructor_before_copying_anything(fictional_store, privacy_root, example_roster):
    _mark_pilot(fictional_store)
    seed_all(fictional_store, privacy_root)
    uri = _with_real_instructor(example_roster)
    events_before = (fictional_store / "events" / "events.jsonl").read_bytes()
    with pytest.raises(app.AppError) as exc:
        app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)
    assert f"{uri}: {REAL} is not a reserved domain" in str(exc.value) and "someone@" not in str(exc.value)
    assert not (fictional_store / "imports").exists()  # the file never entered the pilot store
    assert not (fictional_store / "identities" / "roster.yaml").exists()
    assert (fictional_store / "events" / "events.jsonl").read_bytes() == events_before


def test_the_import_function_reads_the_pilot_flag_itself(fictional_store, privacy_root, example_roster):
    """Second lock: a direct call that passes no settings still applies the store's own flag."""
    _mark_pilot(fictional_store)
    _with_real_instructor(example_roster)
    with pytest.raises(setup.SetupError, match="pilot store"):
        setup.pilot_check(fictional_store, None, roster.load(example_roster))


def test_a_store_without_the_flag_takes_real_domains(fictional_store, privacy_root, example_roster):
    seed_all(fictional_store, privacy_root)
    _with_real_instructor(example_roster)
    app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)


def test_a_store_in_a_personal_onedrive_folder_must_be_marked_pilot(fictional_store, example_roster, monkeypatch):
    monkeypatch.setenv("OneDriveCommercial", str(fictional_store.parent))
    assert config.in_personal_onedrive(fictional_store)
    with pytest.raises(setup.SetupError, match="personal OneDrive folder"):
        setup.pilot_check(fictional_store, None, roster.load(example_roster))
    _mark_pilot(fictional_store)
    setup.pilot_check(fictional_store, None, roster.load(example_roster))  # generated instructors only: accepted


def test_a_synced_library_beside_onedrive_is_not_a_personal_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("OneDriveCommercial", str(tmp_path / "OneDrive - Org"))
    for var in ("OneDriveConsumer", "OneDrive"):
        monkeypatch.delenv(var, raising=False)
    assert not config.in_personal_onedrive(tmp_path / "Org" / "Site - TeacherModel Private")
    assert config.in_personal_onedrive(tmp_path / "OneDrive - Org" / "teachermodel-pilot")
