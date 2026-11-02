"""deploy/claude/relay/relay.py on a fake Anthropic client (decision 0029): nothing here calls the Claude API. A press
starts a budgeted session with the presser's vault; each pending write becomes a card showing the exact call; only the
presser's answer reaches the session; the relay never approves anything itself; the finished session is a
claude-session@1 record the store accepts."""

import sys
from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from teachermodel import feeds
from teachermodel.standards import ROOT

sys.path.insert(0, str(ROOT / "deploy" / "claude" / "relay"))
import relay  # noqa: E402

COORD = "tm:person/sim-coord-1"
ACTION = "0123456789abcdef"
KIT = {"agents": {"grader-ticket": "agent_01grader"}, "environment": "env_01buttons"}


class FakeClient:
    def __init__(self):
        self.sent, self.created, self.events, self.status = [], [], [], "idle"
        self.beta = NS(sessions=NS(create=self._create, retrieve=self._retrieve,
                                   events=NS(send=self._send, list=lambda session_id: list(self.events))),
                       webhooks=NS(unwrap=self._unwrap))

    def _create(self, **kw):
        self.created.append(kw)
        return NS(id="sesn_011CZx")

    def _retrieve(self, session_id):
        meta = self.created[0]["metadata"] if self.created else {}
        return NS(id=session_id, metadata=meta, created_at=datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc),
                  status=self.status, stop_reason=None)

    def _send(self, session_id, events):
        self.sent.extend(events)
        self.events.extend({"type": e["type"], "tool_use_id": e.get("tool_use_id")} for e in events)

    def _unwrap(self, body, headers):
        if headers.get("webhook-signature") != "good":
            raise ValueError("bad signature")
        kind, wid = body.split("|")
        return NS(id=wid, data=NS(type=kind, id="sesn_011CZx"))


class FakeIO:
    def __init__(self):
        self.cards, self.records, self.webhooks, self.memory = [], [], set(), {}

    def post_card(self, to, card):
        self.cards.append((to, card))

    def store(self, record):
        self.records.append(record)

    def seen(self, webhook_id):
        was = webhook_id in self.webhooks
        self.webhooks.add(webhook_id)
        return was

    def remember(self, key, value=None):
        if value is not None:
            self.memory[key] = value
        return self.memory.get(key)


def write_call(event_id="sevt_01write", **over):
    return {"type": "agent.mcp_tool_use", "id": event_id, "name": "createJiraIssue", "mcp_server_name": "atlassian",
            "input": {"project": "GRADE", "summary": "No results for sim-2026-10-d7h2k-1", "expected": 18},
            "evaluated_permission": "ask"} | over


@pytest.fixture
def started():
    client, io = FakeClient(), FakeIO()
    press = relay.Press("grader-ticket", ACTION, COORD, {"deliveries": [{"session": "sim-2026-10-d7h2k-1"}]},
                        "vlt_01coord")
    assert relay.start(client, press, KIT) == "sesn_011CZx"
    return client, io


def test_a_press_starts_a_budgeted_session_in_the_pressers_vault(started):
    client, _ = started
    created = client.created[0]
    assert created["agent"] == "agent_01grader" and created["vault_ids"] == ["vlt_01coord"]
    assert created["budget"] == {"type": "limit", "max_list_cost": {"amount": relay.BUDGET_CENTS, "currency": "USD"}}
    assert created["metadata"] == {"button": "grader-ticket", "action_id": ACTION, "presser": COORD}
    assert client.sent[0]["type"] == "user.message" and "sim-2026-10-d7h2k-1" in client.sent[0]["content"][0]["text"]


def test_a_pending_write_becomes_a_card_with_the_exact_call(started):
    client, io = started
    client.events += [{"type": "agent.mcp_tool_use", "id": "sevt_01read", "name": "getJiraIssue",
                       "mcp_server_name": "atlassian", "evaluated_permission": "allow"}, write_call()]
    assert relay.on_webhook(client, "session.status_idled|whk_1", {"webhook-signature": "good"}, io) == \
        "1 card(s) posted"
    to, card = io.cards[0]
    assert to == COORD and "createJiraIssue in atlassian" in card["body"][0]["text"]
    assert {f["title"] for f in card["body"][1]["facts"]} == {"project", "summary", "expected"}
    assert [a["data"]["decision"] for a in card["actions"]] == ["allow", "deny"]
    assert relay.on_webhook(client, "session.status_idled|whk_1", {"webhook-signature": "good"}, io) == "duplicate"
    assert not [e for e in client.sent if e["type"] == "user.tool_confirmation"]  # the relay never approves
    with pytest.raises(ValueError, match="signature"):
        relay.on_webhook(client, "session.status_idled|whk_2", {"webhook-signature": "forged"}, io)


def test_only_the_presser_answers_and_only_a_pending_call(started):
    client, io = started
    client.events.append(write_call())
    with pytest.raises(PermissionError, match="did not press"):
        relay.on_answer(client, relay.Answer("sesn_011CZx", "sevt_01write", "allow", "tm:person/sim-coord-2"), io)
    with pytest.raises(ValueError, match="not a write waiting"):
        relay.on_answer(client, relay.Answer("sesn_011CZx", "sevt_99other", "allow", COORD), io)
    assert relay.on_answer(client, relay.Answer("sesn_011CZx", "sevt_01write", "deny", COORD,
                                                "Use project GRADER, not GRADE"), io) == "deny"
    assert client.sent[-1] == {"type": "user.tool_confirmation", "tool_use_id": "sevt_01write", "result": "deny",
                               "deny_message": "Use project GRADER, not GRADE"}
    with pytest.raises(ValueError, match="not a write waiting"):  # answered once
        relay.on_answer(client, relay.Answer("sesn_011CZx", "sevt_01write", "allow", COORD), io)


def test_the_finished_session_is_a_record_the_store_accepts(started):
    client, io = started
    client.events.append(write_call("sevt_01deny"))
    relay.on_answer(client, relay.Answer("sesn_011CZx", "sevt_01deny", "deny", COORD, "wrong project"), io)
    client.events.append(write_call("sevt_02write", input={"project": "GRADER", "summary": "No results", "expected": 18}))
    relay.on_answer(client, relay.Answer("sesn_011CZx", "sevt_02write", "allow", COORD), io)
    client.events += [{"type": "agent.mcp_tool_result", "mcp_tool_use_id": "sevt_02write", "is_error": False},
                      {"type": "session.status_idle", "stop_reason": {"type": "end_turn"}}]
    assert relay.on_webhook(client, "session.status_idled|whk_9", {"webhook-signature": "good"}, io) == "recorded"
    record = io.records[0]
    assert feeds.problems(record) == []  # the store's own contract and the button's declared writes
    assert [(c["decision"], c["result"]) for c in record["calls"]] == [("deny", "not-run"), ("allow", "ok")]
    assert record["outcome"] == "completed" and record["started_at"] == "2026-10-30T09:00:00+00:00"
    assert "GRADER" not in str(record)  # inputs are kept as a hash, never as text
