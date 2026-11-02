"""`teachermodel staffing-match` (matching.py, decision 0026): who may teach on a programme's dates, who is free, and their
travel load. Pure rules at their edges, then the whole command on a one-week simulated store with clearances appended."""

import hashlib
import re
from datetime import date

import pytest
import yaml

from teachermodel import app, cli, events, matching, simulate
from teachermodel.matching import Booking

UNIT = "sl:unit/example-agent-loop@1"
REQUEST = {"unit": UNIT, "mode": "in-person", "start": date(2026, 11, 3), "end": date(2026, 11, 5), "region": "IE"}


def test_the_window_is_centred_on_the_programme():
    assert matching.window(date(2026, 11, 3), date(2026, 11, 5), 90) == (date(2026, 9, 20), date(2026, 12, 18))


def travel(start, end):
    return Booking("tm:instructor/x", "prog", start, end, "IE", True)


def test_travel_at_the_flag_share_is_not_flagged_and_above_it_is():
    span = (date(2026, 11, 2), date(2026, 11, 13))  # two working weeks: 10 days
    assert matching.travel_load([travel(date(2026, 11, 2), date(2026, 11, 4))], set(), False, span, 0.30) == \
        (3, 10, 0.3, False)
    assert matching.travel_load([travel(date(2026, 11, 2), date(2026, 11, 5))], set(), False, span, 0.30) == \
        (4, 10, 0.4, True)


def test_a_day_counts_once_and_weekends_and_non_travel_do_not_count():
    span = (date(2026, 11, 2), date(2026, 11, 13))
    home = Booking("tm:instructor/x", "desk", date(2026, 11, 9), date(2026, 11, 13), "IE", False)
    weekend = travel(date(2026, 11, 7), date(2026, 11, 8))
    programme = {date(2026, 11, 3), date(2026, 11, 4)}
    assert matching.travel_load([travel(date(2026, 11, 2), date(2026, 11, 3)), home, weekend], programme, True,
                                span, 0.30)[:2] == (3, 10)
    assert matching.travel_load([], programme, False, span, 0.30)[:2] == (0, 10)


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("matching") / "store"
    try:
        simulate.simulate(s, weeks=1, end=date(2026, 10, 23))
        for slug, modes, expires in (("a1c4f", ["in-person", "remote"], "2027-10-01"), ("d7h2k", ["in-person"], "2026-11-20"),
                                     ("w5r1z", ["in-person"], "2027-10-01")):
            uri = f"tm:instructor/{slug}"
            cid = "tm:clearance/" + hashlib.sha256(slug.encode()).hexdigest()[:16]
            events.append(s / app.EVENT_LOG, events.make_event(
                "clearance", uri, "tm:system/teachermodel",
                {"clearance": cid, "candidate": f"tm:candidate/{slug}--example-agent-loop-1--in-person",
                 "instructor": uri, "unit": UNIT, "modes": modes, "outcome": "cleared", "conditions": [],
                 "recheck": None, "clearers": ["tm:person/clearer-a", "tm:person/clearer-b"],
                 "observations": ["obs-00000001"], "issued": "2026-10-01", "expires": expires,
                 "framework_version": "1.1.0"}, at="2026-10-01T09:00:00+00:00"))
        bookings = {"schema": "tm:contract/bookings@1", "bookings": [
            {"instructor": "tm:instructor/a1c4f", "ref": "prog-x", "from": "2026-11-04", "to": "2026-11-05",
             "region": "IE", "travel": True},
            {"instructor": "tm:instructor/w5r1z", "ref": "prog-y", "from": "2026-10-05", "to": "2026-11-01",
             "region": "IE", "travel": True}]}
        (s / "inputs").mkdir(exist_ok=True)
        (s / matching.BOOKINGS).write_text(yaml.safe_dump(bookings), encoding="utf-8")
        yield s
    finally:
        mp.undo()


def test_the_match_orders_free_before_booked_and_flags_heavy_travel(store):
    rows, view = matching.staffing_match(store, REQUEST)
    by = {r.instructor.split("/")[1]: r for r in rows}
    assert [r.instructor.split("/")[1] for r in rows] == ["w5r1z", "a1c4f", "d7h2k"]
    assert by["w5r1z"].verdict == "ok" and by["w5r1z"].travel_days == 23 and by["w5r1z"].window_days == 65
    assert by["w5r1z"].travel_flag  # 20 days of bookings and the 3 programme days away from US-CA: 35%
    assert by["a1c4f"].booked == ["prog-x"] and not by["a1c4f"].travel_flag
    assert by["d7h2k"].verdict == "warn" and by["d7h2k"].expires == date(2026, 11, 20)
    assert "e8n3b" not in by  # no clearance: blocked, left out
    html = view.read_text(encoding="utf-8")
    assert "35% (23 of 65 days) over" in html and "prog-x" in html and "operational defaults" in html


def test_all_includes_the_blocked(store):
    rows, _ = matching.staffing_match(store, REQUEST, include_blocked=True)
    blocked = [r for r in rows if r.verdict == "block"]
    assert blocked and rows[-1].verdict == "block" and blocked[0].reasons


def test_a_real_store_refuses_bookings_until_retention_covers_them(store):
    with pytest.raises(matching.MatchError, match="booking-records"):
        matching.load_bookings(store, {})
    assert matching.load_bookings(store, {"simulated": True})


def test_a_bad_bookings_file_is_refused(store, tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / matching.BOOKINGS).write_text(yaml.safe_dump({"schema": "tm:contract/bookings@1", "bookings": [
        {"instructor": "tm:instructor/a1c4f", "ref": "Acme Corp", "from": "2026-11-04", "to": "2026-11-05",
         "region": "IE", "travel": True}]}), encoding="utf-8")
    with pytest.raises(matching.MatchError, match="bookings/0/ref"):
        matching.load_bookings(tmp_path, {"simulated": True})


def test_without_bookings_the_view_says_so(tmp_path):
    assert matching.load_bookings(tmp_path, {}) is None
    html = matching.page([], REQUEST, {"staffing": {"travel_window_days": 90, "travel_flag_share": 0.3}}, False)
    assert "No bookings file" in html and "Nobody may teach it" in html


def test_the_command_prints_and_refuses_a_bad_mode(store, capsys):
    assert cli.main(["staffing-match", "--private-dir", str(store), "--unit", UNIT, "--mode", "in-person",
                     "--from", "2026-11-03", "--to", "2026-11-05", "--region", "IE"]) == 0
    out = capsys.readouterr().out
    assert "tm:instructor/w5r1z" in out and "OVER" in out and "3 instructor(s)" in out
    rows = [line for line in out.splitlines() if line.startswith(("ok", "warn"))]
    assert rows and all(re.search(r"expires (\d{4}-\d{2}-\d{2}|-) ", line) for line in rows)  # the date, not "10"
    assert cli.main(["staffing-match", "--private-dir", str(store), "--unit", UNIT, "--mode", "online",
                     "--from", "2026-11-03", "--to", "2026-11-05"]) == 1
    assert "mode must be" in capsys.readouterr().err


def test_bookings_at_2_carry_an_export_date_and_at_1_is_still_read(tmp_path):
    one = {"instructor": "tm:instructor/a1c4f", "ref": "prog-x", "from": "2026-11-04", "to": "2026-11-05",
           "region": "IE", "travel": True}
    (tmp_path / "inputs").mkdir()
    path = tmp_path / matching.BOOKINGS
    path.write_text(yaml.safe_dump({"schema": "tm:contract/bookings@2", "exported_at": "2026-10-28T07:00:00Z",
                                    "bookings": [one]}), encoding="utf-8")
    assert [b.ref for b in matching.load_bookings(tmp_path, {"simulated": True})] == ["prog-x"]
    path.write_text(yaml.safe_dump({"schema": "tm:contract/bookings@2", "bookings": [one]}), encoding="utf-8")
    with pytest.raises(matching.MatchError, match="bookings@2"):
        matching.load_bookings(tmp_path, {"simulated": True})
    path.write_text(yaml.safe_dump({"schema": "tm:contract/bookings@1", "bookings": [one]}), encoding="utf-8")
    assert matching.load_bookings(tmp_path, {"simulated": True})
