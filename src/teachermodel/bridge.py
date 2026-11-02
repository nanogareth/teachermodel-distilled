"""Driver bridge: read plans out, receipts in. Pure and deterministic; callers pass the data.

A plan lists read-only operations; a driver (connector, graph or fixture) executes them and returns a
receipt. Ingest is fail-closed: only `ok` results are evidence, every other outcome becomes a `check`
event that leaves the step open, and nothing a driver or a sender writes as free text reaches the log
(decision 0003). Spec: docs/specs/2026-10-24-workflow-automation-design.md sections 5, 6 and 11.

Per-op `data` shapes the driver returns:
- `site.library`: `{exists: bool}`. `args.name` is the folder search text and `args.library` the path a hit's
  `webUrl` must end with.
- `mail.sent`: `{messages: [{sender, to: [...], subject, sentDateTime}]}`
- `mail.tagged`: `{messages: [{sender, subject, received, attachments: [{name, content | content_base64}]}]}`.
  `sender` is the SMTP address from the message body, never a search hit's display form. `content` is
  UTF-8 text; a connector that returns base64 puts it under `content_base64` instead (strict base64
  of UTF-8 text). A message whose subject lacks `[tm-signoff` is not a sign-off and is ignored, which is
  how a shared mailbox that holds other mail is read. A tagged message with no `.json` attachment is
  rejected as `no sign-off file attached`, once per sign-off id.
- `file.get`: reserved for the Graph driver; the connector cannot report who uploaded a file.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, NamedTuple

from . import events, signoff
from .standards import validate
from .util import iso_seconds as _iso
from .workflow import APPROVING, PROGRAMME, REVOKE, SYSTEM_ACTOR, Due

PLAN_SCHEMA = "tm:contract/plan@1"
STEP_LIBRARY_EXISTS = "tm:step/library-exists"
STEP_NOTICE_SENT = "tm:step/notice-sent"
DEFAULT_DRIVERS = ("connector", "graph")
LIBRARY_CHANNEL_DISABLED = "library channel disabled until the Graph driver (createdBy unavailable)"
SIGNOFF_SEARCH = "tm-signoff"  # the bare text a driver searches for (brackets may be split by KQL)
SIGNOFF_SUBJECT_TAG = "[tm-signoff"  # what a sign-off message subject must contain
AUDITION_STEP = "tm:step/audition-score"  # decision 0031: set aside for the audition, never an event
REQUEST_FORM = "tm:contract/programme-request@1"  # decision 0034: not a sign-off; the sender is who asked

_SMTP_RE = re.compile(r"^[^@\s/]+@[^@\s]+$")
_STEP_RE = re.compile(r"^tm:step/[a-z0-9-]+$")
_SIGNOFF_ID_RE = re.compile(r"^[0-9a-f]{16,}$")
_SIGNOFF_SUBJECT_ID_RE = re.compile(r"\[tm-signoff ([^\]\s]+)\]")
NO_SIGNOFF_FILE = "no sign-off file attached"
_NOTICE_TAG_RE = re.compile(r"^\[tm-notice ([A-Za-z0-9][A-Za-z0-9-]*)\]$")  # `[tm-notice <variant>]`


def _sha(obj: Any) -> str:
    return hashlib.sha256(events.canonical(obj).encode("utf-8")).hexdigest()


def op_id(op: str, args: Mapping[str, Any]) -> str:
    """First 16 hex of sha256 over the canonical {op, args}: a re-plan gives the same id."""
    return _sha({"op": op, "args": args})[:16]


def plan_sha256(plan: Mapping[str, Any]) -> str:
    """Hash of the creation stamp and the ops: the same due list on the same day gives the same hash,
    and a receipt cannot be replayed against a later plan."""
    return _sha({"created": plan["created"], "ops": plan["ops"]})


def library_search_name(library: str) -> str:
    """The folder search text for a library: its last path segment with punctuation as spaces. The connector's search
    reads a hyphen as an operator, so `teachermodel-pilot` finds nothing and `teachermodel pilot` finds the folder
    (probe, 2026-10-27)."""
    last = [seg for seg in library.split("/") if seg][-1]
    return " ".join(re.split(r"[^0-9A-Za-z]+", last)).strip()


def _op(op: str, args: dict[str, Any], step: str | None, subject: str | None) -> dict[str, Any]:
    return {"op_id": op_id(op, args), "op": op, "args": args, "step": step, "subject": subject}


def build_plan(
    due: Iterable[Due],
    *,
    settings: Mapping[str, Any],
    recipients: Mapping[str, str],
    created: str,
    variants: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Read operations for the due `verify` steps plus the standing sign-off mailbox read.

    Returns (plan, problems). A notice-sent step with no recipient address is skipped and listed in
    `problems` rather than aborting the plan. Given `variants` (instructor uri -> the notice variant they are owed),
    each `mail.sent` op searches for `[tm-notice <variant>]`; an instructor with no variant is skipped and listed.
    Without it every op uses `settings["notice_tag"]`. There is no standing library read: the connector cannot
    say who uploaded a file, so the `file.get` op is reserved for the Graph driver.
    """
    ops: dict[str, dict[str, Any]] = {}
    problems: list[str] = []

    def add(o: dict[str, Any]) -> None:
        ops.setdefault(o["op_id"], o)

    for d in due:
        if d.type != "verify":
            continue
        if d.step == STEP_LIBRARY_EXISTS:
            add(_op("site.library", {"library": settings["library"],
                                     "name": library_search_name(settings["library"])}, d.step, d.subject))
        elif d.step == STEP_NOTICE_SENT:
            if d.subject not in recipients:
                problems.append(f"no recipient address for {d.subject}")
                continue
            tag = settings["notice_tag"]
            if variants is not None:
                if d.subject not in variants:
                    problems.append(f"no notice variant for {d.subject}")
                    continue
                tag = f"[tm-notice {variants[d.subject]}]"
            args = {"to": recipients[d.subject], "tag": tag, "since": settings["since"]}
            add(_op("mail.sent", args, d.step, d.subject))
        else:
            raise ValueError(f"no read operation defined for verify step {d.step}")
    add(_op("mail.tagged", {"tag": settings["signoff_tag"], "since": settings["since"],
                            "mailbox": settings["mailbox"]}, None, None))
    plan = {"schema": PLAN_SCHEMA, "created": created, "ops": sorted(ops.values(), key=lambda o: o["op_id"])}
    return plan, sorted(problems)


class _Readers(NamedTuple):
    """What the sign-off check reads from outside the receipt (the caller re-derives all of it from the current state)."""

    current_input: Callable[[str, str], str | None]
    current_rows: Callable[[str, str], Collection[str] | None]
    content_check: Callable[[dict[str, Any]], list[str]] | None
    taken: dict[tuple[str, str], set[str]]  # (step, subject) -> signers whose approving sign-off already counts
    opened_on: Callable[[str, str], date | None] | None  # (step, subject) -> the UTC day the step opened; None = unknown
    now: datetime  # the ingest clock: a sign-off may not be stamped after it (plus the clock skew)
    decided: dict[tuple[str, str], str]  # (step, subject) -> input hash of the latest single-decision sign-off accepted here
    revocable: set[tuple[str, str]]  # (step, subject) of revocable steps whose approval is in force (decision 0019)


@dataclass
class Applied:
    events: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    # (relative path in the private store, document): full sign-offs the caller writes there.
    private: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # Sign-off documents whose id was already accepted (a re-read message): the caller may restore a
    # missing stored copy after checking it against the logged event. Never evidence of anything new.
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    # The receipt run_at when the standing sign-off mailbox read came back ok (else None): the time
    # the next plan may search from.
    mailbox_read_at: datetime | None = None
    # Audition forms (document, verified sender), set aside before any workflow check and logged nowhere: the caller
    # hands them to `audition.receive` (decision 0031).
    auditions: list[tuple[dict[str, Any], str]] = field(default_factory=list)
    # Programme requests (document, verified sender): the caller hands them to `requests.receive` (decision 0034).
    requests: list[tuple[dict[str, Any], str]] = field(default_factory=list)


def _dt(value: Any) -> datetime:
    """Parse to an aware UTC datetime; a naive stamp or a bare date counts as UTC. (A receipt run_at
    is checked for an offset before this runs: a driver clock is never assumed to be UTC.)"""
    if isinstance(value, datetime):
        d = value
    elif isinstance(value, str):
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise TypeError("not a date-time")
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _safe_step(step: Any) -> str | None:
    return step if isinstance(step, str) and _STEP_RE.match(step) else None


def _safe_sid(sid: Any) -> str | None:
    return sid if isinstance(sid, str) and _SIGNOFF_ID_RE.match(sid) else None


def apply_receipt(
    receipt: Mapping[str, Any],
    plan: Mapping[str, Any],
    *,
    workflows: Mapping[str, Any],
    identities: Mapping[str, signoff.Identity],
    current_input: Callable[[str, str], str | None],
    current_rows: Callable[[str, str], Collection[str] | None],
    subjects: Mapping[str, Mapping[str, Any]],
    registrations: Mapping[str, Mapping[str, Any]],
    open_steps: Collection[tuple[str, str]],
    seen_ids: Iterable[str],
    existing_ids: Iterable[str],
    known_templates: Collection[str],
    owner_email: str,
    notice_version: str,
    now: Any,
    allowed_drivers: Collection[str] = DEFAULT_DRIVERS,
    content_check: Callable[[dict[str, Any]], list[str]] | None = None,
    accepted_signers: Mapping[tuple[str, str], Collection[str]] | None = None,
    opened_on: Callable[[str, str], date | None] | None = None,
    revocable: Collection[tuple[str, str]] = (),
) -> Applied:
    """Turn a receipt into events. A receipt for another plan, from a driver not allowed, outside the
    plan's time window or invalid yields no events. Events already in `existing_ids` are not returned.

    `content_check(document) -> reasons` rules on the content of an accepted approving sign-off (the flows register them,
    `flows.content_reasons`); any reason rejects it. `accepted_signers` maps (step, subject) to the signers whose approving
    sign-off is already in the log: a step with a `signer` takes one sign-off from each (decision 0012).

    `opened_on(step, subject)` is the UTC day the step opened for the subject (the caller derives it from the engine: the
    `subject` event's day for a child subject, else the day the step's needs were complete). A sign-off stamped before it,
    or more than a day after `now`, is rejected (`signoff.signed_at_reasons`); None means no lower bound is known.

    `revocable` holds the (step, subject) pairs of `revocable` steps whose approval is in force now: a sign-off with
    decision `revoke` is accepted only for one of them (decision 0019), and only once per approval."""
    schema_errors = validate(dict(receipt), "receipt.schema.json")
    if schema_errors:
        return Applied([], [f"receipt schema: {e}" for e in schema_errors])
    if validate(dict(plan), "plan.schema.json"):
        return Applied([], ["plan schema invalid"])
    if receipt["driver"] not in allowed_drivers:
        return Applied([], ["receipt driver is not allowed"])
    plan_hash = plan_sha256(plan)
    if receipt["plan_sha256"] != plan_hash:
        return Applied([], ["receipt plan_sha256 does not match the plan"])
    try:
        naive_run_at = datetime.fromisoformat(str(receipt["run_at"]).strip().replace("Z", "+00:00")).tzinfo is None
    except ValueError:
        naive_run_at = False  # reported below as not a date-time
    if naive_run_at:
        return Applied([], ["run_at must carry a UTC offset"])
    try:
        now_dt, created_dt, run_dt = _dt(now), _dt(plan["created"]), _dt(receipt["run_at"])
    except (ValueError, TypeError):
        return Applied([], ["receipt run_at, plan created or now is not a date-time"])
    if not created_dt <= run_dt <= now_dt:
        return Applied([], ["receipt run_at is outside the window from plan creation to now"])

    at = _iso(now)
    seen = set(seen_ids)
    existing = set(existing_ids)
    step_defs = {st["id"]: st for wf in workflows["workflows"] for st in wf["steps"]}
    open_set = set(open_steps)
    templates = set(known_templates)
    readers = _Readers(current_input, current_rows, content_check,
                       {k: set(v) for k, v in (accepted_signers or {}).items()}, opened_on, now_dt, {}, set(revocable))
    out = Applied()

    def add_event(ev: dict[str, Any], op: str, key: Any = None) -> bool:
        """Give the event its deterministic id; False when that event is already in the log. The id is
        bound to this plan unless the caller passes its own `key`."""
        ev_id = _sha([plan_hash, op, ev["kind"], events.canonical(ev["payload"])] if key is None else key)[:32]
        if ev_id in existing:
            return False
        existing.add(ev_id)
        out.events.append({**ev, "id": ev_id, "at": at})
        return True

    def emit(op: str, kind: str, subject: str, actor: str, payload: dict[str, Any]) -> None:
        add_event(events.make_event(kind, subject, actor, payload), op)

    def check(op: str, step: Any, subject: str, result: str, **extra: Any) -> None:
        emit(op, "check", subject, SYSTEM_ACTOR, {"step": _safe_step(step), "result": result, **extra})

    def reject(op: str, step: Any, subject: Any, reasons: list[str], signoff_id: Any = None,
               ident: str | None = None) -> None:
        """Log a rejection once per (document, reasons), not once per plan: a bad message that stays in the
        mailbox is read again every day and must not add a line each time. `ident` identifies a document
        that has no usable sign-off id (the hash of its content)."""
        known = subject if isinstance(subject, str) and subject in subjects else PROGRAMME
        sid = _safe_sid(signoff_id)
        payload = {"step": _safe_step(step), "result": "rejected", "reasons": reasons, "signoff_id": sid}
        who = sid or ident
        key = None if who is None else ["rejected", who, payload["step"], known, sorted(reasons)]
        add_event(events.make_event("check", known, SYSTEM_ACTOR, payload), op, key)
        out.rejected.append(f"{sid or '<no id>'}: {'; '.join(reasons)}")

    by_id: dict[str, list[dict[str, Any]]] = {}
    for r in receipt["results"]:
        by_id.setdefault(r["op_id"], []).append(r)

    for op in plan["ops"]:
        oid = op["op_id"]
        subject = op["subject"] or PROGRAMME
        found = by_id.get(oid, [])
        if not found:
            check(oid, op["step"], subject, "missing", op_id=oid)
            continue
        if len(found) > 1:
            check(oid, op["step"], subject, "error", op_id=oid)
            continue
        r = found[0]
        if r["status"] != "ok":
            check(oid, op["step"], subject, r["status"], op_id=oid)  # driver error text is not stored
        elif op["op"] == "site.library":
            exists = r["data"].get("exists") is True
            check(oid, op["step"], subject, "ok" if exists else "not_found", op_id=oid)
        elif op["op"] == "mail.sent":
            _notice(op, r["data"], subject, owner_email, notice_version, now_dt, check, reject, emit)
        elif op["op"] == "mail.tagged":
            _tagged(op, r["data"], step_defs, subjects, registrations, open_set, identities, readers,
                    templates, seen, check, reject, add_event, out)
            if isinstance(r["data"].get("messages", []), list):
                out.mailbox_read_at = max(run_dt, out.mailbox_read_at or run_dt)
        elif op["op"] == "file.get":
            reject(oid, op["step"], op["subject"], [LIBRARY_CHANNEL_DISABLED])
        else:
            check(oid, op["step"], subject, "error", op_id=oid)
    return out


def _ident(obj: Any) -> str | None:
    """Hash identifying a document that cannot name itself; None when it cannot be serialised."""
    try:
        return _sha(obj)
    except (TypeError, ValueError):
        return None


def _decode_attachment(att: Mapping[str, Any]) -> Any:
    """The attachment text: `content` as given, or `content_base64` decoded (strict base64, UTF-8)."""
    if "content_base64" not in att:
        return att.get("content")
    raw = att["content_base64"]
    if not isinstance(raw, str):
        raise ValueError("content_base64 is not a string")
    try:
        return base64.b64decode(raw.encode("ascii"), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeError) as exc:
        raise ValueError("content_base64 is not base64 of UTF-8 text") from exc


def _notice(op, data, subject, owner_email, notice_version, now_dt, check, reject, emit) -> None:
    """Complete notice-sent only on a message the owner sent to the recipient, with the tag, in the window."""
    oid, args = op["op_id"], op["args"]
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        check(oid, op["step"], subject, "error", op_id=oid)
        return
    stamps: list[datetime] = []
    try:
        since = _dt(args["since"])
        want_to = str(args["to"]).strip().lower()
        tag = str(args["tag"])
        owner = owner_email.strip().lower()
    except (KeyError, ValueError, TypeError, AttributeError):
        check(oid, op["step"], subject, "error", op_id=oid)
        return
    for m in messages:
        try:
            if not isinstance(m, Mapping):
                raise TypeError("message")
            sender, to, subj = m.get("sender"), m.get("to"), m.get("subject")
            if not (isinstance(sender, str) and isinstance(to, list) and isinstance(subj, str)):
                continue  # not a message this evidence can use
            sent = _dt(m.get("sentDateTime"))
        except Exception:  # noqa: BLE001 - a bad item is a rejected check, never an abort
            reject(oid, op["step"], op["subject"], ["malformed message"], ident=_ident(m))
            continue
        if not _SMTP_RE.match(sender):
            reject(oid, op["step"], op["subject"], ["sender is not an SMTP address"], ident=_ident(m))
            continue
        recipients = {t.strip().lower() for t in to if isinstance(t, str)}
        if sender.strip().lower() == owner and want_to in recipients and tag in subj and since <= sent <= now_dt:
            stamps.append(sent)
    if not stamps:
        check(oid, op["step"], subject, "not_found", op_id=oid)
        return
    if op["subject"] is None:
        check(oid, op["step"], subject, "error", op_id=oid)
        return
    given_on = min(stamps).date().isoformat()
    payload = {"step": op["step"], "notice_version": notice_version, "given_on": given_on, "op_id": oid}
    variant = _NOTICE_TAG_RE.match(tag)  # the variant the plan asked for; a tag of another shape leaves it out
    if variant:
        payload["notice_variant"] = variant.group(1)
    emit(oid, "notice", op["subject"], SYSTEM_ACTOR, payload)


def _tagged(op, data, step_defs, subjects, registrations, open_set, identities, readers, templates, seen,
            check, reject, add_event, out) -> None:
    oid = op["op_id"]
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        check(oid, op["step"], PROGRAMME, "error", op_id=oid)
        return
    for m in messages:
        if not isinstance(m, Mapping):
            reject(oid, None, None, ["malformed message"], ident=_ident(m))
            continue
        subject_line = m.get("subject")
        if not (isinstance(subject_line, str) and SIGNOFF_SUBJECT_TAG in subject_line):
            continue  # other mail in the mailbox, or a message that cannot be a sign-off
        sender, attachments = m.get("sender"), m.get("attachments", [])
        if not isinstance(sender, str) or not isinstance(attachments, list):
            reject(oid, None, None, ["malformed message"], ident=_ident(m))
            continue
        if not _SMTP_RE.match(sender):
            reject(oid, None, None, ["sender is not an SMTP address"], ident=_ident(m))
            continue
        if not any(isinstance(a, Mapping) and isinstance(a.get("name"), str) and a["name"].lower().endswith(".json")
                   for a in attachments):
            # Mailed without its file (2026-10-27 pilot). The id in the subject, else sender and subject, identify it, so
            # the Sent Items and Inbox copies, and the same message read again tomorrow, are flagged once.
            tagged = _SIGNOFF_SUBJECT_ID_RE.search(subject_line)
            reject(oid, None, None, [NO_SIGNOFF_FILE], tagged.group(1) if tagged else None,
                   ident=_ident({"sender": sender, "subject": subject_line}))
            continue
        for att in attachments:
            try:
                if not isinstance(att, Mapping) or not isinstance(att.get("name"), str):
                    raise TypeError("attachment")
                if not att["name"].lower().endswith(".json"):
                    continue
                content = _decode_attachment(att)
            except ValueError:
                reject(oid, None, None, ["attachment is not valid base64 UTF-8"], ident=_ident(att))
                continue
            except Exception:  # noqa: BLE001
                reject(oid, None, None, ["malformed attachment"], ident=_ident(att))
                continue
            try:
                _signoff(oid, content, sender, step_defs, subjects, registrations, open_set, identities,
                         readers, templates, seen, reject, add_event, out)
            except Exception:  # noqa: BLE001
                reject(oid, None, None, ["malformed attachment"], ident=_ident(att))


def _signoff(oid, content, sender, step_defs, subjects, registrations, open_set, identities, readers,
             templates, seen, reject_with, add_event, out) -> None:
    current_input, current_rows, content_check, taken, opened_on, now_dt, decided, revocable = readers
    ident = _ident(content)

    def reject(op, step, subject, reasons, sid=None):
        reject_with(op, step, subject, reasons, sid, ident)

    try:
        doc = json.loads(content)
    except (TypeError, ValueError):
        reject(oid, None, None, ["not JSON"])
        return
    if not isinstance(doc, dict):
        reject(oid, None, None, ["not a JSON object"])
        return
    if doc.get("schema") == REQUEST_FORM:
        out.requests.append((doc, sender))
        return
    step = doc.get("step") if isinstance(doc.get("step"), str) else None
    subject = doc.get("subject_uri") if isinstance(doc.get("subject_uri"), str) else None
    sid = doc.get("id") if isinstance(doc.get("id"), str) else None
    if step == AUDITION_STEP:
        out.auditions.append((doc, sender))  # auditions stay out of the log (decisions 0025, 0031)
        return
    if sid is not None and sid in seen:
        out.duplicates.append(doc)
        return  # duplicate: a no-op, not a rejection
    step_def = step_defs.get(step) if step is not None else None
    if step_def is None or subject is None:
        reject(oid, step, subject, ["unknown step or no subject"], sid)
        return
    if step_def["type"] != "human":
        reject(oid, step, subject, ["step does not take sign-offs"], sid)
        return
    info = subjects.get(subject)
    if info is None:
        reject(oid, step, subject, ["unknown subject"], sid)
        return
    if info.get("kind") != step_def["subject"]:
        reject(oid, step, subject, ["subject kind does not match step"], sid)
        return
    revoking = doc.get("decision") == REVOKE
    if revoking and (step, subject) not in revocable:
        reject(oid, step, subject, ["nothing to revoke: the step has no approval in force that may be revoked"], sid)
        return
    if not revoking and (step, subject) not in open_set:
        reject(oid, step, subject, ["step not open"], sid)
        return
    cur = current_input(step, subject)
    if cur is None:
        reject(oid, step, subject, ["no current input for step"], sid)
        return
    expected = None
    expected_set = None
    if step_def.get("signer") is not None:
        # The child subject names its signers (decision 0012); each may sign once.
        expected_set = signoff.allowed_signers(step_def, info)
        if not expected_set:
            reject(oid, step, subject, ["no expected signer"], sid)
            return
        if doc.get("signer") in taken.get((step, subject), ()):
            reject(oid, step, subject, ["signer has already signed this step"], sid)
            return
    elif step_def["role"] in signoff.SUBJECT_BOUND_ROLES:
        expected = signoff.expected_signer_for(step_def, subject, registrations.get(subject))
        if expected is None:
            reject(oid, step, subject, ["no expected signer"], sid)
            return
    res = signoff.accept(
        doc,
        current_input_sha256=cur,
        sender_email=sender,
        identities=identities,
        step_role=step_def["role"],
        expected_signer=expected,
        expected_signers=expected_set,
        seen_ids=seen,
        opened_on=opened_on(step, subject) if opened_on is not None else None,
        now=now_dt,
    )
    if res.duplicate:
        out.duplicates.append(doc)
        return
    reasons = list(res.reasons)
    if res.accepted:
        if doc["page_template_sha256"] not in templates:
            reasons.append("unknown page template")
        rows = current_rows(step, subject) if step in signoff.BATCH_STEPS else None
        reasons += signoff.content_reasons(doc, rows)
        if content_check is not None:
            reasons += content_check(doc) if doc.get("decision") in APPROVING else []
        if step in signoff.SINGLE_DECISION_STEPS and doc.get("decision") in APPROVING \
                and decided.get((step, subject)) == doc.get("input_sha256") and signoff.ALREADY_DECIDED not in reasons:
            reasons.append(signoff.ALREADY_DECIDED)  # finding 16: a second decision in one receipt; the first stands
    if reasons:
        reject(oid, step, subject, reasons, sid)
        return
    if add_event(signoff.to_event(doc, sender), oid):
        out.private.append((f"signoffs/{doc['id']}.json", doc))
    seen.add(doc["id"])
    if revoking:
        revocable.discard((step, subject))  # one revocation per approval; a second in this receipt has nothing to revoke
    if doc["decision"] in APPROVING:
        taken.setdefault((step, subject), set()).add(doc["signer"])
        if step in signoff.SINGLE_DECISION_STEPS:
            decided[(step, subject)] = doc["input_sha256"]
