"""Feeds: the weekly release status and results received (decision 0028); drafts, sessions and commands (0029).

    teachermodel import-feed <file>     check a feed file and keep it under inputs/
    feeds.drain_inbox(private)          what the daily job runs first: import every file dropped in inbox/

A feed is a small file another system writes: `tm:contract/release-status@1` (proving-ground's weekly release check,
per lab, as counts) or `tm:contract/results-received@1` (the outcome exporter's dry run, results received and
unreadable per delivery, as counts). Like the schedule and bookings it is an input, never an event; unlike them it
holds no person, so it needs no retention entry. The latest file of each kind is kept; an older run never replaces a
newer one. A refusal lists every problem and writes nothing. Files dropped in `inbox/` move to `inbox/done/` when kept
and to `inbox/refused/` with a `.why.txt` beside them when not, so nothing is read twice and nothing is lost.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .standards import ROOT, load_schema

RELEASE = "tm:contract/release-status@1"
RECEIVED = "tm:contract/results-received@1"
FEEDS = {
    RELEASE: ("release-status.schema.json", Path("inputs") / "release-status.json", "run_at"),
    RECEIVED: ("results-received.schema.json", Path("inputs") / "results-received.json", "exported_at"),
}
# What comes back from the Claude buttons and the cards (decision 0029): many of each, kept one file per key under
# outbox/received/, so the Outbox page can show what has come back for each action.
DRAFT = "tm:contract/draft@1"
SESSION = "tm:contract/claude-session@1"
COMMAND = "tm:contract/command@1"
RETURNS = Path("outbox") / "received"
MANY = {
    DRAFT: ("draft.schema.json", RETURNS / "drafts", "drafted_at"),
    SESSION: ("claude-session.schema.json", RETURNS / "sessions", "ended_at"),
    COMMAND: ("command.schema.json", RETURNS / "commands", "at"),
}
INBOX = Path("inbox")


class FeedError(Exception):
    pass


@dataclass(frozen=True)
class Feed:
    schema: str
    path: Path
    at: str


def _read(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise FeedError(f"{Path(path).name}: not a feed (cannot read it as JSON: {exc.__class__.__name__})") from None


def _schema_problems(doc: Any, schema: dict[str, Any], prefix: str = "") -> list[str]:
    errors = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{prefix}{'/'.join(str(p) for p in e.absolute_path) or 'the file'}: {e.message}" for e in errors]


def _return_problems(doc: dict[str, Any], root: Path) -> list[str]:
    """A draft fits its button's schema; a session's every write ran only with a person's allow, on a declared tool."""
    from . import interventions

    buttons = {b["id"]: b for b in interventions.chains_doc(root).get("buttons") or []}
    if doc["schema"] == COMMAND:
        return []
    button = buttons.get(doc["button"])
    want = "draft" if doc["schema"] == DRAFT else "act"
    if button is None or button["kind"] != want:
        return [f"button: {doc['button']!r} is not a {'drafting' if want == 'draft' else 'acting'} button in "
                "standards/chains.yaml"]
    if doc["schema"] == DRAFT:
        return _schema_problems(doc["content"], load_schema(f"drafts/{doc['button']}.schema.json", root), "content/")
    out = []
    for n, call in enumerate(doc["calls"]):
        if call["tool"] not in (button.get("writes") or {}).get(call["server"], []):
            out.append(f"calls/{n}: {call['server']}.{call['tool']} is not a write this button declares")
        if call["result"] != "not-run" and call["decision"] != "allow":
            out.append(f"calls/{n}: a call ran without a person's allow")
        if call["decision"] == "deny" and call["result"] != "not-run":
            out.append(f"calls/{n}: a denied call must not have run")
    return out


def problems(doc: Any, root: Path = ROOT) -> list[str]:
    """Every problem with a feed file, in path order; [] when it is good."""
    schema = doc.get("schema") if isinstance(doc, dict) else None
    if schema not in FEEDS and schema not in MANY:
        return [f"not a feed: schema is {schema!r}, expected one of {', '.join(sorted({*FEEDS, *MANY}))}"]
    found = _schema_problems(doc, load_schema((FEEDS.get(schema) or MANY[schema])[0], root))
    return found or (_return_problems(doc, root) if schema in MANY else [])


def _key(doc: dict[str, Any]) -> str:
    if doc["schema"] == DRAFT:
        return doc["action_id"]
    if doc["schema"] == SESSION:
        return doc["session_id"]
    stamp = hashlib.sha256(f"{doc['at']}|{doc['choice']}|{doc['by']}".encode()).hexdigest()[:8]
    return f"{doc['action_id']}-{stamp}"


def returns(private: Path | str, schema: str) -> list[dict[str, Any]]:
    """Every kept draft, session record or command, in key order."""
    folder = Path(private) / MANY[schema][1]
    return [_read(p) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def load(private: Path | str, schema: str) -> dict[str, Any] | None:
    """The kept feed of this kind, or None when there is none."""
    path = Path(private) / FEEDS[schema][1]
    return _read(path) if path.exists() else None


def import_feed(private: Path | str, source: Path | str, root: Path = ROOT) -> Feed:
    """Check a feed file and keep it. Raises FeedError listing every problem; writes nothing then."""
    doc = _read(Path(source))
    if found := problems(doc, root):
        raise FeedError("\n".join(found))
    schema = doc["schema"]
    if schema in MANY:
        _, folder, stamp = MANY[schema]
        target = Path(private) / folder / f"{_key(doc)}.json"
        if target.exists() and target.read_bytes() != Path(source).read_bytes():
            kept = _read(target)
            if schema != DRAFT or str(kept[stamp]) >= str(doc[stamp]):
                raise FeedError(f"{target.name} was received already; a {schema.split('/')[-1]} is kept once"
                                + (" (a newer draft replaces an older one)" if schema == DRAFT else ""))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return Feed(schema, target, str(doc[stamp]))
    _, target, stamp = FEEDS[schema]
    target = Path(private) / target
    kept = load(private, schema)
    if kept and str(kept[stamp]) > str(doc[stamp]):
        raise FeedError(f"{stamp} {doc[stamp]} is older than the kept {kept[stamp]}: the newer one stays")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return Feed(schema, target, str(doc[stamp]))


def _move(path: Path, folder: Path) -> Path:
    """Move `path` into `folder`, never over a file already there (the same name dropped twice)."""
    folder.mkdir(exist_ok=True)
    target, n = folder / path.name, 1
    while target.exists():
        target, n = folder / f"{path.stem}.{n}{path.suffix}", n + 1
    shutil.move(path, target)
    return target


def drain_inbox(private: Path | str, root: Path = ROOT) -> list[str]:
    """Import every file in the store's inbox/, oldest name first; one line per file."""
    inbox = Path(private) / INBOX
    lines = []
    for path in sorted(p for p in inbox.glob("*") if p.is_file()) if inbox.is_dir() else []:
        try:
            got = import_feed(private, path, root)
        except FeedError as exc:
            aside = _move(path, inbox / "refused")
            aside.with_name(f"{aside.name}.why.txt").write_text(f"{exc}\n", encoding="utf-8", newline="\n")
            lines.append(f"{path.name}: refused: {str(exc).splitlines()[0]}")
            continue
        _move(path, inbox / "done")
        lines.append(f"{path.name}: kept as {got.path.relative_to(Path(private)).as_posix()} ({got.at})")
    return lines
