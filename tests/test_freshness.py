"""freshness.py: when each source last reported, against how often it should (standards/freshness.yaml, decision 0027).
The pure assessment at its edges, then the readers on a one-week simulated store. Generated data only."""

from datetime import date, datetime, timedelta, timezone

import pytest
import yaml

from teachermodel import freshness, simulate

NOW = datetime(2026, 10, 30, 7, 0, tzinfo=timezone.utc)


def src(read="schedule-export", every=7, grace=2):
    return freshness.Source(id="s", title="Session schedule", owner="coordinator", every_days=every,
                            grace_days=grace, read=read)


def test_a_source_turns_stale_after_its_cadence_and_grace():
    s = src()
    edge = NOW - timedelta(days=9)
    assert freshness.assess([s], {"s": edge}, NOW)[0].state == "ok"
    assert freshness.assess([s], {"s": edge - timedelta(seconds=1)}, NOW)[0].state == "stale"
    late = freshness.assess([s], {"s": edge - timedelta(days=3)}, NOW)[0]
    assert (late.state, late.due, late.days_late) == ("stale", NOW - timedelta(days=3), 3)


def test_never_and_not_connected_are_states_of_their_own():
    assert freshness.assess([src()], {"s": None}, NOW)[0].state == "never"
    assert freshness.assess([src(read="not-connected")], {}, NOW)[0].state == "not-connected"


def test_the_register_names_every_source_with_an_owner():
    sources = freshness.sources()
    assert {s.id for s in sources} >= {"daily-job", "lab-outcomes", "schedule", "bookings", "release-check"}
    assert all(s.owner and s.every_days > 0 for s in sources)


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("freshness") / "store"
    try:
        simulate.simulate(s, weeks=1, end=date(2026, 10, 23))
        yield s
    finally:
        mp.undo()


def test_status_reads_the_store(store):
    (store / "logs").mkdir(exist_ok=True)
    (store / "logs" / "daily.log").write_text("2026-10-28T07:00:01+00:00 tick ok: 3 page(s)\n"
                                              "2026-10-29T07:00:02+00:00 tick ok: 0 page(s)\n", encoding="utf-8")
    (store / "inputs").mkdir(exist_ok=True)
    (store / "inputs" / "schedule.yaml").write_text(yaml.safe_dump(
        {"schema": "tm:contract/schedule@1", "exported_at": "2026-10-15T07:00:00Z", "sessions": []}), encoding="utf-8")
    got = {s.source.id: s for s in freshness.status(store, NOW)}
    assert got["daily-job"].last == datetime(2026, 10, 29, 7, 0, 2, tzinfo=timezone.utc)
    assert got["daily-job"].state == "ok"
    assert (got["schedule"].state, got["schedule"].days_late) == ("stale", 6)
    assert got["release-check"].state == "never"  # connected (decision 0028); no run kept yet
    assert got["bookings"].state == "never"


def test_the_release_check_reads_the_kept_status_and_bookings_their_export_date(tmp_path):
    import json
    import os

    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "release-status.json").write_text(json.dumps(
        {"schema": "tm:contract/release-status@1", "source": "proving-ground", "run_at": "2026-10-19T07:40:00+00:00",
         "labs": [], "shared": {"status": "passed", "checks": 9, "failed": 0}}), encoding="utf-8")
    bookings = tmp_path / "inputs" / "bookings.yaml"
    bookings.write_text(yaml.safe_dump({"schema": "tm:contract/bookings@2", "exported_at": "2026-10-28T07:00:00Z",
                                        "bookings": []}), encoding="utf-8")
    got = {s.source.id: s for s in freshness.status(tmp_path, NOW)}
    assert (got["release-check"].state, got["release-check"].days_late) == ("stale", 2)  # 8 days is the limit
    assert got["bookings"].last == datetime(2026, 10, 28, 7, 0, tzinfo=timezone.utc)
    bookings.write_text(yaml.safe_dump({"schema": "tm:contract/bookings@1", "bookings": []}), encoding="utf-8")
    os.utime(bookings, (NOW.timestamp() - 86400, NOW.timestamp() - 86400))
    got = {s.source.id: s for s in freshness.status(tmp_path, NOW)}
    assert got["bookings"].last == NOW - timedelta(days=1)  # @1 has no export date: the file's time
