"""`teachermodel history` and `teachermodel audit-export` (history.py, increment 4 item 5): a clearance's whole history from
the event log alone, and a quarter's audit samples. Fictional people only."""

import json
from datetime import timedelta

import pytest
from test_clearance import C5, CAND, D1, D2, P3, T0, cleared, decide, issued

import test_clearance

from teachermodel import app, cli, history

ready = test_clearance.ready


@pytest.fixture
def cleared_store(fictional_store, ready):
    ready()
    decide(fictional_store, D1, P3, cleared())
    decide(fictional_store, D2, C5, cleared())
    app.do_run(fictional_store, now=T0 + timedelta(days=2))
    (event,) = issued(fictional_store)
    return fictional_store, event["payload"]["clearance"]


def test_the_history_names_the_candidate_observations_dry_run_round_decisions_and_clearance(cleared_store):
    store, cid = cleared_store
    rep = history.clearance_history(store, cid)
    assert rep.ok, rep.all_lines()
    text = "\n".join(rep.lines)
    kinds = [line.split()[2] for line in rep.lines]
    assert {"subject", "dry_run", "signoff", "step", "clearance"} <= set(kinds)
    assert kinds.count("observation") >= 2
    assert f"{D1.split('/', 1)[1]}" in text and f"{D2.split('/', 1)[1]}" in text
    assert CAND in rep.summary and "on record" in rep.summary


def test_the_history_holds_no_private_text(cleared_store):
    store, cid = cleared_store
    text = "\n".join(history.clearance_history(store, cid).all_lines())
    assert "@" not in text.replace("tm:", "").replace("sl:unit/example-agent-loop@1", "")


def test_an_unknown_clearance_is_refused(fictional_store, capsys):
    with pytest.raises(app.AppError, match="not a clearance"):
        history.clearance_history(fictional_store, "tm:clearance/0000000000000000")
    assert cli.main(["history", "--private-dir", str(fictional_store), "--clearance", "tm:clearance/x"]) == 1


def test_the_history_command(cleared_store, capsys):
    store, cid = cleared_store
    assert cli.main(["history", "--private-dir", str(store), "--clearance", cid]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith("history: ")


def test_audit_export_writes_the_quarter_and_refuses_a_bad_quarter(fictional_store, capsys):
    rep = history.audit_export(fictional_store, "2026Q3")
    doc = json.loads((fictional_store / "exports" / "audit-2026Q3.json").read_text(encoding="utf-8"))
    assert doc["quarter"] == "2026Q3" and doc["summary"]["drawn"] == len(doc["samples"]) and "audit-export" in rep.summary
    with pytest.raises(app.AppError, match="quarter"):
        history.audit_export(fictional_store, "Q3")
    assert cli.main(["audit-export", "--private-dir", str(fictional_store), "--quarter", "2026Q3"]) == 0
