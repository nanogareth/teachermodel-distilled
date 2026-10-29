"""`teachermodel index` (index.py, increment 4 item 2): the disposable SQLite index, rebuilt from the event log. Run on a
one-week simulated store (generated data only)."""

import sqlite3
from datetime import date

import pytest

from teachermodel import app, cli, events, index, simulate


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    store = tmp_path_factory.mktemp("index") / "store"
    try:
        simulate.simulate(store, weeks=1, end=date(2026, 10, 23))
        index.build(store)
        yield store
    finally:
        mp.undo()


def query(store, sql):
    con = sqlite3.connect(store / index.INDEX)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def dump(store):
    con = sqlite3.connect(store / index.INDEX)
    try:
        return list(con.iterdump())
    finally:
        con.close()


def test_the_index_holds_every_event_and_the_records_by_kind(built):
    log = app.read_events(built)
    assert query(built, "SELECT count(*) FROM events") == [(len(log),)]
    for table, kind in (("observations", "observation"), ("dry_runs", "dry_run"), ("calibrations", "calibration"),
                        ("signoffs", "signoff"), ("level_changes", "level_change")):
        assert query(built, f"SELECT count(*) FROM {table}") == [(sum(e["kind"] == kind for e in log),)], table
    assert query(built, "SELECT count(*) FROM instructors") == [(len(simulate.INSTRUCTORS),)]


def test_levels_are_the_latest_and_registrations_keep_the_start(built):
    rows = dict(query(built, "SELECT uri, level FROM instructors"))
    st = app.load_state(built)
    from teachermodel.flows.common import current_level

    assert rows == {u: current_level(st, u) for u in st.registrations}


def test_the_index_holds_no_names_or_addresses(built):
    raw = (built / index.INDEX).read_bytes()
    assert b"@example.com" not in raw and b"Sim " not in raw


def test_a_rebuild_gives_the_same_contents_and_a_new_event_makes_it_stale(built):
    before = dump(built)
    assert index.is_current(built)
    index.build(built)
    assert dump(built) == before
    events.append(built / app.EVENT_LOG, events.make_event("check", "tm:programme/teachermodel", "tm:system/teachermodel",
                                                           {"step": None, "result": "ok"}))
    assert not index.is_current(built)
    index.build(built)
    assert index.is_current(built)


def test_the_index_command(built, capsys):
    assert cli.main(["index", "--private-dir", str(built)]) == 0
    assert "index:" in capsys.readouterr().out
    assert not (built / "index" / "teachermodel.building").exists()
