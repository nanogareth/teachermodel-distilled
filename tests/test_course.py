"""`teachermodel course` (course.py) and the W1 train-the-trainer sign-off page that lists the course record
(docs/train-the-trainer/DESIGN.md). One-week simulated store, generated data only."""

from datetime import date

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
    assert cli.main(["course", "record", "--private-dir", str(store), "--instructor", who, "--session", "remote-delivery",
                     "--evidence-ref", "evidence/ttt/remote.pdf", "--on", "2026-10-22"]) == 0
    assert cli.main(["course", "status", "--private-dir", str(store), "--instructor", who]) == 0
    out = capsys.readouterr().out
    assert "2026-10-22  remote-delivery" in out and "1 of 5 sessions recorded" in out
    assert cli.main(["course", "record", "--private-dir", str(store), "--instructor", who]) == 1
    assert "--session and --evidence-ref" in capsys.readouterr().err
