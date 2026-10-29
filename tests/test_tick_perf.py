"""Integration review finding 14: a tick reads the store once and writes only what changed.

do_tick shares one State across run, plan, pages and next; common.generated() reads each output once per State; do_pages
leaves a page file alone when its bytes would not change; the quality summaries are computed from per-State groupings and
written only when their content changes. Fictional people only.
"""

import json
import os
from datetime import timedelta

import pytest
from test_observation import T0, store

from teachermodel import app, records
from teachermodel.flows import common, quality


def test_do_tick_loads_the_store_once(fictional_store, example_roster, monkeypatch):
    store(fictional_store, example_roster)
    calls = []
    real = app.load_state
    monkeypatch.setattr(app, "load_state", lambda *a, **k: calls.append(1) or real(*a, **k))
    reports = app.do_tick(fictional_store, now=T0 + timedelta(hours=1))
    assert len(calls) == 1
    assert [r.summary.split(":")[0] for r in reports] == ["run", "plan", "pages", "next"]


def test_the_state_a_run_hands_on_is_the_state_a_fresh_load_gives(fictional_store, example_roster):
    store(fictional_store, example_roster, run=False)
    st, now = app.load_state(fictional_store), T0 + timedelta(hours=1)
    report, after = app._run(st, now)
    fresh = app.load_state(fictional_store)
    assert report.ok and len(after.events) > len(st.events)
    assert after.events == fresh.events
    assert after.subjects == fresh.subjects and after.registrations == fresh.registrations
    assert [(d.step, d.subject, d.due) for d in app.due_steps(after, now.date())] == \
           [(d.step, d.subject, d.due) for d in app.due_steps(fresh, now.date())]


def test_a_tick_reports_what_separate_commands_report(fictional_store, example_roster, tmp_path_factory):
    import shutil

    store(fictional_store, example_roster, run=False)
    other = tmp_path_factory.mktemp("sep") / "private"
    shutil.copytree(fictional_store, other)
    now = T0 + timedelta(hours=1)
    together = app.do_tick(fictional_store, now=now)
    apart = [app.do_run(other, now=now), app.do_plan(other, now=now), app.do_pages(other, now=now), app.do_next(other, now=now)]
    assert [r.all_lines() for r in together] == [r.all_lines() for r in apart]
    def shape(private):  # some events carry generated ids: compare what they say
        return sorted((e["kind"], e["subject_uri"], json.dumps(e["payload"], sort_keys=True)) for e in app.read_events(private))

    assert shape(fictional_store) == shape(other)


def test_generated_reads_each_output_once_per_state(fictional_store, example_roster):
    store(fictional_store, example_roster)
    st = app.load_state(fictional_store)
    step = next(e["payload"]["step"] for e in st.index.of("step", app.PROGRAMME)
                if isinstance(e["payload"].get("output"), str) and (st.private / e["payload"]["output"]).is_file())
    first = common.generated(st, step)
    path = st.private / first[1]["output"]
    original = path.read_bytes()
    path.unlink()  # a second read of the file would fail
    try:
        assert common.generated(st, step) == first
    finally:
        path.write_bytes(original)
    assert common.generated(app.load_state(fictional_store), step) == first  # a new state reads it again


def page_mtimes(private):
    return {p.name: p.stat().st_mtime_ns for p in (private / "pages").glob("*")}


def test_pages_that_would_not_change_are_not_rewritten(fictional_store, example_roster):
    store(fictional_store, example_roster)
    now = T0 + timedelta(hours=1)
    app.do_pages(fictional_store, now=now)
    before = page_mtimes(fictional_store)
    assert before
    os.utime(next(iter((fictional_store / "pages").glob("*.html"))), ns=(10**9, 10**9))  # make a rewrite detectable by mtime
    marked = page_mtimes(fictional_store)
    rep = app.do_pages(fictional_store, now=now)
    assert page_mtimes(fictional_store) == marked
    assert rep.summary.startswith("pages: 0 written")


def test_a_changed_page_is_rewritten(fictional_store, example_roster):
    store(fictional_store, example_roster)
    now = T0 + timedelta(hours=1)
    app.do_pages(fictional_store, now=now)
    page = next(iter((fictional_store / "pages").glob("*.html")))
    page.write_bytes(b"stale")
    rep = app.do_pages(fictional_store, now=now)
    assert page.read_bytes() != b"stale" and not rep.summary.startswith("pages: 0 written")
    sidecar = page.with_name(page.name.replace(".html", ".input.json"))
    sidecar.write_bytes(b"{}")
    app.do_pages(fictional_store, now=now)
    assert sidecar.read_bytes() != b"{}"


def test_the_quality_summaries_are_computed_from_one_grouping_per_state(fictional_store, example_roster, monkeypatch):
    store(fictional_store, example_roster)
    st = app.load_state(fictional_store)
    calls = []
    real = records.outcomes
    monkeypatch.setattr(records, "outcomes", lambda *a, **k: calls.append(1) or real(*a, **k))
    instructors = sorted(u for u, i in st.subjects.items() if i["kind"] == "instructor")
    assert len(instructors) >= 3
    for instructor in instructors:
        quality.quality_review(st, instructor, T0 + timedelta(hours=1))
    assert len(calls) <= 1


def test_a_summary_is_not_rewritten_when_its_content_is_unchanged(fictional_store, example_roster):
    store(fictional_store, example_roster)
    st = app.load_state(fictional_store)
    instructor = sorted(u for u, i in st.subjects.items() if i["kind"] == "instructor")[0]
    quality.quality_review(st, instructor, T0 + timedelta(hours=1))
    target = st.private / quality.SUMMARY_DIR / f"{instructor.split('/', 1)[1]}.json"
    os.utime(target, ns=(10**9, 10**9))
    quality.quality_review(app.load_state(fictional_store), instructor, T0 + timedelta(hours=2))
    assert target.stat().st_mtime_ns == 10**9
