"""`teachermodel views` (views.py, increment 4 item 3): the clearance matrix, coaching logs, quality review and instructor
records, written from the index. Run on a one-week simulated store (generated data only)."""

from datetime import date

import pytest

from teachermodel import app, cli, events, simulate, views

T_OUTCOME = "2026-10-22T09:00:00+00:00"


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("views") / "store"
    try:
        simulate.simulate(s, weeks=1, end=date(2026, 10, 23))
        uri = "tm:instructor/a1c4f"
        for ref, learners, score in (("v-few", 9, 40.0), ("v-many", 18, 55.0)):  # one below the minimum, one above
            events.append(s / app.EVENT_LOG, events.make_event(
                "outcome", uri, "tm:system/teachermodel",
                {"delivery_ref": ref, "instructor": uri, "unit": "sl:unit/example-agent-loop@1", "mode": "remote",
                 "delivered_on": "2026-10-20", "learners_assessed": learners, "score": score, "baseline": 70.0,
                 "source": "test"}, at=T_OUTCOME))
        views.build(s)
        yield s
    finally:
        mp.undo()


def view(store, name):
    return (store / views.VIEWS / name).read_text(encoding="utf-8")


def test_every_view_is_written(store):
    out = store / views.VIEWS
    for name in ("clearance-matrix.html", "coaching-log.html", "quality-review.html"):
        assert (out / name).is_file(), name
    assert len(list((out / "instructors").glob("*.html"))) == len(simulate.INSTRUCTORS)
    assert list(out.glob("coaching-log--*.html")) or "0 cycle(s)" in view(store, "coaching-log.html")


def test_the_matrix_has_its_filters_and_flags(store):
    html = view(store, "clearance-matrix.html")
    for f in ("f-type", "f-org", "f-region", "f-mode"):
        assert f'id="{f}"' in html
    assert "expires within 30 days" in html and "a1c4f" in html


def test_quality_review_hides_outcomes_below_the_minimum_learner_count(store):
    html = view(store, "quality-review.html")
    section = html[html.index("<h2>a1c4f</h2>"):]
    section = section[:section.index("</section>")]
    few = section[section.index("v-few"):section.index("</tr>", section.index("v-few"))]
    many = section[section.index("v-many"):section.index("</tr>", section.index("v-many"))]
    assert "insufficient data" in few and "40.0" not in few
    assert "55.0" in many and "-15.0" in many


def test_views_show_ids_only_and_load_nothing_from_outside(store):
    for path in (store / views.VIEWS).rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "@example.com" not in text and "Sim " not in text, path.name
        for external in ("http://", "https://", "src=", "<link"):
            assert external not in text, (path.name, external)


def test_the_instructor_record_holds_their_own_records(store):
    html = view(store, "instructors/a1c4f.html")
    for title in ("Clearances", "Observations", "Coaching cycles", "Dry runs", "CPD", "Level changes", "Bench reviews"):
        assert f"<h2>{title}</h2>" in html
    assert "Instructor record: a1c4f" in html


def test_a_rebuild_writes_nothing_new_and_the_command_runs(store, capsys):
    rep = views.build(store)
    assert rep.summary.startswith("views: 0 written")
    assert cli.main(["views", "--private-dir", str(store)]) == 0
    assert "views:" in capsys.readouterr().out


def test_values_are_escaped():
    assert views._e("<script>") == "&lt;script&gt;"
