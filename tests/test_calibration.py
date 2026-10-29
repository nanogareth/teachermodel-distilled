"""W5 calibration: `open-exercise`, the scoring pages, the result step, the renewal due rule and the records adapter.

Fictional people only (the example roster). The reference scores are a private document: these tests grep the log and
the pages for them.
"""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from privacy_helpers import import_roster_ungated, make_privacy_root, tm_data

from teachermodel import app, cli, due, events, records, rules, signoff, workflow
from teachermodel.flows import PAGE_SPECS, calibration
from teachermodel.standards import ROOT, check_standards, domain_ids, load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
NOW = T0 + timedelta(days=1)
UNIT = "sl:unit/example-agent-loop@1"
A = "tm:instructor/p3x9d"  # observers: the example roster's professional and SME engineer
B = "tm:instructor/k7m2q"
C = "tm:instructor/c5w1t"
SCORE = "tm:step/calibration-score"
RESULT = "tm:step/calibration-result"
RECORDING = "recordings/fictional-delivery-1.mp4"
DOMAINS = domain_ids()
assert len(DOMAINS) == 5, "these tests are written for five framework domains (3 of 5 = the 0.6 exact edge)"


@pytest.fixture
def store(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    return fictional_store


def reference_file(tmp_path, values=None, name="reference.yaml", comment="# fictional answer sheet 7f3a91"):
    values = values or {d: 2 for d in DOMAINS}
    path = tmp_path / name
    path.write_text(comment + "\n" + yaml.safe_dump(values), encoding="utf-8")
    return path


def open_exercise(store, tmp_path, *, observers=(A, B), values=None, now=T0, **kw):
    return calibration.open_exercise(
        store, unit=kw.pop("unit", UNIT), recording_ref=kw.pop("recording_ref", RECORDING), observers=list(observers),
        reference=reference_file(tmp_path, values), now=now, **kw)


def exercise_events(store):
    return [e for e in app.read_events(store) if e["kind"] == "subject" and e["payload"]["subject_kind"] == "exercise"]


def calibration_events(store):
    return [e for e in app.read_events(store) if e["kind"] == "calibration"]


def result_steps(store):
    return [e for e in app.read_events(store) if e["kind"] == "step" and e["payload"].get("step") == RESULT]


def scores_with(exact, off_by_one, off_by_two=0, ref=2):
    """Scores for the five domains against a reference of all `ref`: so many exact, one off, two off."""
    deltas = [0] * exact + [1] * off_by_one + [2] * off_by_two
    assert len(deltas) == len(DOMAINS)
    return {d: ref + delta for d, delta in zip(DOMAINS, deltas)}


def sign(store, exercise, observer, scores, *, sid, at="2026-10-27T09:00:00+00:00", decision="approve", fields=None):
    """Store the sign-off document and append the sign-off event ingest would produce for `observer`'s page."""
    st = app.load_state(store)
    digest = app._current_input_reader(st)(SCORE, exercise)
    assert digest is not None, "the scoring page cannot be built"
    doc = {
        "schema": "tm:contract/signoff@1", "id": sid, "step": SCORE, "subject_uri": exercise, "input_sha256": digest,
        "decision": decision, "signer": observer, "signed_at": at, "page_template_sha256": "b" * 64,
        "fields": fields if fields is not None else {d: {"score": s, "note": "fictional evidence"} for d, s in scores.items()},
    }
    target = store / "signoffs" / f"{sid}.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(doc), encoding="utf-8")
    events.append(store / app.EVENT_LOG, {**signoff.to_event(doc, "x@example.com"), "at": at})
    return doc


def sign_b(store, exercise, sid="c" * 16):
    """B's complete submission, so that the result step waits only on A's."""
    return sign(store, exercise, B, scores_with(5, 0), sid=sid)


def of_a(store):
    return [e for e in calibration_events(store) if e["subject_uri"] == A]


def due_set(store, today=NOW.date(), root=ROOT):
    return {(d.step, d.subject) for d in app.due_steps(app.load_state(store, root), today)}


# --- open-exercise ------------------------------------------------------------------------------------


def test_open_exercise_appends_the_exercise_subject_event(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    (event,) = exercise_events(store)
    assert opened.created and opened.exercise == event["subject_uri"]
    assert event["subject_uri"].startswith("tm:exercise/") and len(event["subject_uri"]) == len("tm:exercise/") + 16
    assert event["actor"] == workflow.SYSTEM_ACTOR
    assert event["payload"] == {
        "subject_kind": "exercise",
        "attrs": {"unit": UNIT, "rubric_version": "1.1.0", "recording_ref": RECORDING, "observers": [B, A],
                  "reference_key": f"calibration/{event['subject_uri'].split('/')[1]}.reference.json"},
        "opened_by": "tm:cli/open-exercise",
    }
    assert events.check_event(event) == []
    assert event["at"] == T0.isoformat(timespec="seconds")


def test_the_exercise_is_a_subject_of_the_engine(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    info = app.load_state(store).subjects[opened.exercise]
    assert info["kind"] == "exercise" and info["observers"] == [B, A] and info["unit"] == UNIT


def test_the_reference_is_stored_privately_under_its_key(store, tmp_path):
    opened = open_exercise(store, tmp_path, values={d: i % 4 + 1 for i, d in enumerate(DOMAINS)})
    key = exercise_events(store)[0]["payload"]["attrs"]["reference_key"]
    stored = json.loads((store / key).read_text(encoding="utf-8"))
    assert stored["scores"] == {d: i % 4 + 1 for i, d in enumerate(DOMAINS)} and stored["exercise"] == opened.exercise
    assert not (store / "events" / "reference").exists()


def test_the_same_exercise_opened_twice_is_one_exercise(store, tmp_path):
    first = open_exercise(store, tmp_path)
    again = open_exercise(store, tmp_path)
    assert not again.created and again.exercise == first.exercise
    assert len(exercise_events(store)) == 1


def test_a_changed_reference_for_an_open_exercise_is_refused(store, tmp_path):
    open_exercise(store, tmp_path)
    with pytest.raises(calibration.ExerciseError, match="different reference"):
        open_exercise(store, tmp_path, values={d: 3 for d in DOMAINS})
    assert len(exercise_events(store)) == 1


def test_observer_order_does_not_change_the_exercise(store, tmp_path):
    assert open_exercise(store, tmp_path, observers=(A, B)).exercise == open_exercise(store, tmp_path, observers=(B, A)).exercise


def test_a_later_day_opens_a_new_exercise_for_the_same_recording(store, tmp_path):
    first = open_exercise(store, tmp_path)
    second = open_exercise(store, tmp_path, now=T0 + timedelta(days=200))
    assert second.created and second.exercise != first.exercise


def test_bare_slugs_name_instructors(store, tmp_path):
    opened = open_exercise(store, tmp_path, observers=("p3x9d", "k7m2q"))
    assert app.load_state(store).subjects[opened.exercise]["observers"] == [B, A]


@pytest.mark.parametrize("values, message", [
    ({d: 2 for d in DOMAINS[1:]}, f"missing domain.*{DOMAINS[0]}"),
    ({**{d: 2 for d in DOMAINS}, "charisma": 3}, "unknown domain.*charisma"),
    ({**{d: 2 for d in DOMAINS}, DOMAINS[0]: 5}, f"{DOMAINS[0]}.*1-4"),
    ({**{d: 2 for d in DOMAINS}, DOMAINS[0]: 0}, f"{DOMAINS[0]}.*1-4"),
    ({**{d: 2 for d in DOMAINS}, DOMAINS[0]: 2.5}, f"{DOMAINS[0]}.*1-4"),
    ({**{d: 2 for d in DOMAINS}, DOMAINS[0]: True}, f"{DOMAINS[0]}.*1-4"),
    ({**{d: 2 for d in DOMAINS}, DOMAINS[0]: "3"}, f"{DOMAINS[0]}.*1-4"),
])
def test_a_reference_must_score_every_domain_one_to_four(store, tmp_path, values, message):
    with pytest.raises(calibration.ExerciseError, match=message):
        open_exercise(store, tmp_path, values=values)
    assert exercise_events(store) == [] and not (store / "calibration").exists()


def test_a_reference_that_is_not_a_mapping_is_refused(store, tmp_path):
    path = tmp_path / "ref.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(calibration.ExerciseError, match="mapping"):
        calibration.open_exercise(store, unit=UNIT, recording_ref=RECORDING, observers=[A, B], reference=path, now=T0)


def test_a_missing_reference_file_is_refused(store, tmp_path):
    with pytest.raises(calibration.ExerciseError, match="no such file"):
        calibration.open_exercise(store, unit=UNIT, recording_ref=RECORDING, observers=[A, B],
                                  reference=tmp_path / "nope.yaml", now=T0)


def test_a_json_reference_is_read(store, tmp_path):
    path = tmp_path / "ref.json"
    path.write_text(json.dumps({d: 2 for d in DOMAINS}), encoding="utf-8")
    assert calibration.open_exercise(store, unit=UNIT, recording_ref=RECORDING, observers=[A, B], reference=path,
                                     now=T0).created


@pytest.mark.parametrize("observers, message", [
    ((), "at least two observers"),
    ((A,), "at least two observers"),  # spec W5 step 1: two or more observers score the same recording
    ((A, A), "twice"),
    ((A, "tm:instructor/nobody"), "not a registered instructor"),
    ((A, "tm:person/hot-1"), "not an instructor"),
    ((A, "Not A Slug"), "not an instructor"),
])
def test_observers_must_be_distinct_registered_instructors(store, tmp_path, observers, message):
    with pytest.raises(calibration.ExerciseError, match=message):
        open_exercise(store, tmp_path, observers=observers)
    assert exercise_events(store) == [] and not (store / "calibration").exists()


@pytest.mark.parametrize("ref", ["https://example.com/recording.mp4", "C:/Users/x/rec.mp4", "../rec.mp4", "", "a b"])
def test_the_recording_is_a_key_into_the_private_store_not_a_link(store, tmp_path, ref):
    with pytest.raises(calibration.ExerciseError, match="recording"):
        open_exercise(store, tmp_path, recording_ref=ref)


def test_an_unknown_unit_is_refused(store, tmp_path):
    with pytest.raises(calibration.ExerciseError, match="unit"):
        open_exercise(store, tmp_path, unit="sl:unit/nope@1")


# --- the command ----------------------------------------------------------------------------------------


def run_cli(store, tmp_path, capsys, *, values=None, observers="p3x9d,k7m2q", recording=RECORDING):
    ref = reference_file(tmp_path, values)
    code = cli.main(["open-exercise", "--private-dir", str(store), "--unit", UNIT, "--recording-ref", recording,
                     "--observers", observers, "--reference", str(ref)])
    return code, capsys.readouterr()


def test_the_command_opens_an_exercise(store, tmp_path, capsys):
    code, out = run_cli(store, tmp_path, capsys)
    assert code == 0
    (event,) = exercise_events(store)
    assert event["subject_uri"] in out.out and "opened" in out.out


def test_the_command_refuses_a_reference_missing_a_domain(store, tmp_path, capsys):
    code, out = run_cli(store, tmp_path, capsys, values={d: 2 for d in DOMAINS[:-1]})
    assert code == 1 and "missing domain" in out.err and DOMAINS[-1] in out.err
    assert exercise_events(store) == [] and not (store / "calibration").exists()


def test_the_command_refuses_an_unknown_observer(store, tmp_path, capsys):
    code, out = run_cli(store, tmp_path, capsys, observers="p3x9d,nobody")
    assert code == 1 and "not a registered instructor" in out.err


def test_the_command_is_listed_in_the_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["open-exercise", "--help"])
    assert "--reference" in capsys.readouterr().out


# --- the scoring pages --------------------------------------------------------------------------------


def test_the_workflow_defines_the_calibration_and_recalibration_steps():
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/calibration"]
    steps = {s["id"]: s for s in wf["steps"]}
    assert set(steps) == {SCORE, RESULT, "tm:step/open-recalibrations", "tm:step/recalibration-exercise"}
    assert steps[SCORE]["type"] == "human" and steps[SCORE]["subject"] == "exercise" and steps[SCORE]["page"] == "approve"
    assert steps[RESULT]["type"] == "auto" and steps[RESULT]["subject"] == "exercise"
    assert steps[SCORE]["due"] == "clearer_renewal"
    assert check_standards() == []


def test_both_steps_are_due_for_an_open_exercise(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    assert {(SCORE, opened.exercise), (RESULT, opened.exercise)} <= due_set(store)


def test_a_page_is_written_for_each_listed_observer_and_no_one_else(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    app.do_pages(store, now=NOW)
    slug = opened.exercise.split("/")[1]
    names = sorted(p.name for p in (store / "pages").glob("calibration-score--*.html"))
    assert names == [f"calibration-score--{slug}--k7m2q.html", f"calibration-score--{slug}--p3x9d.html"]
    for name, observer in zip(names, (B, A)):
        data = tm_data(store / "pages" / name)
        assert data["signer"] == observer and data["subject_uri"] == opened.exercise and data["step"] == SCORE
        assert data["template"] == "approve" and data["role"] == "instructor"


def test_a_page_scores_each_framework_domain_with_evidence(store, tmp_path):
    open_exercise(store, tmp_path)
    app.do_pages(store, now=NOW)
    page = next((store / "pages").glob("calibration-score--*--p3x9d.html"))
    fields = tm_data(page)["fields"]
    assert [f["name"] for f in fields] == DOMAINS
    assert all(f["kind"] == "evidence_score" and f["required"] and len(f["anchors"]) == 4 for f in fields)


def test_every_observer_sees_the_same_inputs(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    st = app.load_state(store)
    specs = PAGE_SPECS[SCORE](st, opened.exercise)
    assert [s["signer"] for s in specs] == [B, A]
    assert specs[0]["inputs"] == specs[1]["inputs"]
    assert specs[0]["inputs"]["unit"] == UNIT and specs[0]["inputs"]["recording_ref"] == RECORDING
    assert app._current_input_reader(st)(SCORE, opened.exercise) == signoff.input_sha256(specs[0]["inputs"])


def test_the_reference_never_reaches_a_page_or_the_log(store, tmp_path):
    values = {d: i % 4 + 1 for i, d in enumerate(DOMAINS)}
    opened = open_exercise(store, tmp_path, values=values)
    # The pages are written while the exercise is open: once both observers have signed the step is done and none is
    # written, so a scan made after signing would find nothing to look at (integration review finding 9).
    app.do_pages(store, now=NOW)
    scored = sorted((store / "pages").glob("calibration-score--*"))
    assert scored, "no calibration-score page was written, so there is nothing to scan"
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign(store, opened.exercise, B, scores_with(3, 2), sid="b" * 16)
    app.do_tick(store, now=NOW)
    key = exercise_events(store)[0]["payload"]["attrs"]["reference_key"]
    secrets = [(store / key).read_text(encoding="utf-8"), "fictional answer sheet 7f3a91",
               json.dumps(values), json.dumps(values, separators=(",", ":")), json.dumps(values, sort_keys=True),
               yaml.safe_dump(values)]
    pages = sorted((store / "pages").glob("*"))
    assert set(scored) <= set(pages)
    haystacks = [p.read_text(encoding="utf-8") for p in pages]
    haystacks.append((store / app.EVENT_LOG).read_text(encoding="utf-8"))
    for text in haystacks:
        for secret in secrets:
            assert secret not in text
    for text in haystacks[:-1]:
        assert key not in text


# --- the result step ----------------------------------------------------------------------------------


def run(store, now=NOW):
    return app.do_run(store, now=now)


def test_nothing_is_computed_until_every_listed_observer_has_submitted(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    run(store)
    assert calibration_events(store) == [] and result_steps(store) == []
    assert (SCORE, opened.exercise) in due_set(store)  # B can still sign


def test_every_observer_gets_a_calibration_event_once_all_have_submitted(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign(store, opened.exercise, B, scores_with(2, 3), sid="b" * 16)
    run(store)
    by_observer = {e["subject_uri"]: e for e in calibration_events(store)}
    assert set(by_observer) == {A, B}
    ev = by_observer[A]
    assert ev["actor"] == workflow.SYSTEM_ACTOR and ev["at"] == NOW.isoformat(timespec="seconds")
    # inter_observer: A against B, the observers against each other (W5 step 2); reported, not part of pass or fail
    assert ev["payload"] == {"exercise": opened.exercise, "observer": A, "unit": UNIT, "rubric_version": "1.1.0",
                             "within_one_share": 1.0, "exact_share": 1.0, "passed": True, "signoff_id": "a" * 16,
                             "inter_observer": {"within_one_share": 1.0, "exact_share": 0.4}}
    assert by_observer[B]["payload"]["passed"] is False and by_observer[B]["payload"]["signoff_id"] == "b" * 16
    assert all(events.check_event(e) == [] for e in by_observer.values())
    (done,) = result_steps(store)
    assert done["subject_uri"] == opened.exercise and done["payload"]["observers"] == [B, A]
    assert done["payload"]["renewal_months"] == 6  # the rules the result was computed under (the clearer_renewal rule)


def test_the_exercise_is_finished_once_the_result_is_written(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign(store, opened.exercise, B, scores_with(5, 0), sid="b" * 16)
    run(store)
    assert {(SCORE, opened.exercise), (RESULT, opened.exercise)}.isdisjoint(due_set(store))


def test_a_second_run_appends_nothing(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign(store, opened.exercise, B, scores_with(5, 0), sid="b" * 16)
    run(store)
    before = app.read_events(store)
    run(store, NOW + timedelta(days=1))
    # Nothing of W5: the levels workflow may now propose a cleared instructor who passed for clearer (it reads the
    # calibration a run after it was written), which is not this step appending again.
    new = [e for e in app.read_events(store)[len(before):]
           if not (e["kind"] == "step" and e["payload"].get("step") in ("tm:step/propose-levels", "tm:step/levels-decided"))]
    assert new == []


@pytest.mark.parametrize("exact, off1, off2, passed", [
    (5, 0, 0, True),
    (3, 2, 0, True),   # exact agreement 3/5 = 0.6: the edge, passes
    (2, 3, 0, False),  # exact agreement 2/5 = 0.4
    (3, 1, 1, False),  # within-one 4/5 = 0.8 < 0.9
    (4, 0, 1, False),
    (0, 5, 0, False),  # within one everywhere but never exact
])
def test_pass_and_fail_at_the_thresholds(store, tmp_path, exact, off1, off2, passed):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(exact, off1, off2), sid="a" * 16)
    sign_b(store, opened.exercise)
    run(store)
    (ev,) = of_a(store)
    assert ev["payload"]["passed"] is passed
    assert ev["payload"]["exact_share"] == pytest.approx(exact / 5)
    assert ev["payload"]["within_one_share"] == pytest.approx((exact + off1) / 5)


def test_scores_below_the_reference_count_too(store, tmp_path):
    opened = open_exercise(store, tmp_path, values={d: 3 for d in DOMAINS})
    sign(store, opened.exercise, A, {d: 2 for d in DOMAINS}, sid="a" * 16)  # one under, everywhere
    sign_b(store, opened.exercise)
    run(store)
    (ev,) = of_a(store)
    assert ev["payload"]["within_one_share"] == 1.0 and ev["payload"]["exact_share"] == 0.0 and not ev["payload"]["passed"]


def test_the_thresholds_come_from_the_rules_file(fictional_store, example_roster, tmp_path):
    root = make_privacy_root(tmp_path / "r")
    path = root / "standards" / "rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["calibration"]["within_one_point_share"] = 0.8
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    store = fictional_store
    import_roster_ungated(store, example_roster, T0)
    opened = open_exercise(store, tmp_path, observers=(A, B), root=root)

    def submit(observer, scores, sid):
        st = app.load_state(store, root)
        digest = app._current_input_reader(st)(SCORE, opened.exercise)
        doc = {"schema": "tm:contract/signoff@1", "id": sid, "step": SCORE, "subject_uri": opened.exercise,
               "input_sha256": digest, "decision": "approve", "signer": observer, "signed_at": NOW.isoformat(),
               "page_template_sha256": "b" * 64,
               "fields": {d: {"score": s, "note": "n"} for d, s in scores.items()}}
        (store / "signoffs").mkdir(exist_ok=True)
        (store / "signoffs" / f"{sid}.json").write_text(json.dumps(doc), encoding="utf-8")
        events.append(store / app.EVENT_LOG, {**signoff.to_event(doc, "x@example.com"), "at": NOW.isoformat()})

    submit(A, scores_with(3, 1, 1), "a" * 16)  # within one 4/5 = 0.8: the edge of the lowered threshold, passes
    submit(B, scores_with(2, 1, 2), "b" * 16)  # within one 3/5 = 0.6: fails
    app.do_run(store, now=NOW, root=root)
    got = {e["subject_uri"]: e["payload"]["passed"] for e in calibration_events(store)}
    assert got == {A: True, B: False}


def test_the_latest_submission_of_an_observer_counts(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(0, 0, 5), sid="a" * 16, at="2026-10-27T09:00:00+00:00")
    sign(store, opened.exercise, A, scores_with(5, 0), sid="b" * 16, at="2026-10-27T10:00:00+00:00")
    sign_b(store, opened.exercise)
    run(store)
    (ev,) = of_a(store)
    assert ev["payload"]["passed"] is True and ev["payload"]["signoff_id"] == "b" * 16


def test_a_sign_off_that_does_not_approve_is_not_a_submission(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16, decision="changes")
    sign_b(store, opened.exercise)
    run(store)
    assert calibration_events(store) == []


def test_a_sign_off_by_someone_who_is_not_listed_is_ignored(store, tmp_path):
    opened = open_exercise(store, tmp_path, observers=(A, C))
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign(store, opened.exercise, B, scores_with(5, 0), sid="b" * 16)  # B is not listed: C has not submitted
    run(store)
    assert calibration_events(store) == [] and result_steps(store) == []


@pytest.mark.parametrize("fields", [
    {},
    {d: {"score": 3, "note": "n"} for d in DOMAINS[1:]},
    {**{d: {"score": 3, "note": "n"} for d in DOMAINS}, DOMAINS[0]: {"score": 9, "note": "n"}},
    {**{d: {"score": 3, "note": "n"} for d in DOMAINS}, DOMAINS[0]: {"score": True, "note": "n"}},
    {**{d: {"score": 3, "note": "n"} for d in DOMAINS}, DOMAINS[0]: 3},
])
def test_an_incomplete_or_malformed_submission_is_not_counted(store, tmp_path, fields):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, {}, sid="a" * 16, fields=fields)
    sign_b(store, opened.exercise)
    run(store)
    assert calibration_events(store) == [] and (SCORE, opened.exercise) in due_set(store)


def test_a_missing_sign_off_document_is_not_counted(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign_b(store, opened.exercise)
    (store / "signoffs" / ("a" * 16 + ".json")).unlink()
    run(store)
    assert calibration_events(store) == []


def test_a_missing_reference_blocks_the_result_once(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign_b(store, opened.exercise)
    key = exercise_events(store)[0]["payload"]["attrs"]["reference_key"]
    (store / key).unlink()
    run(store)
    assert calibration_events(store) == []
    (check,) = [e for e in app.read_events(store) if e["kind"] == "check" and e["payload"].get("step") == RESULT]
    assert check["payload"]["result"] == "blocked" and check["subject_uri"] == opened.exercise
    run(store, NOW + timedelta(days=1))
    assert len([e for e in app.read_events(store) if e["kind"] == "check" and e["payload"].get("step") == RESULT]) == 1


def test_a_reference_that_no_longer_covers_the_domains_blocks_the_result(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign_b(store, opened.exercise)
    key = exercise_events(store)[0]["payload"]["attrs"]["reference_key"]
    doc = json.loads((store / key).read_text(encoding="utf-8"))
    doc["scores"].pop(DOMAINS[0])
    (store / key).write_text(json.dumps(doc), encoding="utf-8")
    run(store)
    assert calibration_events(store) == []


def test_two_exercises_are_scored_apart(store, tmp_path):
    first = open_exercise(store, tmp_path)
    second = open_exercise(store, tmp_path, recording_ref="recordings/other.mp4")
    assert first.exercise != second.exercise
    sign(store, first.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign_b(store, first.exercise)
    run(store)
    assert {e["payload"]["exercise"] for e in calibration_events(store)} == {first.exercise}
    assert (SCORE, second.exercise) in due_set(store)


# --- records and the renewal due rule -------------------------------------------------------------------


def cal(observer, day, passed=True):
    payload = {"exercise": "tm:exercise/" + "0" * 16, "observer": observer, "unit": UNIT, "rubric_version": "0.2.0",
               "within_one_share": 1.0 if passed else 0.4, "exact_share": 1.0 if passed else 0.2, "passed": passed,
               "signoff_id": "a" * 16}
    return events.make_event("calibration", observer, workflow.SYSTEM_ACTOR, payload, at=f"{day}T09:00:00+00:00")


def test_records_lists_the_passed_calibrations_per_observer_oldest_first():
    log = [cal(A, "2026-09-01"), cal(A, "2026-03-01"), cal(B, "2026-05-01", passed=False), cal(B, "2026-06-15"),
           events.make_event("check", A, workflow.SYSTEM_ACTOR, {"step": None, "result": "ok"})]
    assert records.calibrations(log) == {A: [date(2026, 3, 1), date(2026, 9, 1)], B: [date(2026, 6, 15)]}


def test_records_of_nothing_is_empty():
    assert records.calibrations([]) == {}
    assert records.calibrations([cal(A, "2026-09-01", passed=False)]) == {}


def test_records_feed_is_calibrated_at_the_renewal_edge():
    rule_set = load_standards()["rules"]
    got = records.calibrations([cal(A, "2026-03-31")])
    assert rule_set["calibration"]["renewal_months"] == 6
    assert rules.is_calibrated(A, date(2026, 9, 29), got, rule_set)
    assert not rules.is_calibrated(A, date(2026, 9, 30), got, rule_set)  # six months after 31 March is 30 September
    assert not rules.is_calibrated(A, date(2026, 3, 30), got, rule_set)
    assert not rules.is_calibrated(B, date(2026, 5, 1), got, rule_set)


def test_records_round_trip_from_the_result_step(store, tmp_path):
    opened = open_exercise(store, tmp_path)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign(store, opened.exercise, B, scores_with(2, 3), sid="b" * 16)
    run(store)
    got = records.calibrations(app.read_events(store))
    assert got == {A: [NOW.date()]}
    rule_set = load_standards()["rules"]
    assert rules.is_calibrated(A, NOW.date() + timedelta(days=100), got, rule_set)
    assert not rules.is_calibrated(B, NOW.date(), got, rule_set)


def renewal(subject, info, log, today=NOW.date()):
    return due.resolve("clearer_renewal")({}, subject, info, log, today)


def test_clearer_renewal_is_registered_and_used():
    assert "clearer_renewal" in due.names()


def test_renewal_falls_due_six_months_after_the_latest_pass():
    log = [cal(A, "2026-01-31"), cal(A, "2026-03-31"), cal(A, "2026-08-01", passed=False)]
    assert renewal(A, {"kind": "instructor"}, log) == date(2026, 9, 30)


def test_no_passed_calibration_means_no_renewal_date():
    assert renewal(A, {"kind": "instructor"}, []) is None
    assert renewal(A, {"kind": "instructor"}, [cal(A, "2026-03-01", passed=False)]) is None


def test_an_exercise_falls_due_when_its_first_observer_would_lapse():
    log = [cal(A, "2026-03-31"), cal(B, "2026-05-15")]
    info = {"kind": "exercise", "observers": [A, B]}
    assert renewal("tm:exercise/" + "1" * 16, info, log) == date(2026, 9, 30)
    assert renewal("tm:exercise/" + "1" * 16, {"kind": "exercise", "observers": [B]}, log) == date(2026, 11, 15)
    assert renewal("tm:exercise/" + "1" * 16, {"kind": "exercise", "observers": ["tm:instructor/new"]}, log) is None


def test_the_open_exercise_carries_the_renewal_date_of_its_observers(store, tmp_path):
    events.append(store / app.EVENT_LOG, cal(A, "2026-04-30"))
    opened = open_exercise(store, tmp_path)
    (item,) = [d for d in app.due_steps(app.load_state(store), NOW.date()) if (d.step, d.subject) == (SCORE, opened.exercise)]
    assert item.due == date(2026, 10, 30) and not item.overdue
    (late,) = [d for d in app.due_steps(app.load_state(store), date(2026, 11, 1)) if d.step == SCORE]
    assert late.overdue


# --- integration-review fixes -------------------------------------------------------------------------------------


def test_inter_observer_agreement_is_reported_and_does_not_decide(store, tmp_path):
    opened = open_exercise(store, tmp_path, observers=(A, B, C))
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)  # 2 2 2 2 2
    sign(store, opened.exercise, B, scores_with(3, 0, 2), sid="b" * 16)  # 2 2 2 4 4: fails against the reference
    sign(store, opened.exercise, C, scores_with(5, 0), sid="c" * 16)
    run(store)
    got = {e["subject_uri"]: e["payload"] for e in calibration_events(store)}
    assert got[A]["inter_observer"] == {"within_one_share": 0.8, "exact_share": 0.8}  # (3+5)/10 with B and C
    assert got[B]["inter_observer"] == {"within_one_share": 0.6, "exact_share": 0.6}
    assert got[A]["passed"] and got[C]["passed"] and not got[B]["passed"]
    assert all(events.check_event(e) == [] for e in calibration_events(store))


def test_the_renewal_rule_reads_the_rules_of_the_root_the_result_was_computed_under(fictional_store, example_roster,
                                                                                    tmp_path):
    root = make_privacy_root(tmp_path / "r")
    path = root / "standards" / "rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["calibration"]["renewal_months"] = 3
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    store = fictional_store
    import_roster_ungated(store, example_roster, T0)
    opened = open_exercise(store, tmp_path, root=root)
    sign(store, opened.exercise, A, scores_with(5, 0), sid="a" * 16)
    sign(store, opened.exercise, B, scores_with(5, 0), sid="b" * 16)
    app.do_run(store, now=NOW, root=root)
    log = app.read_events(store)
    assert renewal(A, {"kind": "instructor"}, log) == rules.add_months(NOW.date(), 3)
    assert renewal(opened.exercise, {"kind": "exercise", "observers": [A, B]}, log) == rules.add_months(NOW.date(), 3)
