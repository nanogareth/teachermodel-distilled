"""The tour script (scripts/tour.py): the run sheet is current and every command it runs parses.

The tour itself runs on a 26-week simulated store, too slow for the suite; `py scripts/tour.py --check` runs it.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from teachermodel import cli

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "tour.py"


@pytest.fixture(scope="module")
def tour():
    spec = importlib.util.spec_from_file_location("tour", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def test_run_sheet_is_current(tour):
    assert tour.SHEET.read_text(encoding="utf-8") == tour.render_sheet(), "run: py scripts/tour.py --sheet"


def test_every_command_parses(tour):
    parser = cli._build_parser()
    for stop in tour.STOPS:
        for item in stop.show:
            if isinstance(item, tour.Run):
                parser.parse_args([a.format(partner_clearance="tm:clearance/0000000000000000") for a in item.args])


def test_every_stop_has_a_known_audience_and_something_to_show(tour):
    for stop in tour.STOPS:
        assert stop.audiences and set(stop.audiences) <= set(tour.AUDIENCES), stop.title
        assert stop.say and stop.show, stop.title


def test_kept_values_are_kept_before_use(tour):
    kept = {item.keep for stop in tour.STOPS for item in stop.show if isinstance(item, tour.Run) and item.keep}
    used = {a[1:-1] for stop in tour.STOPS for item in stop.show if isinstance(item, tour.Run)
            for a in item.args if a.startswith("{")}
    assert used <= kept


def test_the_store_is_refused_inside_the_repo(tour):
    with pytest.raises(SystemExit):
        tour.main(["--store", str(SCRIPT.parent / "store"), "--check"])
