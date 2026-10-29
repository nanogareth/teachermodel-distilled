"""Append-only event log (actuals data class), hub events/ shape.

Events carry references only. Personal data (names, evidence notes, recording links) lives in the
private store outside git and is referenced by key from the payload.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .standards import validate
from .util import slug as _slug
from .workflow import candidate_uri

# Event kinds whose payload has a contract of its own, and the schema (under contracts/) that checks it.
PAYLOAD_SCHEMAS = {
    "observation": "observation.schema.json",
    "dry_run": "dry-run.schema.json",
    "calibration": "calibration.schema.json",
    "clearance": "clearance.schema.json",
    "subject": "subject.schema.json",
    # increment 3 (decision 0014)
    "audit": "audit.schema.json",
    "coaching_cycle": "coaching-cycle.schema.json",
    "cpd": "cpd.schema.json",
    "outcome": "outcome.schema.json",
    "bench_decision": "bench-decision.schema.json",
}
_CHILD_URI = {
    "assignment": re.compile(r"^tm:assignment/[0-9a-f]{16}$"),
    "exercise": re.compile(r"^tm:exercise/[0-9a-f]{16}$"),
    "override": re.compile(r"^tm:override/[0-9a-f]{16}$"),
    "appeal": re.compile(r"^tm:appeal/[0-9a-f]{16}$"),
    "recalibration": re.compile(r"^tm:recalibration/[0-9a-f]{16}$"),
}


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def receipt(kind: str, subject_uri: str, actor: str, payload: dict[str, Any]) -> str:
    body = canonical({"kind": kind, "subject_uri": subject_uri, "actor": actor, "payload": payload})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def make_event(
    kind: str,
    subject_uri: str,
    actor: str,
    payload: dict[str, Any],
    *,
    id: str | None = None,
    at: str | None = None,
) -> dict[str, Any]:
    return {
        "id": id or uuid.uuid4().hex,
        "at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "subject_uri": subject_uri,
        "actor": actor,
        "payload": payload,
        "receipt_sha256": receipt(kind, subject_uri, actor, payload),
    }


class EventError(ValueError):
    pass


def check_event(event: dict[str, Any]) -> list[str]:
    errors = validate(event, "event.schema.json")
    if not errors:
        expected = receipt(event["kind"], event["subject_uri"], event["actor"], event["payload"])
        if expected != event["receipt_sha256"]:
            errors.append(f"event {event['id']}: receipt does not match payload")
    if not errors and event["kind"] in PAYLOAD_SCHEMAS:
        errors += [f"payload/{e}" for e in validate(event["payload"], PAYLOAD_SCHEMAS[event["kind"]])]
        if not errors and event["kind"] == "subject":
            errors += _subject_uri_errors(event)
    return errors


def _subject_uri_errors(event: dict[str, Any]) -> list[str]:
    """A subject event's subject_uri must fit its kind. A candidate's is derived from its attrs (decision 0011), and so is
    a cycle's (`tm:cycle/<instructor slug>--<number>`) and a sample's (`tm:sample/<quarter>--<observation id>`); a bench's
    is `tm:bench/<instructor slug>--<n>` with the slug of its instructor (decision 0014)."""
    kind, attrs, uri = event["payload"]["subject_kind"], event["payload"]["attrs"], event["subject_uri"]
    if kind == "candidate":
        want = candidate_uri(attrs["instructor"], attrs["unit"], attrs["mode"])
        return [] if uri == want else [f"subject_uri {uri!r} is not the candidate URI of its attrs ({want!r})"]
    if kind == "cycle":
        want = f"tm:cycle/{_slug(attrs['instructor'])}--{attrs['number']}"
        return [] if uri == want else [f"subject_uri {uri!r} is not the cycle URI of its attrs ({want!r})"]
    if kind == "sample":
        want = f"tm:sample/{attrs['quarter']}--{attrs['observation']}"
        return [] if uri == want else [f"subject_uri {uri!r} is not the sample URI of its attrs ({want!r})"]
    if kind == "bench":
        want = f"tm:bench/{_slug(attrs['instructor'])}--"
        ok = uri.startswith(want) and re.fullmatch(r"[1-9][0-9]*", uri[len(want):]) is not None
        return [] if ok else [f"subject_uri {uri!r} does not fit a bench of its instructor ({want}<n>)"]
    return [] if _CHILD_URI[kind].match(uri) else [f"subject_uri {uri!r} does not fit a {kind} (tm:{kind}/<16 hex>)"]


def append(path: Path, event: dict[str, Any]) -> None:
    """Append one event. The log is never rewritten; corrections are new events."""
    errors = check_event(event)
    if errors:
        raise EventError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(canonical(event) + "\n")


def read(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def verify(path: Path) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for n, event in enumerate(read(path), start=1):
        errors += [f"line {n}: {e}" for e in check_event(event)]
        if event.get("id") in seen:
            errors.append(f"line {n}: duplicate id {event['id']}")
        seen.add(event.get("id"))
    return errors
