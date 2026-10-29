"""Private store resolution and the people list (decision 0006).

The private store holds names, emails and the live event log, so it must sit outside the git
working tree. Resolution is explicit-path, then TEACHERMODEL_PRIVATE_DIR, otherwise an error.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .standards import ROOT, validate

ENV_VAR = "TEACHERMODEL_PRIVATE_DIR"

# Spec roles (v0.2, "Users and roles"; manager and partner lead split) plus the setup roles
# programme-owner, it, dpo (workflow automation design, section 7) and legal (privacy-jurisdictions design,
# section 2). Slugs are stable.
ROLES: tuple[str, ...] = (
    "head-of-training",
    "clearer",
    "coach",
    "observer-in-training",
    "instructor",
    "manager",  # engineering manager (SME engineers)
    "partner-lead",  # nominates partner instructors
    "coordinator",
    "programme-owner",  # owns the private store and setup sign-offs (0006)
    "it",
    "dpo",
    "legal",  # verifies the privacy profiles (privacy-jurisdictions design, section 2)
)


class ConfigError(Exception):
    """Configuration is missing or unsafe; the message says how to fix it."""


def assert_outside_repo(path: Path | str) -> Path:
    """Refuse a path inside a git working tree. Walks the path and its parents for `.git`."""
    resolved = Path(path).resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ".git").exists():  # a directory, or a file in worktrees and submodules
            raise ConfigError(
                f"{resolved} is inside the git working tree at {candidate}; the private store "
                "must live outside any repository (decision 0006)"
            )
    return resolved


def private_dir(explicit: Path | str | None = None) -> Path:
    """Resolve the private store: explicit path, else $TEACHERMODEL_PRIVATE_DIR, else error."""
    if explicit is not None:
        if not str(explicit).strip():
            raise ConfigError("empty --private-dir; give the synced library path (decision 0006)")
        chosen = Path(explicit)
    else:
        env = os.environ.get(ENV_VAR, "").strip()
        if not env:
            raise ConfigError(
                f"no private store: pass --private-dir or set {ENV_VAR} to the synced SharePoint "
                "library path (docs/decisions/0006-private-store-location-and-backup.md)"
            )
        chosen = Path(env)
    return _assert_not_appdata(assert_outside_repo(chosen))


def _assert_not_appdata(path: Path) -> Path:
    """0006: never under %LOCALAPPDATA%/%APPDATA% (packaged apps redirect writes there)."""
    for var in ("LOCALAPPDATA", "APPDATA"):
        root = os.environ.get(var, "").strip()
        if root and path.is_relative_to(Path(root).resolve()):
            raise ConfigError(f"{path} is under %{var}%; packaged apps redirect writes there (decision 0006)")
    return path


ONEDRIVE_VARS = ("OneDriveCommercial", "OneDriveConsumer", "OneDrive")


def in_personal_onedrive(path: Path | str) -> bool:
    """True when `path` is inside the user's own OneDrive folder, which Windows names in %OneDriveCommercial%,
    %OneDriveConsumer% and %OneDrive%. A synced SharePoint library is not: it syncs to its own folder beside them.
    Decision 0016: such a store is a pilot store."""
    resolved = Path(path).resolve()
    for var in ONEDRIVE_VARS:
        root = os.environ.get(var, "").strip()
        if root and resolved.is_relative_to(Path(root).resolve()):
            return True
    return False


def people(private: Path | str) -> list[dict[str, Any]]:
    """Load identities/people.yaml: [{person, name, email, roles, instructor?, coaches?}], validated. `coaches` (the
    instructors a coach coaches) is only for a row holding the coach role; each is a tm:instructor URI."""
    path = Path(private) / "identities" / "people.yaml"
    if not path.is_file():
        raise ConfigError(f"missing {path} (people list; decision 0006 layout)")
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    errors = validate(doc, "people.schema.json", ROOT) if isinstance(doc, dict) else ["<root>: not a mapping"]
    if not errors:
        ids: set[str] = set()
        emails: set[str] = set()
        mapped: set[str] = set()
        for n, row in enumerate(doc["people"]):
            where = f"people/{n} ({row['person']})"
            if row["person"] in ids:
                errors.append(f"{where}: duplicate person id")
            ids.add(row["person"])
            email = row["email"].lower()
            if email in emails:
                errors.append(f"{where}: duplicate email")
            emails.add(email)
            if "instructor" in row:
                if row["instructor"] in mapped:
                    errors.append(f"{where}: {row['instructor']} is mapped by another person")
                mapped.add(row["instructor"])
            if "coaches" in row and "coach" not in row["roles"]:
                errors.append(f"{where}: coaches is only for a person holding the coach role")
            for role in row["roles"]:
                if role not in ROLES:
                    errors.append(f"{where}: unknown role {role!r}; known roles are {list(ROLES)}")
    if errors:
        raise ConfigError(f"{path}: " + "; ".join(errors))
    return list(doc["people"])
