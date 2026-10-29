"""Instructor replies and appeals (standards/workflows/rights.yaml; spec v0.2 Privacy, instructor rights; decision 0021).

    reply-or-appeal (the instructor)  ->  a `step` event {step, decision, kind: reply | appeal, text_key, signoff_id} on the
                                          instructor; the text in the private store (rights/<hex>.json). An appeal also opens
                                          an `appeal` subject (subject@2) {instructor, decision, request_ref}
    appeal-decision (head of training) ->  a `check` event {step, result: upheld | varied, appeal, decided_by, reason_key,
                                          signoff_id}; the reason in the private store

The decisions an instructor may reply to are read from the log: their clearances, level changes, bench decisions, the
overrides decided for them, and the audits that referred them back to calibration. Each is named by its event id, so the
reply points at exactly one record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import events
from ..signoff import short_sha as _hex
from ..util import iso_seconds
from ..workflow import SYSTEM_ACTOR
from . import content_check, on_signoff, register
from .common import HEAD_ROLE, is_head, PageProblem, State, people_with, spec
from .dry_run import is_candidates_instructor
from .pathway import subject_event_id

STEP_REPLY = "tm:step/reply-or-appeal"
STEP_APPEAL = "tm:step/appeal-decision"
KINDS = ("reply", "appeal")
OUTCOMES = ("upheld", "varied")
STORE_DIR = "rights"


def text_key(signoff_id: str) -> str:
    return f"{STORE_DIR}/{_hex({'rights_text': signoff_id})}.json"


def appeal_uri(signoff_id: str) -> str:
    return "tm:appeal/" + _hex({"appeal": signoff_id}, 16)


def decisions(st: State, instructor: str) -> list[dict[str, Any]]:
    """The instructor's decisions on record, oldest first: {id, kind, date, summary}."""
    out = []
    for e in st.events:
        p, kind = e["payload"], e["kind"]
        row = None
        if kind == "clearance" and p.get("instructor") == instructor:
            row = ("clearance", f"{p.get('outcome')} for {p.get('unit')} ({', '.join(p.get('modes', []))})")
        elif kind == "level_change" and e["subject_uri"] == instructor:
            row = ("level change", f"{p.get('from')} to {p.get('to')}")
        elif kind == "bench_decision" and p.get("instructor") == instructor:
            row = ("bench decision", str(p.get("decision")))
        elif kind == "check" and p.get("step") == "tm:step/override-decision" and p.get("result") in ("granted", "declined") \
                and (st.subjects.get(e["subject_uri"]) or {}).get("instructor") == instructor:
            row = ("override", f"{p.get('result')} for {e['subject_uri']}")
        elif kind == "audit" and p.get("observer") == instructor and p.get("referred_to_calibration"):
            row = ("audit referral", f"sample {p.get('sample')}")
        if row:
            out.append({"id": e["id"], "kind": row[0], "date": e["at"][:10], "summary": row[1]})
    return out


def replies(st: State, instructor: str) -> list[dict[str, Any]]:
    return [e["payload"] for e in st.index.of("step", instructor) if e["payload"].get("step") == STEP_REPLY]


@register(STEP_REPLY)
def _b_reply(st: State, instructor: str):
    info = st.subjects.get(instructor)
    if info is None or info.get("kind") != "instructor":
        raise PageProblem(f"{instructor} is not an instructor")
    mine = decisions(st, instructor)
    if not mine:
        raise PageProblem(f"{instructor} has no decision on record to reply to yet")
    inputs = {"instructor": instructor, "decisions": mine, "replies": len(replies(st, instructor))}
    fields = [
        {"name": "decision", "label": "The decision", "kind": "enum", "options": [d["id"] for d in mine], "required": True,
         "help": "The id of the decision, as listed above."},
        {"name": "kind", "label": "Reply or appeal", "kind": "enum", "options": list(KINDS), "required": True,
         "help": "A reply goes on your record beside the decision. An appeal also asks the head of training to "
                 "decide it again."},
        {"name": "text", "label": "Your words (private)", "kind": "textarea", "required": True,
         "help": "They stay in the private store; your record holds a key to them."},
    ]
    intro = ("You can reply to any decision on your record, or appeal it to the head of training (spec, instructor "
             "rights). Nothing here is needed unless you want to: if you do not, simply do not send this page. After each "
             "reply the page comes back for another one.")
    return [spec(st, STEP_REPLY, instructor, instructor, "approve", inputs, fields, intro)]


def _reply_reasons(st: State, document: dict[str, Any]) -> list[str]:
    instructor = document.get("subject_uri")
    if (st.subjects.get(instructor) or {}).get("kind") != "instructor":
        return ["the subject is not an instructor"]
    reasons = []
    if document.get("signer") != instructor:
        reasons.append("only the instructor replies on their own record")
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return reasons + ["the sign-off carries no fields"]
    if fields.get("decision") not in {d["id"] for d in decisions(st, instructor)}:
        reasons.append("decision: one of your decisions on record is required")
    if fields.get("kind") not in KINDS:
        reasons.append("kind: reply or appeal is required")
    if not isinstance(fields.get("text"), str) or not fields["text"].strip():
        reasons.append("text: your words are required")
    return reasons


content_check(STEP_REPLY)(_reply_reasons)


@on_signoff(STEP_REPLY)
def _record_reply(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    if _reply_reasons(st, document):
        return [], []
    instructor, fields, sid = signed["subject_uri"], document["fields"], signed["payload"]["signoff_id"]
    key = text_key(sid)
    stamp = iso_seconds(now)
    out = [events.make_event(
        "step", instructor, signed["actor"],
        {"step": STEP_REPLY, "decision": fields["decision"], "kind": fields["kind"], "text_key": key, "signoff_id": sid},
        id=_hex({"reply": sid}), at=stamp)]
    if fields["kind"] == "appeal":
        uri = appeal_uri(sid)
        out.append(events.make_event(
            "subject", uri, SYSTEM_ACTOR,
            {"subject_kind": "appeal", "opened_by": STEP_REPLY,
             "attrs": {"instructor": instructor, "decision": fields["decision"], "request_ref": key}},
            id=subject_event_id(uri), at=stamp))
    private = {"signoff_id": sid, "instructor": instructor, "decision": fields["decision"], "kind": fields["kind"],
               "text": fields["text"].strip()}
    return out, [(key, private)]


def _appeal(st: State, subject: str) -> dict[str, Any]:
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "appeal":
        raise PageProblem(f"{subject} is not an appeal")
    return info


@register(STEP_APPEAL)
def _b_appeal(st: State, subject: str):
    info = _appeal(st, subject)
    heads = [r["person"] for r in people_with(st, HEAD_ROLE) if not is_candidates_instructor(st, r["person"], info["instructor"])]
    if not heads:
        raise PageProblem(f"{subject}: no head of training other than the instructor can decide it")
    decided = next((d for d in decisions(st, info["instructor"]) if d["id"] == info["decision"]), None)
    inputs = {"appeal": subject, "instructor": info["instructor"], "decision": decided or {"id": info["decision"]},
              "request_ref": info["request_ref"]}
    fields = [
        {"name": "outcome", "label": "Decision", "kind": "enum", "options": list(OUTCOMES), "required": True,
         "help": "Upheld: the decision stands. Varied: you will change it through the ordinary workflow (a new clearance "
                 "round, a revocation, a level decision); this page records your decision and changes nothing by itself."},
        {"name": "reason", "label": "Reason (private)", "kind": "textarea", "required": True,
         "help": "It stays in the private store; the log holds a key."},
    ]
    intro = (f"{info['instructor']} appeals the decision shown below. Their words are in the private store at "
             f"{info['request_ref']}. Decide it again, as the head of training (spec, instructor rights).")
    return [spec(st, STEP_APPEAL, subject, h, "approve", inputs, fields, intro) for h in heads]


def _appeal_reasons(st: State, document: dict[str, Any]) -> list[str]:
    info = st.subjects.get(document.get("subject_uri"))
    if info is None or info.get("kind") != "appeal":
        return ["the subject is not an appeal"]
    signer = document.get("signer")
    reasons = []
    if not is_head(st, signer):
        reasons.append("the signer is not the head of training")
    if is_candidates_instructor(st, signer, info["instructor"]):
        reasons.append("the signer is the instructor who appeals")
    fields = document.get("fields")
    if not isinstance(fields, dict):
        return reasons + ["the sign-off carries no fields"]
    if fields.get("outcome") not in OUTCOMES:
        reasons.append("outcome: upheld or varied is required")
    if not isinstance(fields.get("reason"), str) or not fields["reason"].strip():
        reasons.append("reason: a written reason is required")
    return reasons


content_check(STEP_APPEAL)(_appeal_reasons)


@on_signoff(STEP_APPEAL)
def _record_appeal(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    if _appeal_reasons(st, document):
        return [], []
    subject, fields, sid = signed["subject_uri"], document["fields"], signed["payload"]["signoff_id"]
    key = text_key(sid)
    event = events.make_event(
        "check", subject, signed["actor"],
        {"step": STEP_APPEAL, "result": fields["outcome"], "appeal": subject, "decided_by": signed["actor"],
         "reason_key": key, "signoff_id": sid},
        id=_hex({"appeal_decision": [subject, sid]}), at=iso_seconds(now))
    return [event], [(key, {"appeal": subject, "outcome": fields["outcome"], "reason": fields["reason"].strip(),
                            "signoff_id": sid, "decided_by": signed["actor"]})]
