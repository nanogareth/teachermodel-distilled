"""feeds.py: the release status and results-received feeds (decision 0028), kept as inputs, and the store's inbox the
daily job drains. Generated data only."""

import json
from datetime import datetime, timezone

import pytest

from teachermodel import daily, feeds

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def status(run_at="2026-11-02T07:40:00+00:00", **lab):
    return {"schema": "tm:contract/release-status@1", "source": "proving-ground", "run_at": run_at,
            "labs": [{"lab": "aggregates-only-export", "unit": None, "status": "passed", "checks": 1, "failed": 0}
                     | lab],
            "shared": {"status": "passed", "checks": 9, "failed": 0}}


def received(**row):
    return {"schema": "tm:contract/results-received@1", "source": "proving-ground",
            "exported_at": "2026-10-29T09:00:00+00:00",
            "deliveries": [{"delivery_ref": "agent-loop-g2", "received": 14, "unreadable": 1} | row]}


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_a_release_status_is_checked_and_kept(tmp_path):
    got = feeds.import_feed(tmp_path, write(tmp_path / "in.json", status()))
    assert got.schema == "tm:contract/release-status@1"
    assert (tmp_path / "inputs" / "release-status.json").exists()
    assert feeds.load(tmp_path, feeds.RELEASE)["labs"][0]["lab"] == "aggregates-only-export"
    assert feeds.load(tmp_path, feeds.RECEIVED) is None


def test_every_problem_is_listed_and_nothing_is_written(tmp_path):
    bad = status(status="green", detail="C:/Users/someone/lab: 3 failed")
    with pytest.raises(feeds.FeedError) as err:
        feeds.import_feed(tmp_path, write(tmp_path / "in.json", bad))
    text = str(err.value)
    assert "green" in text and "detail" in text
    assert not (tmp_path / "inputs").exists()


def test_an_unknown_or_missing_schema_is_refused(tmp_path):
    with pytest.raises(feeds.FeedError, match="not a feed"):
        feeds.import_feed(tmp_path, write(tmp_path / "in.json", {"schema": "tm:contract/outcome-import@1"}))
    with pytest.raises(feeds.FeedError, match="not a feed"):
        feeds.import_feed(tmp_path, write(tmp_path / "in.json", ["no", "object"]))


def test_an_older_run_never_replaces_a_newer_one(tmp_path):
    feeds.import_feed(tmp_path, write(tmp_path / "new.json", status()))
    with pytest.raises(feeds.FeedError, match="older"):
        feeds.import_feed(tmp_path, write(tmp_path / "old.json", status(run_at="2026-10-26T07:40:00+00:00")))
    assert feeds.load(tmp_path, feeds.RELEASE)["run_at"] == "2026-11-02T07:40:00+00:00"


def test_results_received_carry_counts_and_never_a_score(tmp_path):
    feeds.import_feed(tmp_path, write(tmp_path / "r.json", received()))
    assert feeds.load(tmp_path, feeds.RECEIVED)["deliveries"][0]["received"] == 14
    with pytest.raises(feeds.FeedError, match="score"):
        feeds.import_feed(tmp_path, write(tmp_path / "r2.json", received(score=83.3)))


def test_the_inbox_keeps_good_files_and_sets_bad_ones_aside_with_reasons(tmp_path):
    write(tmp_path / "inbox" / "release-status-2026-11-02.json", status())
    write(tmp_path / "inbox" / "results-received.json", received(received=-1))
    (tmp_path / "inbox" / "notes.txt").write_text("not json", encoding="utf-8")
    lines = feeds.drain_inbox(tmp_path)
    assert (tmp_path / "inbox" / "done" / "release-status-2026-11-02.json").exists()
    assert (tmp_path / "inbox" / "refused" / "results-received.json").exists()
    assert "received" in (tmp_path / "inbox" / "refused" / "results-received.json.why.txt").read_text(encoding="utf-8")
    assert (tmp_path / "inbox" / "refused" / "notes.txt").exists()
    assert not [p for p in (tmp_path / "inbox").iterdir() if p.is_file()]
    assert sum("kept" in line for line in lines) == 1 and sum("refused" in line for line in lines) == 2
    assert feeds.drain_inbox(tmp_path) == []  # done/ and refused/ are not read again


def test_the_daily_job_drains_the_inbox_first_and_logs_it(tmp_path, monkeypatch):
    (tmp_path / "settings.yaml").write_text("x: 1\n", encoding="utf-8")
    write(tmp_path / "inbox" / "release-status.json", status())
    monkeypatch.setattr(daily.setup, "load_settings", lambda private: {})
    monkeypatch.setattr(daily.app, "do_tick", lambda private, now, root: [daily.app.Report(summary="0 page(s)")])
    daily.daily(tmp_path, now=NOW)
    log = (tmp_path / "logs" / "daily.log").read_text(encoding="utf-8")
    assert "inbox ok: 1 kept" in log
    assert feeds.load(tmp_path, feeds.RELEASE) is not None


def test_the_command_keeps_a_feed_and_refuses_a_bad_one(tmp_path, capsys):
    from teachermodel import cli

    assert cli.main(["import-feed", "--private-dir", str(tmp_path), str(write(tmp_path / "s.json", status()))]) == 0
    assert "kept as inputs/release-status.json" in capsys.readouterr().out
    assert cli.main(["import-feed", "--private-dir", str(tmp_path),
                     str(write(tmp_path / "r.json", received(unreadable="one")))]) == 1
    assert "unreadable" in capsys.readouterr().err


def room_summary(room_id="a-lab-202610010900-abcd", ended="2026-10-01T10:30:00+00:00", held=9, marks=(), lab="a-lab"):
    return {"schema": feeds.ROOM, "source": "generated", "room_id": room_id, "lab": lab,
            "started_at": "2026-10-01T09:00:00+00:00", "ended_at": ended, "minutes": 90, "devices": 24,
            "steps": [{"step": 2, "title": "Property 1", "reached": 20, "stuck_at_end": 1, "stuck_peak": 9,
                       "long_stuck_peak": 8, "held_minutes": held}],
            "marks": list(marks), "refused": 0}


def test_a_room_summary_is_kept_one_file_per_room_and_a_later_one_replaces_it(tmp_path):
    source = tmp_path / "room.json"
    source.write_text(json.dumps(room_summary()), encoding="utf-8")
    got = feeds.import_feed(tmp_path, source)
    assert got.path == tmp_path / "inputs" / "rooms" / "a-lab-202610010900-abcd.json"
    source.write_text(json.dumps(room_summary(ended="2026-10-01T10:45:00+00:00", held=12)), encoding="utf-8")
    feeds.import_feed(tmp_path, source)
    assert [r["steps"][0]["held_minutes"] for r in feeds.returns(tmp_path, feeds.ROOM)] == [12]
    source.write_text(json.dumps(room_summary(ended="2026-10-01T10:00:00+00:00", held=1)), encoding="utf-8")
    with pytest.raises(feeds.FeedError, match="received already"):
        feeds.import_feed(tmp_path, source)


@pytest.mark.parametrize("extra", [{"session": "s-1"}, {"instructor": "tm:instructor/a1c4f"}, {"device": "0123456789abcdef"}])
def test_a_room_summary_may_not_carry_a_session_an_instructor_or_a_device(extra):
    assert feeds.problems({**room_summary(), **extra})
