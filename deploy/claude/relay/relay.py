"""The relay between Teams and an acting button's Managed Agents session (decision 0029).
Owned by the programme account, deployed by IT (owner, 2026-10-30).

    start(client, press, kit)                    a button press: one session, the presser's vault, a budget
    on_webhook(client, body, headers, io)        Anthropic's signed webhook: post approval cards, record the end
    on_answer(client, answer, io)                a person's Approve or Deny on a card: the tool confirmation

Every write the agent makes pauses its session (the agents' write tools are `always_ask`, `teachermodel claude-kit`).
This relay turns each pending call into a Teams card showing the exact call, and sends the person's answer back as a
`user.tool_confirmation`. It approves nothing itself: there is no code path from a webhook to an `allow`. When the
session ends it writes a `claude-session@1` record (the store's contract) through `io.store`, which the flow drops in
the programme library for the store's inbox.

The client is `anthropic.Anthropic()` in the deployment (`function_app.py`); tests pass a fake. Event field names
for MCP tool calls and results are read through `_get`, which accepts the documented names and their alternatives;
confirm them against the Managed Agents events reference when deploying.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

BUDGET_CENTS = "200"  # per session: $2.00, a hard cap the platform enforces (operational default, decision 0002)
ENDED = {"end_turn": "completed", "budget_reached": "budget-reached"}


@dataclass(frozen=True)
class Press:
    button: str
    action_id: str
    presser: str  # tm:person/... or tm:instructor/...: the card was sent to this id (outbox@1 `to`)
    projection: dict[str, Any]  # the presser's own projection, as the card carried it
    vault_id: str  # the presser's vault: their own sign-ins to the connectors


@dataclass(frozen=True)
class Answer:
    session_id: str
    event_id: str  # the pending agent.mcp_tool_use event (sevt_...)
    decision: str  # "allow" | "deny"
    by: str  # the person who pressed the card (must be the session's presser)
    reason: str = ""


class IO(Protocol):
    def post_card(self, to: str, card: dict[str, Any]) -> None: ...
    def store(self, record: dict[str, Any]) -> None: ...
    def seen(self, webhook_id: str) -> bool: ...
    def remember(self, key: str, value: dict[str, Any] | None = None) -> dict[str, Any] | None: ...


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso(value: Any) -> str:
    return value.isoformat(timespec="seconds") if isinstance(value, datetime) else str(value).replace(" ", "T", 1)


def start(client: Any, press: Press, kit: dict[str, Any], now: Callable[[], str] = _now) -> str:
    """Start the button's session for this press; returns the session id. `kit` maps button ids to agent ids and holds
    the environment id (from claude-lock.json after `ant apply`)."""
    session = client.beta.sessions.create(
        agent=kit["agents"][press.button],
        environment_id=kit["environment"],
        vault_ids=[press.vault_id],
        title=f"{press.button} {press.action_id}",
        metadata={"button": press.button, "action_id": press.action_id, "presser": press.presser},
        budget={"type": "limit", "max_list_cost": {"amount": BUDGET_CENTS, "currency": "USD"}},
    )
    client.beta.sessions.events.send(session_id=session.id, events=[{
        "type": "user.message",
        "content": [{"type": "text", "text": "The view you may use, as JSON:\n"
                     + json.dumps(press.projection, sort_keys=True)}],
    }])
    return session.id


def card_for(session_id: str, event: Any, presser: str) -> dict[str, Any]:
    """The approval card: the system, the tool and every field the call would write, with Approve and Deny."""
    fields = _get(event, "input", default={}) or {}
    return {"type": "AdaptiveCard", "version": "1.5",
            "body": [{"type": "TextBlock", "weight": "Bolder", "wrap": True,
                      "text": f"Claude wants to {_get(event, 'name', 'tool_name')} in "
                              f"{_get(event, 'mcp_server_name', 'server_name', default='a connected system')}"},
                     {"type": "FactSet", "facts": [{"title": str(k), "value": json.dumps(v)[:500]}
                                                   for k, v in sorted(fields.items())]},
                     {"type": "Input.Text", "id": "reason", "placeholder": "Why not (sent to Claude if you deny)",
                      "isMultiline": True}],
            "actions": [{"type": "Action.Submit", "title": "Approve",
                         "data": {"session_id": session_id, "event_id": _get(event, "id"), "decision": "allow",
                                  "by": presser}},
                        {"type": "Action.Submit", "title": "Deny",
                         "data": {"session_id": session_id, "event_id": _get(event, "id"), "decision": "deny",
                                  "by": presser}}]}


def _pending(events: list[Any]) -> list[Any]:
    answered = {_get(e, "tool_use_id") for e in events if _get(e, "type") == "user.tool_confirmation"}
    return [e for e in events if _get(e, "type") == "agent.mcp_tool_use"
            and _get(e, "evaluated_permission") == "ask" and _get(e, "id") not in answered]


def _last_stop(events: list[Any]) -> str | None:
    idle = [e for e in events if _get(e, "type") == "session.status_idle"]
    return _get(_get(idle[-1], "stop_reason", default={}) or {}, "type") if idle else None


def session_record(session: Any, events: list[Any], io: IO) -> dict[str, Any]:
    """claude-session@1 from the session's events and the answers this relay recorded (who, when)."""
    meta = _get(session, "metadata", default={}) or {}
    results = {}
    for e in events:
        if _get(e, "type") == "agent.mcp_tool_result":
            results[_get(e, "mcp_tool_use_id", "tool_use_id")] = "error" if _get(e, "is_error") else "ok"
    calls = []
    for e in events:
        if _get(e, "type") != "agent.mcp_tool_use" or _get(e, "evaluated_permission") != "ask":
            continue  # reads run as always_allow and are not records of change
        answer = io.remember(f"answer:{_get(e, 'id')}") or {}
        decision = answer.get("decision", "deny")
        calls.append({"event_id": _get(e, "id"), "server": _get(e, "mcp_server_name", "server_name"),
                      "tool": _get(e, "name", "tool_name"),
                      "input_sha256": hashlib.sha256(json.dumps(_get(e, "input", default={}), sort_keys=True)
                                                     .encode("utf-8")).hexdigest(),
                      "decision": decision, "decided_by": answer.get("by", meta.get("presser")),
                      "decided_at": answer.get("at", _now()),
                      "result": results.get(_get(e, "id"), "not-run") if decision == "allow" else "not-run"})
    stop = _last_stop(events)  # the session object has no stop_reason: the latest status_idle event carries it
    outcome = ENDED.get(stop, "completed" if _get(session, "status") == "terminated" else "abandoned")
    if outcome == "completed" and calls and all(c["decision"] == "deny" for c in calls):
        outcome = "denied"
    if any(c["result"] == "error" for c in calls):
        outcome = "failed"
    return {"schema": "tm:contract/claude-session@1", "session_id": _get(session, "id"),
            "button": meta.get("button"), "action_id": meta.get("action_id"), "presser": meta.get("presser"),
            "started_at": _iso(_get(session, "created_at")), "ended_at": _now(), "calls": calls, "outcome": outcome}


def on_webhook(client: Any, body: str, headers: dict[str, str], io: IO) -> str:
    """Verify, de-duplicate, then post a card for each pending write, or record a finished session."""
    event = client.beta.webhooks.unwrap(body, headers=headers)  # verifies the signature and the age
    if io.seen(_get(event, "id")):
        return "duplicate"
    data = _get(event, "data")
    kind, session_id = _get(data, "type"), _get(data, "id")
    if kind not in ("session.status_idled", "session.status_terminated"):
        return f"ignored {kind}"
    session = client.beta.sessions.retrieve(session_id)
    events = list(client.beta.sessions.events.list(session_id=session_id))
    presser = (_get(session, "metadata", default={}) or {}).get("presser")
    pending = _pending(events)
    for e in pending:
        io.post_card(presser, card_for(session_id, e, presser))
    if pending:
        return f"{len(pending)} card(s) posted"
    if kind == "session.status_terminated" or _last_stop(events) in ENDED:
        io.store(session_record(session, events, io))
        return "recorded"
    return "waiting"


def on_answer(client: Any, answer: Answer, io: IO) -> str:
    """A person's Approve or Deny. Refused unless it comes from the session's presser, for a call still pending."""
    if answer.decision not in ("allow", "deny"):
        raise ValueError("a decision is allow or deny")
    session = client.beta.sessions.retrieve(answer.session_id)
    presser = (_get(session, "metadata", default={}) or {}).get("presser")
    if answer.by != presser:
        raise PermissionError(f"{answer.by} did not press this button; only {presser} may approve its writes")
    events = list(client.beta.sessions.events.list(session_id=answer.session_id))
    if answer.event_id not in {_get(e, "id") for e in _pending(events)}:
        raise ValueError(f"{answer.event_id} is not a write waiting for approval in {answer.session_id}")
    confirmation = {"type": "user.tool_confirmation", "tool_use_id": answer.event_id, "result": answer.decision}
    if answer.decision == "deny" and answer.reason.strip():
        confirmation["deny_message"] = answer.reason.strip()
    client.beta.sessions.events.send(session_id=answer.session_id, events=[confirmation])
    io.remember(f"answer:{answer.event_id}", {"decision": answer.decision, "by": answer.by, "at": _now()})
    return answer.decision
