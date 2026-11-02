"""Feeds from the lab systems: the weekly release status and results received per delivery (decision 0028).

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


def problems(doc: Any, root: Path = ROOT) -> list[str]:
    """Every problem with a feed file, in path order; [] when it is good."""
    schema = doc.get("schema") if isinstance(doc, dict) else None
    if schema not in FEEDS:
        return [f"not a feed: schema is {schema!r}, expected one of {', '.join(sorted(FEEDS))}"]
    errors = sorted(Draft202012Validator(load_schema(FEEDS[schema][0], root)).iter_errors(doc),
                    key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or 'the file'}: {e.message}" for e in errors]


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
