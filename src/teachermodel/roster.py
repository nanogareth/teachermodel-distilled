"""Roster import format (tm:contract/roster@2): load and check a roster file.

A filled roster holds personal data, so live files live in the private store (decision 0006).
Checking reads the file only; splitting identities from references is the phase 3 importer.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .standards import ROOT, load_standards, validate


class _StringDates(yaml.SafeLoader):
    """SafeLoader that keeps dates as ISO strings, so they validate as JSON Schema strings."""


_StringDates.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.load(fh, Loader=_StringDates)


# Domains that can never belong to a real mailbox: RFC 2606 (example.com/.net/.org and the .example, .test and
# .invalid top-level names) and RFC 6761 (.localhost).
RESERVED_DOMAINS = ("example.com", "example.net", "example.org")
RESERVED_TLDS = ("example", "test", "invalid", "localhost")


def is_reserved_email(email: Any) -> bool:
    if not isinstance(email, str) or email.count("@") != 1:
        return False
    domain = email.rsplit("@", 1)[1].strip().rstrip(".").lower()
    return (domain in RESERVED_DOMAINS or any(domain.endswith("." + d) for d in RESERVED_DOMAINS)
            or domain.rsplit(".", 1)[-1] in RESERVED_TLDS)


def pilot_refusals(doc: Any) -> list[str]:
    """Decision 0016: a pilot store holds generated instructors only, and a generated instructor's email is on a
    reserved domain. One reason per other instructor; the reason names the domain, never the address."""
    rows = doc.get("instructors") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return ["the roster has no instructors list, so it cannot be shown to be generated"]
    out = []
    for n, row in enumerate(rows):
        row = row if isinstance(row, dict) else {}
        who = row.get("instructor") if isinstance(row.get("instructor"), str) else f"row {n + 1}"
        identity = row.get("identity")
        email = identity.get("email") if isinstance(identity, dict) else None
        if not is_reserved_email(email):
            domain = email.rsplit("@", 1)[1] if isinstance(email, str) and "@" in email else "no email"
            out.append(f"{who}: {domain} is not a reserved domain")
    return out


def _date(value: str, where: str, errors: list[str]) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{where}: {value} is not a calendar date")
        return None


def check_roster(doc: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Schema-validate a roster and check what the schema cannot: levels, uniqueness, dates."""
    errors = validate(doc, "roster.schema.json", root)
    if errors:
        return errors
    levels = load_standards(root)["framework"]["levels"]
    _date(doc["as_of"], "as_of", errors)
    ids: set[str] = set()
    emails: set[str] = set()
    for n, row in enumerate(doc["instructors"]):
        where = f"instructors/{n} ({row['instructor']})"
        if row["instructor"] in ids:
            errors.append(f"{where}: duplicate instructor id")
        ids.add(row["instructor"])
        email = row["identity"]["email"].lower()
        if email in emails:
            errors.append(f"{where}: duplicate email")
        emails.add(email)
        if row["level"] not in levels:
            errors.append(f"{where}: level {row['level']} not in framework levels {levels}")
        slug = row["instructor"].split("/", 1)[1]
        tokens = [t for t in re.split(r"[^a-z]+", row["identity"]["name"].lower()) if len(t) >= 3]
        if any(t in slug for t in tokens):
            errors.append(f"{where}: id contains part of the name; ids must be meaningless")
        eng = row["engagement"]
        start = _date(eng["start"], f"{where}/engagement/start", errors)
        end = _date(eng["end"], f"{where}/engagement/end", errors) if "end" in eng else None
        if start and end and end < start:
            errors.append(f"{where}: engagement ends before it starts")
        if "notice" in row:
            _date(row["notice"]["given_on"], f"{where}/notice/given_on", errors)
        units = [d["unit"] for d in row.get("delivers", [])]
        if len(units) != len(set(units)):
            errors.append(f"{where}: a unit is listed twice in delivers")
    return errors
