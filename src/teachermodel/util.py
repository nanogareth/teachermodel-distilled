"""Small helpers shared across modules. No imports from the package, so any module can use them."""

from __future__ import annotations

import html
from datetime import date, datetime
from pathlib import Path
from typing import Any


def slug(uri: str) -> str:
    """The part of a `tm:` URI after its kind: `tm:instructor/ana` -> `ana`."""
    return uri.split("/", 1)[1]


def parse_day(value: Any) -> date | None:
    """The date at the start of an ISO date or timestamp string, or None if `value` is not one."""
    try:
        return date.fromisoformat(value[:10]) if isinstance(value, str) else None
    except ValueError:
        return None


def iso_seconds(now: Any) -> str:
    return now.isoformat(timespec="seconds") if isinstance(now, datetime) else str(now)


def esc(value: Any) -> str:
    """HTML-escape a value for text or an attribute; None is empty."""
    return html.escape("" if value is None else str(value), quote=True)


def write_if_changed(path: Path, data: bytes) -> bool:
    """Write `data` to `path` unless it already holds exactly that. True if it wrote."""
    if path.is_file() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True
