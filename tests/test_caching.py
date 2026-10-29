"""Memoisation that keeps a tick fast (integration review finding 3): the answers stay the same, the files are parsed once.

Every cache is keyed by the bytes of the files it was built from, so an edit is seen on the next call."""

import re
from datetime import date

import yaml
from privacy_helpers import edit_yaml, sign_step

from teachermodel import app, privacy, standards
from teachermodel.flows import PAGE_SPECS


def count_loads(monkeypatch):
    """Count the YAML documents parsed through standards.parse_yaml (the one place a document is parsed)."""
    calls = []
    real = standards.parse_yaml

    def counting(data):
        calls.append(len(data))
        return real(data)

    monkeypatch.setattr(standards, "parse_yaml", counting)
    monkeypatch.setattr(privacy, "parse_yaml", counting, raising=False)
    return calls


def test_a_profile_is_parsed_and_validated_once_per_content(privacy_root, monkeypatch):
    path, _ = privacy.base_profile(privacy_root)
    path.write_bytes(path.read_bytes() + b"# a content nobody has loaded\n")
    calls = count_loads(monkeypatch)
    for _ in range(5):
        privacy.load_profile(path, privacy_root)
    assert len(calls) == 1


def test_an_edited_profile_is_seen_on_the_next_call(privacy_root):
    path, doc = privacy.base_profile(privacy_root)
    edit_yaml(path, lambda d: d.__setitem__("name", "Renamed Fictionland"))
    assert privacy.load_profile(path, privacy_root)["name"] == "Renamed Fictionland"
    assert doc["name"] != "Renamed Fictionland"


def test_purposes_are_cached_by_content(privacy_root, monkeypatch):
    privacy.load_purposes(privacy_root)
    calls = count_loads(monkeypatch)
    for _ in range(4):
        privacy.load_purposes(privacy_root)
    assert calls == []
    edit_yaml(privacy_root / privacy.PURPOSES_FILE, lambda d: d["purposes"][0].__setitem__("name", "Edited name"))
    assert privacy.load_purposes(privacy_root)["purposes"][0]["name"] == "Edited name"


def test_a_broken_file_is_not_cached(privacy_root):
    path, _ = privacy.base_profile(privacy_root)
    good = path.read_bytes()
    privacy.load_profile(path, privacy_root)
    path.write_text("schema_version: 1\n", encoding="utf-8")
    try:
        privacy.load_profile(path, privacy_root)
    except privacy.PrivacyError as exc:
        assert path.name in str(exc)
    else:
        raise AssertionError("a broken profile loaded from the cache")
    path.write_bytes(good)
    assert privacy.load_profile(path, privacy_root)["role"] == "base"


def test_the_cache_is_bounded():
    for n in range(standards.MEMO_MAX * 2):
        standards.memo(("test-bound", n), lambda n=n: n)
    assert len(standards._MEMO) <= standards.MEMO_MAX


def test_the_fast_yaml_loader_keeps_the_plain_safe_loader_results(tmp_path):
    path = tmp_path / "doc.yaml"
    path.write_text("a: 2026-10-24\nb: [1, 2.5, true, null]\nc: 'x'\n", encoding="utf-8")
    assert standards.load_yaml(path) == yaml.safe_load(path.read_text(encoding="utf-8"))


def test_the_roster_loader_still_keeps_dates_as_strings(tmp_path):
    from teachermodel import roster

    path = tmp_path / "r.yaml"
    path.write_text("as_of: 2026-10-24\n", encoding="utf-8")
    assert roster.load(path) == {"as_of": "2026-10-24"}


# --- one run reads the store once and appends without re-reading it (integration review finding 8) ---------


def _boom(*a, **k):
    raise AssertionError("the event log was read again")


def _fresh_event(n, at="2026-10-26T08:00:00+00:00"):
    from teachermodel import events

    return events.make_event("check", "tm:programme/teachermodel", "tm:system/teachermodel",
                             {"step": None, "result": "test", "n": n}, id=f"{n:032x}", at=at)


def test_append_new_with_a_known_id_set_does_not_read_the_log(fictional_store, monkeypatch):
    app.append_new(fictional_store, [_fresh_event(1)])
    monkeypatch.setattr(app, "read_events", _boom)
    seen = {_fresh_event(1)["id"]}
    added = app.append_new(fictional_store, [_fresh_event(1), _fresh_event(2), _fresh_event(2)], seen=seen)
    assert [e["id"] for e in added] == [_fresh_event(2)["id"]]  # the known id and the repeat are dropped
    assert seen == {_fresh_event(1)["id"], _fresh_event(2)["id"]}  # and the set the caller keeps is brought up to date
    monkeypatch.undo()
    assert [e["id"] for e in app.read_events(fictional_store)] == [_fresh_event(1)["id"], _fresh_event(2)["id"]]


def test_append_new_without_a_set_still_reads_the_ids_once(fictional_store):
    app.append_new(fictional_store, [_fresh_event(1)])
    assert app.append_new(fictional_store, [_fresh_event(1), _fresh_event(3)]) == [_fresh_event(3)]


def test_a_run_loads_the_state_once(fictional_store, example_roster, monkeypatch):
    from clearer_helpers import calibrate, set_level
    from privacy_helpers import import_roster_ungated

    from datetime import datetime, timezone

    now = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
    import_roster_ungated(fictional_store, example_roster, now)
    for s in ("k7m2q", "c5w1t", "r8n4h"):
        set_level(fictional_store, f"tm:instructor/{s}", "clearer")
    calibrate(fictional_store, "k7m2q", "c5w1t", "r8n4h")
    loads, reads = [], []
    real_load, real_read = app.load_state, app.read_events
    monkeypatch.setattr(app, "load_state", lambda *a, **k: (loads.append(1), real_load(*a, **k))[1])
    monkeypatch.setattr(app, "read_events", lambda *a, **k: (reads.append(1), real_read(*a, **k))[1])
    rep = app.do_run(fictional_store, now=now)
    # word-bounded: "30 event(s) appended" contains the substring "0 event(s) appended"
    assert not re.search(r"(?<!\d)0 auto step\(s\) executed", rep.summary), rep.summary
    assert not re.search(r"(?<!\d)0 event\(s\) appended", rep.summary), rep.summary
    assert rep.lines  # it did chains of work (candidates, then proposals), each round on the state it advanced itself
    assert len(loads) == 1 and len(reads) == 1  # the log was read once, however many rounds and refreshes it took


def test_an_advanced_state_is_the_state_a_fresh_load_would_give(fictional_store, example_roster):
    from clearer_helpers import set_level
    from privacy_helpers import import_roster_ungated

    from datetime import datetime, timezone

    now = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
    import_roster_ungated(fictional_store, example_roster, now)
    set_level(fictional_store, "tm:instructor/k7m2q", "clearer")
    before = app.load_state(fictional_store)
    app.do_run(fictional_store, now=now)  # opens candidates and proposes
    after = app.load_state(fictional_store)
    added = after.events[len(before.events):]
    assert len(added) > 3 and any(e["kind"] == "subject" for e in added)
    advanced = app.advance_state(before, added)
    assert advanced.events == after.events and advanced.subjects == after.subjects
    assert advanced.registrations == after.registrations and advanced.identities == after.identities
    assert advanced.cache.get("page_specs") is None  # answers derived from the old events are not carried over
    assert advanced.index.ids == {e["id"] for e in after.events} and before.index.ids != advanced.index.ids


def test_the_state_index_answers_by_kind_and_subject(fictional_store, example_roster):
    from datetime import datetime, timezone

    from privacy_helpers import import_roster_ungated

    now = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
    import_roster_ungated(fictional_store, example_roster, now)
    st = app.load_state(fictional_store)
    regs = [e for e in st.events if e["kind"] == "registration"]
    assert regs and st.index.of("registration", regs[0]["subject_uri"]) == [regs[0]]
    assert regs[0] in st.index.for_subject(regs[0]["subject_uri"])
    assert st.index is st.index and st.index.events is st.events  # built once per state, over the state's own list


# --- the page builders run once per (step, subject) for one loaded state ---------------------------------


def test_a_current_input_is_derived_once_per_step_and_subject(fictional_store, privacy_root, monkeypatch):
    app.do_tick(fictional_store, root=privacy_root)
    st = app.load_state(fictional_store, privacy_root)
    step = "tm:step/base-profile-verified"
    calls = []
    real = PAGE_SPECS[step]

    def counting(state, subject):
        calls.append(subject)
        return real(state, subject)

    monkeypatch.setitem(PAGE_SPECS, step, counting)
    reader = app._current_input_reader(st)
    first = reader(step, "tm:programme/teachermodel")
    assert first is not None
    assert reader(step, "tm:programme/teachermodel") == first
    assert app._current_rows_reader(st)(step, "tm:programme/teachermodel") == set()  # shares the builder's result
    assert len(calls) == 1


def test_a_new_state_sees_new_files(fictional_store, privacy_root):
    app.do_tick(fictional_store, root=privacy_root)
    step = "tm:step/base-profile-verified"
    before = app._current_input_reader(app.load_state(fictional_store, privacy_root))(step, "tm:programme/teachermodel")
    path, _ = privacy.base_profile(privacy_root)
    path.write_bytes(path.read_bytes() + b"# edit\n")
    after = app._current_input_reader(app.load_state(fictional_store, privacy_root))(step, "tm:programme/teachermodel")
    assert before != after


def test_a_state_builds_each_page_spec_once_for_next_and_pages(fictional_store, privacy_root, monkeypatch):
    app.do_tick(fictional_store, root=privacy_root)
    sign_step(fictional_store, privacy_root, "tm:step/base-profile-verified")
    st = app.load_state(fictional_store, privacy_root)
    calls = []
    real = dict(PAGE_SPECS)
    for step, fn in real.items():
        monkeypatch.setitem(PAGE_SPECS, step, lambda s, u, _fn=fn, _step=step: (calls.append((_step, u)), _fn(s, u))[1])
    today = date(2026, 10, 26)
    app.due_steps(st, today)
    app.due_steps(st, today)
    assert len(calls) == len(set(calls))

