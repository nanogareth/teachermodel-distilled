"""CLI over a fictional private store (plan Task 9). Fictional people only."""

import json
from datetime import datetime, timezone

from privacy_helpers import import_roster_ungated

from teachermodel import app, cli
from teachermodel.standards import ROOT, validate


def run(capsys, *argv):
    code = cli.main([str(a) for a in argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_tick_on_fictional_store(fictional_store, capsys):
    code, out, err = run(capsys, "tick", "--private-dir", fictional_store)
    assert code == 0, err
    lines = out.splitlines()
    stages = [ln.split(":")[0] for ln in lines if ln.split(":")[0] in ("run", "plan", "pages", "next")]
    assert stages == ["run", "plan", "pages", "next"]
    steps = [e["payload"].get("step") for e in app.read_events(fictional_store) if e["kind"] == "step"]
    assert "tm:step/it-request" in steps and "tm:step/ropa" in steps  # run executed the auto steps
    queue = [ln for ln in lines if "tm:step/" in ln]
    assert [any(s in ln for ln in queue) for s in ("it-done", "base-profile-verified", "ropa-approved")] == [True] * 3
    assert "tm:step/it-done" in queue[0] and "tm:step/dpia-screening" not in "".join(queue)  # due human steps
    for name in ("it-done--teachermodel--it-1", "base-profile-verified--teachermodel--legal-1",
                 "ropa-approved--teachermodel--dpo-1"):
        assert (fictional_store / "pages" / f"{name}.html").is_file()
    assert (fictional_store / "plans" / "latest.sha256").is_file()


def test_queue_json_has_no_names(fictional_store, example_roster, fictional_names, tmp_path, capsys):
    assert run(capsys, "tick", "--private-dir", fictional_store)[0] == 0
    import_roster_ungated(fictional_store, example_roster, datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc))
    out_json = tmp_path / "queue.json"
    code, _, err = run(capsys, "next", "--private-dir", fictional_store, "--json", out_json)
    assert code == 0, err
    text = out_json.read_text(encoding="utf-8")
    doc = json.loads(text)
    assert validate(doc, "queue.schema.json", ROOT) == []
    assert doc["items"], "queue should not be empty"
    log = (fictional_store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert '"registration"' in log  # the roster really was imported
    for needle in fictional_names:
        assert needle not in text, needle
        assert needle not in log, needle


def test_next_role_filter(fictional_store, capsys):
    run(capsys, "tick", "--private-dir", fictional_store)
    code, out, _ = run(capsys, "next", "--private-dir", fictional_store, "--role", "legal")
    assert code == 0 and "tm:step/base-profile-verified" in out and "tm:step/it-done" not in out
    code, _, err = run(capsys, "next", "--private-dir", fictional_store, "--role", "wizard")
    assert code == 1 and "unknown role" in err


def test_env_dot_refused(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("TEACHERMODEL_PRIVATE_DIR", ".")
    code, _, err = run(capsys, "next")
    assert code == 1 and "0006" in err


def test_no_private_dir_refused(monkeypatch, capsys):
    monkeypatch.delenv("TEACHERMODEL_PRIVATE_DIR", raising=False)
    code, _, err = run(capsys, "next")
    assert code == 1 and "0006" in err


def test_direct_signoff_refused(fictional_store, capsys):
    direct = fictional_store / "direct.json"
    direct.write_text(json.dumps({"schema": "tm:contract/signoff@1"}), encoding="utf-8")
    code, _, err = run(capsys, "ingest", direct, "--private-dir", fictional_store)
    assert code == 1 and "sign-offs arrive only via a receipt (verified sender)" in err


def test_ingest_unknown_plan_refused(fictional_store, capsys):
    run(capsys, "tick", "--private-dir", fictional_store)
    receipt = fictional_store / "r.json"
    receipt.write_text(json.dumps({"schema": "tm:contract/receipt@1", "plan_sha256": "f" * 64,
                                   "driver": "connector", "run_at": "2026-10-26T08:00:00+00:00",
                                   "results": []}), encoding="utf-8")
    code, _, err = run(capsys, "ingest", receipt, "--private-dir", fictional_store)
    assert code == 1 and "no plan" in err


def test_import_roster_error_exits_1(fictional_store, tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema: tm:contract/roster@2\n", encoding="utf-8")
    code, _, err = run(capsys, "import-roster", bad, "--private-dir", fictional_store)
    assert code == 1 and "import-roster refused" in err  # the base workflow is not complete, so nothing is read


def test_existing_commands_still_work(capsys):
    assert run(capsys, "validate")[0] == 0
    assert run(capsys, "check-roster", ROOT / "standards" / "templates" / "roster.example.yaml")[0] == 0
