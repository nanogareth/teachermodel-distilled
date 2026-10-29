import json

import pytest

from teachermodel import events

OBS = {
    "instructor": "tm:instructor/eng-1",
    "unit": "sl:unit/example-agent-loop@1",
    "observer": "tm:instructor/obs-a",
    "length": "full",
    "lead": True,
    "rubric_version": "0.2.0",
    "scores": {"technical-depth": 3},
}


def make(**kw):
    return events.make_event(
        "observation", "tm:instructor/eng-1", "tm:instructor/obs-a", OBS,
        id="evt00000001", at="2026-10-23T10:00:00+00:00", **kw,
    )


def test_round_trip_and_verify(tmp_path):
    log = tmp_path / "events.jsonl"
    events.append(log, make())
    assert [e["id"] for e in events.read(log)] == ["evt00000001"]
    assert events.verify(log) == []


def test_tampered_payload_fails_receipt(tmp_path):
    log = tmp_path / "events.jsonl"
    events.append(log, make())
    event = json.loads(log.read_text())
    event["payload"]["scores"]["technical-depth"] = 4
    log.write_text(json.dumps(event) + "\n")
    assert any("receipt" in e for e in events.verify(log))


def test_rejects_unknown_kind_and_bad_payload(tmp_path):
    bad = events.make_event("gossip", "tm:instructor/x", "tm:instructor/y", {})
    with pytest.raises(events.EventError):
        events.append(tmp_path / "e.jsonl", bad)
    payload = dict(OBS, scores={"technical-depth": 5})
    bad_obs = events.make_event("observation", "tm:instructor/eng-1", "tm:instructor/obs-a", payload)
    with pytest.raises(events.EventError):
        events.append(tmp_path / "e.jsonl", bad_obs)


def test_duplicate_ids_flagged(tmp_path):
    log = tmp_path / "events.jsonl"
    events.append(log, make())
    events.append(log, make())
    assert any("duplicate" in e for e in events.verify(log))
