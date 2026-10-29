"""Integration-review fix 2: no roster is imported before the base workflow is complete. The command checks the engine's
`needs` of roster-import, and the import function checks the facts again (second lock). Fictional fixtures only."""

from datetime import datetime, timezone

import pytest
from privacy_helpers import (
    STEP_DPIA,
    STEP_RETENTION,
    STEP_VERIFIED,
    edit_yaml,
    prerequisite_events,
    seed_check,
    sign_step,
)

from teachermodel import app, setup
from teachermodel.standards import ROOT

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
EXAMPLE_ROSTER = ROOT / "standards" / "templates" / "roster.example.yaml"
NEEDS = ["tm:step/library-exists", STEP_VERIFIED, STEP_DPIA, STEP_RETENTION]


def seed_all(private, root):
    app.do_tick(private, now=T0, root=root)
    seed_check(private, "tm:step/library-exists")
    for step in (STEP_VERIFIED, STEP_DPIA, STEP_RETENTION):
        sign_step(private, root, step)


# --- the command ----------------------------------------------------------------------------------------


def test_the_command_refuses_a_roster_on_a_fresh_store_and_names_what_is_missing(fictional_store, privacy_root, example_roster):
    with pytest.raises(app.AppError) as exc:
        app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)
    for step in NEEDS:
        assert step in str(exc.value)
    assert not (fictional_store / "identities" / "roster.yaml").exists()
    assert not (fictional_store / "imports").exists()  # nothing was copied or kept
    assert not (fictional_store / "events").exists()


def test_the_command_names_only_the_steps_still_missing(fictional_store, privacy_root, example_roster):
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    seed_check(fictional_store, "tm:step/library-exists")
    sign_step(fictional_store, privacy_root, STEP_VERIFIED)
    with pytest.raises(app.AppError) as exc:
        app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)
    msg = str(exc.value)
    assert STEP_DPIA in msg and STEP_RETENTION in msg
    assert "library-exists" not in msg and STEP_VERIFIED not in msg


def test_the_command_imports_once_the_base_workflow_is_complete(fictional_store, privacy_root, example_roster):
    seed_all(fictional_store, privacy_root)
    rep = app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)
    assert "import-roster:" in rep.summary
    assert (fictional_store / "identities" / "roster.yaml").is_file()


def test_the_command_refuses_again_when_a_bound_approval_lapses(fictional_store, privacy_root, example_roster):
    seed_all(fictional_store, privacy_root)
    path = privacy_root / "standards" / "privacy" / "jurisdictions" / "xx.yaml"
    path.write_bytes(path.read_bytes() + b"# edited\n")
    with pytest.raises(app.AppError, match="base-profile-verified"):
        app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)


def test_the_real_standards_refuse_a_roster(fictional_store, example_roster):
    with pytest.raises(app.AppError, match="tm:step/base-profile-verified"):
        app.do_import_roster(fictional_store, example_roster, now=T0)


# --- the second lock inside the import --------------------------------------------------------------------


def run_import(private, root, log):
    return setup.import_roster(private, EXAMPLE_ROSTER, log, T0, root=root)


def test_the_import_function_works_with_every_prerequisite(tmp_path, privacy_root):
    log = prerequisite_events(privacy_root)
    assert [e["kind"] for e in run_import(tmp_path, privacy_root, log)].count("registration") == 4


@pytest.mark.parametrize("without, words", [
    ("library", "library"), ("verified", "base profile"), ("retention", "retention"), ("dpia", "DPIA")])
def test_the_import_function_names_the_missing_prerequisite(tmp_path, privacy_root, without, words):
    log = prerequisite_events(privacy_root, **{without: False})
    with pytest.raises(setup.SetupError, match=f"(?i)import refused.*{words}"):
        run_import(tmp_path, privacy_root, log)
    assert not (tmp_path / "identities").exists()


def test_the_import_function_names_everything_missing_at_once(tmp_path, privacy_root):
    with pytest.raises(setup.SetupError) as exc:
        run_import(tmp_path, privacy_root, [])
    text = str(exc.value).lower()
    for word in ("library", "base profile", "retention", "dpia"):
        assert word in text


def test_a_dpia_signoff_for_other_triggers_is_not_current(tmp_path, privacy_root):
    log = prerequisite_events(privacy_root)
    edit_yaml(privacy_root / "standards" / "privacy" / "jurisdictions" / "xx.yaml",
              lambda d: d["dpia_triggers"].append({"criterion": "large-scale", "citation": "s.50"}))
    # the profile bytes changed too, so the verification lapses; the DPIA is named as well
    with pytest.raises(setup.SetupError, match="DPIA"):
        run_import(tmp_path, privacy_root, log)


def test_a_failed_decision_is_not_a_clearance(tmp_path, privacy_root):
    log = prerequisite_events(privacy_root, dpia_decision="changes")
    with pytest.raises(setup.SetupError, match="DPIA"):
        run_import(tmp_path, privacy_root, log)


def test_the_real_root_refuses_an_import_without_prerequisites(tmp_path):
    with pytest.raises(setup.SetupError, match="base profile"):
        setup.import_roster(tmp_path, EXAMPLE_ROSTER, [], T0)
