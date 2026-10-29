"""Sign-off ingest core: who may sign, is the sign-off current, and the event it becomes.

Pure and deterministic. A sign-off returned by a generated page is checked against the identities
of the private store (people list plus roster instructors); only references enter the event.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from jsonschema import Draft202012Validator

from . import events
from .standards import load_schema
from .workflow import APPROVING, REVOKE

Identity = dict[str, Any]  # {"uri": str, "roles": set[str]}

# Roles whose holder is fixed by the subject (decision 0003: references, not people lists):
# the instructor signs their own, the manager and partner lead come from the registration.
SUBJECT_BOUND_ROLES = frozenset({"instructor", "manager", "partner-lead"})

# Content rules on approving sign-offs. The page enforces them in the browser; ingest enforces them
# again because the document that arrives is whatever the sender attached.
DPIA_STEP = "tm:step/dpia-screening"
DPIA_STEPS = frozenset({DPIA_STEP, "tm:step/dpia-delta"})  # the base screening and an overlay's delta
DPIA_NOT_REQUIRED = "dpia-not-required"
BATCH_STEPS = frozenset({"tm:step/gap-list-approved", "tm:step/lead-observed-level", "tm:step/retention-approved",
                         "tm:step/assignments-approved", "tm:step/levels-approved"})
CLEARER_ROLE = "clearer"
# Steps decided once on a given set of inputs (integration review finding 16): the first accepted approving sign-off stands,
# and a second one on the same inputs, in the same receipt (the bridge) or a later one (`flows.content_reasons`), is refused.
SINGLE_DECISION_STEPS = frozenset({"tm:step/bench-decision", "tm:step/override-decision", "tm:step/appeal-decision",
                                   "tm:step/head-resolves", "tm:step/recalibration-exercise",
                                   "tm:step/levels-decided"})
ALREADY_DECIDED = "this step was already decided on these inputs; the first accepted decision stands"


def already_decided(signoffs: Iterable[Mapping[str, Any]], step: Any, subject: Any, input_sha: Any) -> bool:
    """True when the latest approving sign-off of a single-decision `step` on `subject` among `signoffs` (events, in log
    order) covered `input_sha` (the hash of the inputs a page showed). Only the latest counts: inputs that change and come
    back (A, B, A) may be decided again, as `bind: input` reopens the step for them."""
    if step not in SINGLE_DECISION_STEPS:
        return False
    latest = [e for e in signoffs if e.get("kind") == "signoff" and e.get("subject_uri") == subject
              and e["payload"].get("step") == step and e["payload"].get("decision") in APPROVING]
    return bool(latest) and latest[-1]["payload"].get("input_sha256") == input_sha


def input_sha256(obj: Any) -> str:
    """SHA-256 of the canonical JSON of the inputs a page showed."""
    return hashlib.sha256(events.canonical(obj).encode("utf-8")).hexdigest()


def short_sha(obj: Any, n: int = 32) -> str:
    """The first `n` hex digits of `input_sha256(obj)`: the id of an event derived from its content."""
    return input_sha256(obj)[:n]


def identities(
    people_rows: Iterable[Mapping[str, Any]], roster_doc: Mapping[str, Any] | None,
    clearers: Collection[str] = (),
) -> dict[str, list[Identity]]:
    """Map lower-cased email to the identities that use it: [{"uri", "roles"}, ...].

    Roster instructors get the `instructor` role, and `clearer` when their URI is in `clearers` (the instructors whose
    latest level is clearer; the caller reads the log). A people-list person with an `instructor` field (decision 0012)
    also appears as that instructor, under their own mailbox, with their roles plus `instructor` (and `clearer` for a
    clearer): the explicit mapping is the only link between the two lists. One mailbox may belong to a person in the people
    list and to a roster instructor (a coordinator who also teaches): both entries are kept and `accept` picks the ones
    the sign-off names. Two rows of the same source sharing an email stay an error.

    A mapped person's `clearer` role is kept only while their instructor is in `clearers` (integration review finding 5):
    the level decides who is a clearer, so the people list cannot grant it by itself, under either URI.
    """
    out: dict[str, list[Identity]] = {}
    source: dict[tuple[str, str], str] = {}

    def add(email: str, uri: str, roles: set[str], kind: str) -> None:
        key = email.strip().lower()
        if (key, kind) in source:
            raise ValueError(f"duplicate email within the {kind} list: {uri} and {source[(key, kind)]}")
        source[(key, kind)] = uri
        out.setdefault(key, []).append({"uri": uri, "roles": roles})

    def instructor_roles(uri: str, extra: Collection[str] = ()) -> set[str]:
        return {*extra, "instructor", *([CLEARER_ROLE] if uri in clearers else [])}

    for row in people_rows:
        roles = set(row["roles"])
        mapped = row.get("instructor") if isinstance(row.get("instructor"), str) else None
        if mapped is not None and mapped not in clearers:
            # Clearer status comes from the instructor's level (a level_change or the registration), never from the
            # people list alone: a mapped person's `clearer` role grants nothing while their instructor is not a clearer.
            roles.discard(CLEARER_ROLE)
        add(row["email"], row["person"], roles, "people")
        if mapped is not None:
            add(row["email"], mapped, instructor_roles(mapped, roles), "mapped")
    for inst in (roster_doc or {}).get("instructors", []):
        add(inst["identity"]["email"], inst["instructor"], instructor_roles(inst["instructor"]), "roster")
    return out


SIGNER_ATTRS = {"attrs.observer": "observer", "attrs.instructor": "instructor", "attrs.observers": "observers"}


def allowed_signers(step_def: Mapping[str, Any], info: Mapping[str, Any] | None) -> set[str] | None:
    """The URIs that may sign a step with a `signer` (decision 0012), read from the attrs of the child subject
    (`info`, the engine's view of it): the one assigned observer, the one instructor, or every listed observer. None for
    a step without `signer`; an empty set when the subject lacks the attribute or it is not made of URI strings (nobody
    may sign, which the caller rejects as "no expected signer")."""
    attr = SIGNER_ATTRS.get(step_def.get("signer"))
    if attr is None:
        return None
    value = (info or {}).get(attr)
    values = value if isinstance(value, list) else [value]
    return {v for v in values if isinstance(v, str) and v}


def expected_signer_for(
    step_def: Mapping[str, Any], subject_uri: str, registration_payload: Any, info: Mapping[str, Any] | None = None
) -> str | None:
    """Who must sign this step for this subject; None when the role is not subject-bound or the data is missing.

    With a `signer` on the step, the one signer named by the subject's attrs (`info`); None when it names several
    (`attrs.observers`: see `allowed_signers`) or none."""
    if step_def.get("signer") is not None:
        found = allowed_signers(step_def, info) or set()
        return next(iter(found)) if len(found) == 1 else None
    role = step_def.get("role")
    if role == "instructor":
        return subject_uri
    key = {"manager": "manager", "partner-lead": "nominated_by"}.get(role)
    if key is None or not isinstance(registration_payload, Mapping):
        return None
    engagement = registration_payload.get("engagement")
    if not isinstance(engagement, Mapping):
        return None
    who = engagement.get(key)
    return who if isinstance(who, str) and who else None


def _schema_reasons(signoff: Mapping[str, Any]) -> list[str]:
    """Schema failures as `path: keyword`, never the validator message (it quotes the offending value)."""
    validator = Draft202012Validator(load_schema("signoff.schema.json"))
    found = {f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.validator}" for e in validator.iter_errors(dict(signoff))}
    return sorted(found)


@dataclass
class Result:
    accepted: bool = False
    duplicate: bool = False
    reasons: list[str] = field(default_factory=list)


CLOCK_SKEW = timedelta(days=1)  # how far after the ingest clock a `signed_at` may lie before it is refused


def _utc(stamp: datetime) -> datetime:
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def signed_at_reasons(signed_at: str, opened_on: date | None, now: datetime | None) -> list[str]:
    """Why a `signed_at` cannot be believed. The signer chooses it, and it dates the evidence (an observation's session,
    the day a clearer was calibrated, a clearance's issue), so it is held to what the system knows: not before the day the
    step opened (`opened_on`, a UTC day; None means unknown and sets no lower bound) and not more than CLOCK_SKEW after
    `now` (None sets no upper bound). A naive stamp counts as UTC. An unreadable stamp is left to the caller."""
    try:
        stamp = _utc(datetime.fromisoformat(signed_at.replace("Z", "+00:00")))
    except (ValueError, AttributeError):
        return []
    reasons = []
    if opened_on is not None and stamp.date() < opened_on:
        reasons.append("signed_at is before the step opened")
    if now is not None and stamp > _utc(now) + CLOCK_SKEW:
        reasons.append("signed_at is in the future")
    return reasons


def accept(
    signoff: Mapping[str, Any],
    *,
    current_input_sha256: str,
    sender_email: str,
    identities: Mapping[str, list[Identity]],
    step_role: str,
    expected_signer: str | None = None,
    expected_signers: Collection[str] | None = None,
    seen_ids: Iterable[str] = frozenset(),
    opened_on: date | None = None,
    now: datetime | None = None,
) -> Result:
    """Decide whether a returned sign-off counts. Rejections carry the reason text; a repeat id is a no-op.

    `expected_signer` is the one URI that must sign; `expected_signers` is a set of which the signer must be one (a step
    whose `signer` names the observers of an exercise). The signer must also be the sender's identity and hold `step_role`.
    `opened_on` and `now` bound `signed_at` (`signed_at_reasons`); the caller derives the day from the engine."""
    sid = signoff.get("id")
    if isinstance(sid, str) and sid in set(seen_ids):
        return Result(accepted=False, duplicate=True, reasons=[])
    schema_errors = _schema_reasons(signoff)
    if schema_errors:
        return Result(reasons=schema_errors)
    try:
        datetime.fromisoformat(signoff["signed_at"].replace("Z", "+00:00"))
    except ValueError:
        return Result(reasons=["signed_at is not a valid date-time"])
    reasons: list[str] = signed_at_reasons(signoff["signed_at"], opened_on, now)
    if signoff["input_sha256"] != current_input_sha256:
        reasons.append(
            f"stale: sign-off covers input {signoff['input_sha256'][:12]}, current input is {current_input_sha256[:12]}"
        )
    entries = identities.get(sender_email.strip().lower()) if isinstance(sender_email, str) else None
    if not entries:
        reasons.append("unknown sender")
    else:
        named = [e for e in entries if e["uri"] == signoff["signer"]]  # one mailbox can reach one URI by two lists
        if not named:
            reasons.append("sender is not the named signer")
        elif not any(step_role in e["roles"] for e in named):
            reasons.append(f"signer lacks role {step_role}")
    if expected_signer is not None and signoff["signer"] != expected_signer:
        reasons.append(f"signer is not the expected {expected_signer}")
    if expected_signers is not None and signoff["signer"] not in set(expected_signers):
        reasons.append("signer is not an expected signer of this subject")
    return Result(accepted=not reasons, reasons=reasons)


def content_reasons(signoff: Mapping[str, Any], expected_rows: Collection[str] | None = None) -> list[str]:
    """Reasons an otherwise valid approving sign-off still cannot count, from its own `fields`.

    - DPIA screening and an overlay's DPIA delta: only `dpo-decision: dpia-not-required` completes it; a required or undecided DPIA
      must not unlock the steps that follow.
    - Batch approvals (gap list, level change): `fields.rows` must decide exactly the rows the page
      showed (`expected_rows`, re-derived at ingest; None means unknown, which rejects) and every
      decision must be `approve`.
    - A revocation (decision 0019) needs a written `fields.reason`.
    A sign-off with another decision is not checked: it never completes a step.
    """
    fields = signoff.get("fields")
    fields = fields if isinstance(fields, Mapping) else {}
    if signoff.get("decision") == REVOKE:
        reason = fields.get("reason")
        return [] if isinstance(reason, str) and reason.strip() else ["reason: a written reason is required to revoke"]
    if signoff.get("decision") not in APPROVING:
        return []
    step = signoff.get("step")
    if step in DPIA_STEPS and fields.get("dpo-decision") != DPIA_NOT_REQUIRED:
        return ["DPIA required or undecided"]
    if step in BATCH_STEPS:
        rows = fields.get("rows")
        if not isinstance(rows, Mapping) or any(v != "approve" for v in rows.values()):
            return ["batch rows not all approved"]
        if expected_rows is None or set(rows) != set(expected_rows):
            return ["batch rows do not match the rows the page showed"]
    return []


def fields_sha256(signoff: Mapping[str, Any]) -> str:
    """The hash of a sign-off's `fields` that the log keeps, salted with the sign-off id. A bare hash of the fields would
    be the same for two observers who answered alike, and an unsalted hash lets anyone with the log test a guess at what
    a blind scorer entered; the id (unique per sign-off, and not a secret) makes each logged hash its own."""
    return input_sha256({"id": signoff["id"], "fields": signoff["fields"]})


def to_event(signoff: Mapping[str, Any], sender_email: str) -> dict[str, Any]:
    """The `signoff` event for an accepted sign-off. `sender_email` is already verified by `accept`
    and is deliberately not stored, and neither are the free-text `fields`: only their salted hash
    (`fields_sha256`) enters the log, the full document goes to the private store (decision 0003)."""
    payload = {
        "step": signoff["step"],
        "decision": signoff["decision"],
        "fields_sha256": fields_sha256(signoff),
        "input_sha256": signoff["input_sha256"],
        "signoff_id": signoff["id"],
        "page_template_sha256": signoff["page_template_sha256"],
        "signed_at": signoff["signed_at"],
    }
    return events.make_event("signoff", signoff["subject_uri"], signoff["signer"], payload)
