"""`teachermodel course` (course.py) and the W1 train-the-trainer sign-off page that lists the course record
(docs/train-the-trainer/DESIGN.md). One-week simulated store, generated data only."""

import hashlib
from datetime import date, datetime, timezone

import pytest
import yaml

from teachermodel import app, cli, course, simulate
from teachermodel.flows import onboarding

SESSIONS = ["micro-teach", "prior-knowledge", "lab-facilitation", "remote-delivery", "rubric-scoring"]


def test_the_course_has_its_five_sessions_on_known_domains():
    assert [s["id"] for s in course.sessions()] == SESSIONS


def test_a_malformed_course_file_is_refused(tmp_path):
    (tmp_path / "standards").mkdir()
    (tmp_path / "standards" / "framework.yaml").write_text("domains: [{id: lab-facilitation}]\n", encoding="utf-8")
    (tmp_path / "standards" / "train-the-trainer.yaml").write_text(yaml.safe_dump({"sessions": [
        {"id": "a", "title": "A", "domains": ["lab-facilitation"], "evidence": "x"},
        {"id": "a", "title": "B", "domains": ["juggling"], "evidence": "y"}]}), encoding="utf-8")
    with pytest.raises(course.CourseError, match="unknown domain juggling") as err:
        course.sessions(tmp_path)
    assert "unique" in str(err.value)


QUESTIONS = {"unit": "sl:unit/example-agent-loop@1", "pre_check": [{
    "topic": "tool-use loop", "question": "Which stop condition prevents an agent from calling tools forever?",
    "options": [{"text": "A maximum number of turns checked by the loop", "correct": True},
                {"text": "The model notices it is repeating itself and stops", "misconception": "model-retries-itself"},
                {"text": "The API rejects the tenth call in a row",
                 "proposed_misconception": "The API enforces a cap on consecutive tool calls"}],
    "routes": {"correct": "skip worked example", "incorrect": "worked example first"}}]}


def test_a_session_2_question_set_is_checked_against_its_unit(tmp_path):
    assert course.question_set_errors(QUESTIONS) == []
    item = QUESTIONS["pre_check"][0]
    bad = {"unit": "sl:unit/example-agent-loop@1", "pre_check": [
        {**item, "options": item["options"][:2]},
        {**item, "options": [{**o, "correct": True} for o in item["options"]]},
        {**item, "options": [item["options"][0], {"text": "x", "misconception": "no-such-id"},
                             {"text": "y", "proposed_misconception": "z"}]},
        {**item, "options": item["options"] + [{"text": "w"}]},
        {"topic": "", "question": "q", "options": item["options"], "routes": {"correct": "a"}}]}
    errors = course.question_set_errors(bad)
    assert errors == [
        "pre_check[0]: needs 3 to 5 options, has 2",
        "pre_check[1]: needs exactly one correct option, has 3",
        "pre_check[2].options[1]: misconception no-such-id is not in sl:unit/example-agent-loop@1",
        "pre_check[2]: at least one wrong option must use a misconception id from the unit",
        "pre_check[3].options[3]: a wrong option needs misconception (an id from the unit) or proposed_misconception",
        "pre_check[4]: needs topic, question and options",
        "pre_check[4]: routes need correct and incorrect"]
    assert course.question_set_errors({"unit": "sl:unit/nothing@1", "pre_check": [item]})[0].startswith("unit: no unit file")
    assert course.question_set_errors({"unit": "sl:unit/example-agent-loop@1"}) == ["pre_check: needs at least one question"]
    path = tmp_path / "questions.yaml"
    path.write_text(yaml.safe_dump(QUESTIONS), encoding="utf-8")
    assert cli.main(["check-questions", str(path)]) == 0
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    assert cli.main(["check-questions", str(path)]) == 1


CATALOGUE = {"failure_catalogue": [
    {"id": "room-unreachable", "inject": "Stop the collector", "expected_handling": "Show of hands; restart"},
    {"id": "stale-room-code", "inject": "Join with an old code", "expected_handling": "Join again"}]}
LOG = {"lab": "aggregates-only-export", "failure": "room-unreachable", "against_expected": "partly",
       "cohort_kept_moving": True, "what_was_done": "Took a show of hands per step; restarted with a new code."}


def test_a_session_3_failure_log_is_checked_against_the_lab_catalogue(tmp_path):
    assert course.failure_log_errors(LOG, CATALOGUE) == []
    bad = {"lab": "Aggregates Only", "failure": "wifi-down", "against_expected": "mostly",
           "cohort_kept_moving": "yes", "what_was_done": "x" * 601}
    assert course.failure_log_errors(bad, CATALOGUE) == [
        "lab: a scenario slug (lower-case letters, digits and -)",
        "failure: wifi-down is not in the catalogue (room-unreachable, stale-room-code)",
        "against_expected: met, partly or missed (the catalogue's expected_handling)",
        "cohort_kept_moving: true or false",
        "what_was_done: at most 600 characters"]
    assert course.failure_log_errors({**LOG, "what_was_done": " "}, CATALOGUE) == ["what_was_done: say what was done"]
    assert course.failure_log_errors(LOG, {}) == ["catalogue: has no failure_catalogue"]
    log, cat = tmp_path / "log.yaml", tmp_path / "catalogue.yaml"
    log.write_text(yaml.safe_dump(LOG), encoding="utf-8")
    cat.write_text(yaml.safe_dump(CATALOGUE), encoding="utf-8")
    assert cli.main(["check-failure-log", str(log), "--catalogue", str(cat)]) == 0
    log.write_text(yaml.safe_dump(bad), encoding="utf-8")
    assert cli.main(["check-failure-log", str(log), "--catalogue", str(cat)]) == 1


D5 = ["technical-depth", "prior-knowledge", "conceptual-questioning", "lab-facilitation", "remote-inclusive"]
REFERENCE = {"recordings": [{"recording": "ref-a", "scores": dict(zip(D5, [3, 2, 1, 3, 2]))},
                            {"recording": "ref-b", "scores": dict(zip(D5, [4, 3, 3, 2, 1]))}]}
MINE = {"recordings": [{"recording": "ref-a", "scores": dict(zip(D5, [3, 2, 3, 3, 2]))},
                       {"recording": "ref-b", "scores": dict(zip(D5, [4, 2, 3, 2, 1]))}]}


def test_session_5_scores_are_compared_with_the_reference_domain_by_domain(tmp_path):
    rows, errors = course.compare_scores(MINE, REFERENCE)
    assert errors == []
    assert rows[0] == {"recording": "ref-a", "exact": 0.8, "within_one": 0.8, "domains": [
        {"domain": d, "score": s, "reference": r, "difference": s - r}
        for d, s, r in zip(D5, [3, 2, 3, 3, 2], [3, 2, 1, 3, 2])]}
    assert (rows[1]["exact"], rows[1]["within_one"]) == (0.8, 1.0)
    one = {"recordings": [{"recording": "ref-a", "scores": {**MINE["recordings"][0]["scores"], "lab-facilitation": 5}},
                          {"recording": "ref-c", "scores": {"technical-depth": 3}}]}
    assert course.compare_scores(one, REFERENCE)[1] == [
        "ref-a: lab-facilitation must be a whole number 1-4",
        "ref-c: not in the reference (ref-a, ref-b)",
        "ref-c: missing prior-knowledge, conceptual-questioning, lab-facilitation, remote-inclusive"]
    assert course.compare_scores({"recordings": MINE["recordings"][:1]}, REFERENCE)[1] == [
        "recordings: score at least two reference recordings"]
    mine, ref, out = tmp_path / "mine.yaml", tmp_path / "ref.yaml", tmp_path / "compared.yaml"
    mine.write_text(yaml.safe_dump(MINE), encoding="utf-8")
    ref.write_text(yaml.safe_dump(REFERENCE), encoding="utf-8")
    assert cli.main(["compare-scores", str(mine), "--reference", str(ref), "--out", str(out)]) == 0
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["recordings"] == rows
    mine.write_text(yaml.safe_dump(one), encoding="utf-8")
    assert cli.main(["compare-scores", str(mine), "--reference", str(ref)]) == 1


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("course") / "store"
    try:
        simulate.simulate(s, weeks=1, end=date(2026, 10, 23))
        yield s
    finally:
        mp.undo()


def test_sessions_are_recorded_once_with_an_evidence_key(store):
    regs = app.load_state(store).registrations
    who = sorted(regs)[0]
    course.record(store, who, "micro-teach", "evidence/ttt/round-forms-01.pdf", date(2026, 10, 20), regs)
    with pytest.raises(course.CourseError, match="already recorded"):
        course.record(store, who, "micro-teach", "evidence/ttt/again.pdf", date(2026, 10, 21), regs)
    with pytest.raises(course.CourseError, match="no session"):
        course.record(store, who, "juggling", "evidence/x", date(2026, 10, 21), regs)
    for bad in ("https://example.com/recording", "evidence/../identities/roster.yaml", "Jane Doe forms"):
        with pytest.raises(course.CourseError, match="private-store key"):
            course.record(store, who, "prior-knowledge", bad, date(2026, 10, 21), regs)
    with pytest.raises(course.CourseError, match="not a registered instructor"):
        course.record(store, "tm:instructor/nobody", "micro-teach", "evidence/x", date(2026, 10, 21), regs)
    rows = course.status(store, who)
    assert [r["session"] for r in rows] == SESSIONS
    assert rows[0]["recorded"] == "2026-10-20" and {r["recorded"] for r in rows[1:]} == {"missing"}


def test_the_sign_off_page_exists_only_once_every_session_is_recorded_and_binds_to_it(store):
    st = app.load_state(store)
    who = sorted(st.registrations)[1]
    for n, session in enumerate(SESSIONS[:-1], 1):
        course.record(store, who, session, f"evidence/ttt/{session}.pdf", date(2026, 10, n + 1), st.registrations)
        assert onboarding._b_train_the_trainer(app.load_state(store), who) == []  # nothing to approve yet
    assert course.missing(store, who) == ["Seeing teaching through the rubric"]
    course.record(store, who, SESSIONS[-1], f"evidence/ttt/{SESSIONS[-1]}.pdf", date(2026, 10, 6), st.registrations)
    after = onboarding._b_train_the_trainer(app.load_state(store), who)
    assert after and "Every session of the course is recorded" in after[0]["intro"]
    fields = {f["name"]: f for f in after[0]["fields"]}
    assert set(fields) == {"date", "note"}  # no delivery reference: the course is not a delivery
    assert fields["date"]["value"] == "2026-10-06"  # the last session's date
    assert after[0]["inputs"]["course"][4] == {"session": "rubric-scoring", "title": "Seeing teaching through the rubric",
                                               "recorded": "2026-10-06", "evidence": "evidence/ttt/rubric-scoring.pdf"}


def test_the_command_records_and_shows(store, capsys):
    who = sorted(app.load_state(store).registrations)[2]
    record = ["course", "record", "--private-dir", str(store), "--instructor", who, "--session", "remote-delivery",
              "--evidence-ref", "evidence/ttt/remote.pdf"]
    assert cli.main(record + ["--on", "2026-10-22"]) == 1  # the key names nothing in the store
    assert "evidence/ttt/remote.pdf is not in the private store" in capsys.readouterr().err
    (store / "evidence" / "ttt").mkdir(parents=True, exist_ok=True)
    (store / "evidence" / "ttt" / "remote.pdf").write_bytes(b"%PDF-1.7\n")
    assert cli.main(record) == 1  # no default date: the session's, never the day it is typed
    assert "--on" in capsys.readouterr().err
    assert cli.main(record + ["--on", "2026-10-22"]) == 0
    assert cli.main(["course", "status", "--private-dir", str(store), "--instructor", who]) == 0
    out = capsys.readouterr().out
    assert "2026-10-22  remote-delivery" in out and "1 of 5 sessions recorded" in out
    assert cli.main(["course", "record", "--private-dir", str(store), "--instructor", who]) == 1
    assert "--session and --evidence-ref" in capsys.readouterr().err


# --- intake (decision 0030): the session picks the check; a pass stores and records, a refusal is logged ----------

NOW = datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)
ON = date(2026, 10, 22)


def _who(store, n):
    return sorted(app.load_state(store).registrations)[n]


def _intake(store, who, session, path, on=ON, **kw):
    return course.intake(store, who, session, path, on, app.load_state(store).registrations, NOW, **kw)


def _yaml(tmp_path, name, doc):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def test_a_scan_that_passes_is_stored_under_a_generated_key_and_recorded_on_the_session_day(store, tmp_path):
    who = _who(store, 3)
    scan = tmp_path / "Round forms (Ana).pdf"
    scan.write_bytes(b"%PDF-1.7\n1 0 obj\n")
    sha = hashlib.sha256(scan.read_bytes()).hexdigest()
    got = _intake(store, who, "micro-teach", scan)
    assert got.stored and got.problems == []
    assert got.key == f"evidence/ttt/{who.split('/')[-1]}-micro-teach-{sha[:8]}.pdf"  # never the file's own name
    assert (store / got.key).read_bytes() == scan.read_bytes()
    assert course.read(store, who)["micro-teach"] == {"on": "2026-10-22", "evidence_ref": got.key}
    assert course.intake_log(store, who) == [{"at": NOW.isoformat(), "session": "micro-teach", "sha256": sha,
                                              "result": "stored", "key": got.key, "on": "2026-10-22"}]


@pytest.mark.parametrize("name, data, problem", [
    ("forms.pdf", b"", "The file is empty."),
    ("forms.docx", b"PK\x03\x04", "A scan is a PDF, PNG or JPEG file; this one is .docx."),
    ("forms.pdf", b"\x89PNG\r\n\x1a\n", "The file is named .pdf but is not a PDF."),
    ("forms.jpg", b"%PDF-1.7", "The file is named .jpg but is not a JPEG."),
])
def test_a_scan_that_is_not_one_is_refused(name, data, problem):
    assert course.scan_errors(name, data) == [problem]


def test_a_refused_question_set_stores_nothing_records_nothing_and_says_what_to_fix(store, tmp_path):
    who = _who(store, 4)
    item = QUESTIONS["pre_check"][0]
    bad = {"unit": QUESTIONS["unit"], "pre_check": [
        {**item, "options": item["options"][:2]},
        {**item, "options": item["options"][:2] + [{"text": "The loop times out"}]}]}
    path = _yaml(tmp_path, "questions.yaml", bad)
    got = _intake(store, who, "prior-knowledge", path)
    assert not got.stored and got.key is None
    assert got.problems == [
        "Question 1: needs 3 to 5 options, has 2.",
        "Question 2, option C: say which wrong idea this answer shows (a misconception id from the unit, "
        "or proposed_misconception)."]
    assert "prior-knowledge" not in course.read(store, who)
    assert not list((store / "evidence" / "ttt").glob(f"{who.split('/')[-1]}-prior-knowledge-*"))
    entry = course.intake_log(store, who)[-1]
    assert entry == {"at": NOW.isoformat(), "session": "prior-knowledge",
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "result": "refused",
                     "problems": got.problems}
    assert course.returned(store, who) == {"prior-knowledge": 2}
    (tmp_path / "broken.yaml").write_text("pre_check: [\n", encoding="utf-8")
    unreadable = _intake(store, who, "prior-knowledge", tmp_path / "broken.yaml")
    assert len(unreadable.problems) == 1 and unreadable.problems[0].startswith("The file cannot be read as YAML")
    assert course.returned(store, who) == {"prior-knowledge": 1}  # the latest refusal counts
    fixed = _intake(store, who, "prior-knowledge", _yaml(tmp_path, "fixed.yaml", QUESTIONS))
    assert fixed.stored and fixed.key.endswith(".yaml")
    assert yaml.safe_load((store / fixed.key).read_text(encoding="utf-8")) == QUESTIONS
    assert course.returned(store, who) == {}  # recorded now, so no longer sent back
    assert [e["result"] for e in course.intake_log(store, who)] == ["refused", "refused", "stored"]  # appended


def test_a_failure_log_is_checked_against_the_catalogue_it_is_given(store, tmp_path):
    who = _who(store, 5)
    log = _yaml(tmp_path, "log.yaml", LOG)
    with pytest.raises(course.CourseError, match="--catalogue"):
        _intake(store, who, "lab-facilitation", log)
    assert course.intake_log(store, who) == []  # a missing option is the operator's slip, not the participant's
    refused = _intake(store, who, "lab-facilitation", _yaml(tmp_path, "bad.yaml", {**LOG, "failure": "wifi-down"}),
                      catalogue=_yaml(tmp_path, "catalogue.yaml", CATALOGUE))
    assert refused.problems == ["failure: wifi-down is not in the catalogue (room-unreachable, stale-room-code)."]
    got = _intake(store, who, "lab-facilitation", log, catalogue=tmp_path / "catalogue.yaml")
    assert got.stored and yaml.safe_load((store / got.key).read_text(encoding="utf-8")) == LOG


def test_session_5_stores_the_comparison_not_the_typed_scores(store, tmp_path):
    who = _who(store, 6)
    (store / "reference").mkdir(exist_ok=True)
    (store / "reference" / "ttt-rubric.yaml").write_text(yaml.safe_dump(REFERENCE), encoding="utf-8")
    mine = _yaml(tmp_path, "scores.yaml", MINE)
    with pytest.raises(course.CourseError, match="--reference"):
        _intake(store, who, "rubric-scoring", mine)
    with pytest.raises(course.CourseError, match="reference/none.yaml is not in the private store"):
        _intake(store, who, "rubric-scoring", mine, reference="reference/none.yaml")
    got = _intake(store, who, "rubric-scoring", mine, reference="reference/ttt-rubric.yaml")
    assert got.stored and got.key.endswith(".yaml")
    assert yaml.safe_load((store / got.key).read_text(encoding="utf-8")) == {
        "recordings": course.compare_scores(MINE, REFERENCE)[0]}
    assert course.intake_log(store, who)[-1]["sha256"] == hashlib.sha256(mine.read_bytes()).hexdigest()


def test_an_intake_the_coordinator_cannot_make_is_an_error_and_logs_nothing(store, tmp_path):
    who = _who(store, 8)
    scan = tmp_path / "forms.pdf"
    scan.write_bytes(b"%PDF-1.7\n")
    assert _intake(store, who, "micro-teach", scan).stored  # its own record: the suite runs tests in any order
    before = course.intake_log(store, who)
    for kwargs, match in [
        ({"session": "micro-teach"}, "already recorded"),
        ({"session": "juggling"}, "no session"),
        ({"session": "remote-delivery", "on": date(2026, 10, 24)}, "after today"),
        ({"session": "remote-delivery", "who": "tm:instructor/nobody"}, "not a registered instructor")]:
        with pytest.raises(course.CourseError, match=match):
            _intake(store, kwargs.get("who", who), kwargs["session"], scan, on=kwargs.get("on", ON))
    with pytest.raises(course.CourseError, match="no file"):
        _intake(store, who, "remote-delivery", tmp_path / "absent.pdf")
    assert course.intake_log(store, who) == before


def test_every_session_names_a_known_check(tmp_path):
    assert [s["check"] for s in course.sessions()] == ["scan", "question-set", "failure-log", "scan", "scores"]
    (tmp_path / "standards").mkdir()
    (tmp_path / "standards" / "framework.yaml").write_text("domains: [{id: lab-facilitation}]\n", encoding="utf-8")
    (tmp_path / "standards" / "train-the-trainer.yaml").write_text(yaml.safe_dump({"sessions": [
        {"id": "a", "title": "A", "domains": ["lab-facilitation"], "evidence": "x", "check": "vibes"}]}),
        encoding="utf-8")
    with pytest.raises(course.CourseError, match="session a: check vibes"):
        course.sessions(tmp_path)


def test_the_intake_command_stores_or_returns_with_problems(store, tmp_path, capsys):
    who = _who(store, 7)
    scan = tmp_path / "remote.png"
    scan.write_bytes(b"\x89PNG\r\n\x1a\n....")
    base = ["course", "intake", "--private-dir", str(store), "--instructor", who, "--session", "remote-delivery"]
    assert cli.main(base + [str(scan)]) == 1
    assert "--on" in capsys.readouterr().err
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    assert cli.main(base + [str(empty), "--on", "2026-10-22"]) == 1
    captured = capsys.readouterr()
    assert "The file is empty." in captured.err and "returned: 1 problem" in captured.out
    assert cli.main(base + [str(scan), "--on", "2026-10-22"]) == 0
    out = capsys.readouterr().out
    assert f"stored as evidence/ttt/{who.split('/')[-1]}-remote-delivery-" in out and "recorded on 2026-10-22" in out
