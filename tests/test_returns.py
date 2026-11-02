"""What comes back from the Claude buttons and the cards (decision 0029): drafts that must fit their button's schema,
session records whose every write a person allowed, commands; kept under outbox/received/ through the inbox."""

import json

import pytest

from teachermodel import cli, feeds

ACTION = "0123456789abcdef"


def draft(**content):
    body = {"slots": [{"start": "2026-11-03T10:00", "end": "2026-11-03T11:00"}],
            "message": "Three times that suit you both."} | content
    return {"schema": feeds.DRAFT, "button": "propose-slots", "action_id": ACTION,
            "drafted_at": "2026-10-30T09:00:00+00:00", "model": "interactive session", "content": body}


def call(**over):
    return {"event_id": "sevt_01abc", "server": "atlassian", "tool": "createJiraIssue", "input_sha256": "a" * 64,
            "decision": "allow", "decided_by": "tm:person/sim-coord-1", "decided_at": "2026-10-30T09:05:00+00:00",
            "result": "ok"} | over


def session(*calls, **over):
    return {"schema": feeds.SESSION, "session_id": "sesn_011CZx", "button": "grader-ticket", "action_id": ACTION,
            "presser": "tm:person/sim-coord-1", "started_at": "2026-10-30T09:00:00+00:00",
            "ended_at": "2026-10-30T09:06:00+00:00", "calls": list(calls), "outcome": "completed"} | over


def write(path, doc):
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_a_draft_must_fit_its_buttons_schema():
    assert feeds.problems(draft()) == []
    assert any(p.startswith("content/") for p in feeds.problems(draft(slots=[])))
    assert any("not a drafting button" in p for p in feeds.problems(draft() | {"button": "grader-ticket"}))


@pytest.mark.parametrize("calls, expected", [
    ([call()], None),
    ([call(tool="deleteJiraIssue")], "not a write this button declares"),
    ([call(server="salesforce", tool="dispatch")], "not a write this button declares"),
    ([call(decision="deny")], "ran without a person's allow"),
    ([call(decision="deny", result="not-run")], None),
])
def test_a_session_may_only_make_declared_writes_a_person_allowed(calls, expected):
    found = feeds.problems(session(*calls))
    assert (found == []) if expected is None else any(expected in p for p in found)


def test_returns_are_kept_one_per_key_and_a_newer_draft_replaces_an_older_one(tmp_path):
    feeds.import_feed(tmp_path, write(tmp_path / "d1.json", draft()))
    newer = draft(message="A better time is Thursday.") | {"drafted_at": "2026-10-30T10:00:00+00:00"}
    feeds.import_feed(tmp_path, write(tmp_path / "d2.json", newer))
    kept = feeds.returns(tmp_path, feeds.DRAFT)
    assert [d["content"]["message"] for d in kept] == ["A better time is Thursday."]
    with pytest.raises(feeds.FeedError, match="newer draft replaces"):
        feeds.import_feed(tmp_path, write(tmp_path / "d3.json", draft(message="older")))
    feeds.import_feed(tmp_path, write(tmp_path / "s1.json", session(call())))
    feeds.import_feed(tmp_path, write(tmp_path / "s1.json", session(call())))  # the same file again is fine
    with pytest.raises(feeds.FeedError, match="kept once"):
        feeds.import_feed(tmp_path, write(tmp_path / "s2.json", session(call(), outcome="failed")))


def test_check_draft_reports_and_exits(tmp_path, capsys):
    assert cli.main(["check-draft", str(write(tmp_path / "ok.json", draft()))]) == 0
    assert cli.main(["check-draft", str(write(tmp_path / "bad.json", session(call(decision="deny"))))]) == 1
    assert "person's allow" in capsys.readouterr().err
