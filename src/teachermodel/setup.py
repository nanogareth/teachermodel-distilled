"""Setup workflow auto steps (tm:workflow/setup). Spec: docs/specs/2026-10-24-workflow-automation-design.md §7.

Each step takes the private dir, the event list, the settings and the time, writes its output under
`<private>/generated/` (or `identities/` for the roster import) and returns the events to append; it
never writes the log. A re-run whose output is unchanged returns `[]` (idempotent by output_sha256
against the latest `step` event). A step that cannot run yet returns one `check` event with
`result: blocked`, reported once until its reasons change.

Names and emails go only into private files (`identities/`, `.eml` drafts). Events hold tm: URIs,
step ids and hashes (decision 0003).
"""

from __future__ import annotations

import email.policy
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from string import Template
from typing import Any

import yaml

from . import events as ev
from . import mdlite, notice, privacy
from .citations import CitationError, Citer
from . import roster as roster_module
from . import signoff
from .config import ROLES, in_personal_onedrive
from .privacy import PrivacyError
from .records import bench_blocks
from .rules import BENCH_BLOCKS, Clearance, staffing_check
from .standards import ROOT, load_standards, load_yaml, memo, sha256_hex, validate
from .standards import sha256_hex as _sha
from . import workflow
from .workflow import PROGRAMME, SYSTEM_ACTOR, notice_variant
from .util import iso_seconds as _iso, slug as _slug, write_if_changed as _write

STEP_IT_REQUEST = "tm:step/it-request"
STEP_ROPA = "tm:step/ropa"
STEP_NOTICE_TEXT = "tm:step/notice-text"
STEP_NOTICE_APPROVED = "tm:step/notice-approved"
STEP_RETENTION_APPROVED = privacy.STEP_RETENTION_APPROVED
STEP_NOTICE_DRAFTS = "tm:step/notice-drafts"
STEP_ROSTER_IMPORT = "tm:step/roster-import"
STEP_GAP_LIST = "tm:step/gap-list"

SETTINGS_SCHEMA = "settings.schema.json"
IT_REQUEST_SUBJECT = "teachermodel private store request [tm-setup it-request]"
IDENTITIES = "identities/roster.yaml"

# What each role sees. The first seven rows are the "Sees" column of the spec role table
# (docs/specs/2026-10-23-instructor-development-spec-v0.2.md, Users and roles; the manager and
# partner lead share one row there). The setup roles come from decision 0006 (Access) and the
# workflow automation design §7, which the spec table does not cover.
# `source` is a citation (document, section[, paragraph]) for citations.Citer: a decision number or a path.
SPEC = "docs/specs/2026-10-23-instructor-development-spec-v0.2.md"
WORKFLOW_DESIGN = "docs/specs/2026-10-24-workflow-automation-design.md"
PRIVACY_DESIGN = "docs/specs/2026-10-24-privacy-jurisdictions-design.md"
_SPEC_ROLES = (SPEC, "Users and roles", 2)
ROLE_SEES: dict[str, dict[str, Any]] = {
    "head-of-training": {"label": "Head of training", "sees": "Everything", "source": _SPEC_ROLES},
    "clearer": {"label": "Clearer", "sees": "Instructors and modules they assess", "source": _SPEC_ROLES},
    "coach": {"label": "Coach", "sees": "Assigned instructors' records", "source": _SPEC_ROLES},
    "observer-in-training": {
        "label": "Observer in training",
        "sees": "Assigned recordings and their own scores",
        "source": _SPEC_ROLES,
    },
    "instructor": {"label": "Instructor", "sees": "Their own record only", "source": _SPEC_ROLES},
    "manager": {
        "label": "Engineering manager",
        "sees": "Their people's clearance status, not scores",
        "source": _SPEC_ROLES,
    },
    "partner-lead": {
        "label": "Partner lead",
        "sees": "Their people's clearance status, not scores",
        "source": _SPEC_ROLES,
    },
    "coordinator": {
        "label": "Programme coordinator",
        "sees": "Clearance register and schedules, not scores",
        "source": _SPEC_ROLES,
    },
    "programme-owner": {
        "label": "Programme owner",
        "sees": "Everything in the private store, which they write with the head of training",
        "source": ("0006", "Decision", "Access"),
    },
    "it": {
        "label": "IT",
        "sees": "No instructor records; administers the library, its security group and the nightly copy",
        "source": ("0006", "Decision", "Access"),
    },
    "dpo": {
        "label": "Data protection officer",
        "sees": "This record of processing and the DPIA screening facts; no instructor records",
        "source": (WORKFLOW_DESIGN, "7"),
    },
    "legal": {
        "label": "Internal legal",
        "sees": "The privacy profiles and the record of processing; no instructor records",
        "source": (PRIVACY_DESIGN, "2"),
    },
}

# Spec v0.2, Privacy, consent and fairness: Retention.
RETENTION_SPEC = (
    "Spec: observations and outcome summaries are kept for the engagement plus a set period; "
    "the event log is kept longer."
)


class SetupError(Exception):
    """A setup step refused its input; the message names what to fix."""


# --- helpers ------------------------------------------------------------------------------------


def _event(kind: str, subject: str, payload: dict[str, Any], now: Any) -> dict[str, Any]:
    return ev.make_event(kind, subject, SYSTEM_ACTOR, payload, at=_iso(now))


def _latest(log: Iterable[Mapping[str, Any]], kind: str, subject: str, step: str | None = None):
    found = None
    for e in log:
        if e["kind"] == kind and e["subject_uri"] == subject and (step is None or e["payload"].get("step") == step):
            found = e
    return found


def _output(
    private: Path,
    log: Sequence[Mapping[str, Any]],
    step: str,
    subject: str,
    rel: str,
    data: bytes,
    now: Any,
    **extra: Any,
) -> list[dict[str, Any]]:
    """Write one output file; return a `step` event unless the latest one has the same hash and the same `extra`."""
    _write(private / rel, data)
    digest = _sha(data)
    latest = _latest(log, "step", subject, step)
    if latest is not None and latest["payload"].get("output_sha256") == digest \
            and all(latest["payload"].get(k) == v for k, v in extra.items()):
        return []  # same output, and nothing it was made against has moved
    return [_event("step", subject, {"step": step, "output": rel, "output_sha256": digest, **extra}, now)]


def _blocked(log: Sequence[Mapping[str, Any]], step: str, subject: str, reasons: list[str], now: Any):
    payload = {"step": step, "result": "blocked", "reasons": reasons}
    latest = _latest(log, "check", subject, step)
    if latest is not None and latest["payload"] == payload:
        return []
    return [_event("check", subject, payload, now)]


def _render(root: Path, name: str, **values: Any) -> str:
    text = Template((root / "standards" / "templates" / name).read_text(encoding="utf-8")).substitute(values)
    return text.rstrip("\n") + "\n"


_EML_STYLE = (
    "body{font:11pt Calibri,Arial,sans-serif;color:#1b1f24}h1{font-size:16pt}h2{font-size:13pt;margin-top:1.2em}"
    "h3{font-size:11.5pt}table{border-collapse:collapse;margin:.5em 0}th,td{border:1px solid #d0d7de;"
    "padding:4px 8px;text-align:left;vertical-align:top}th{background:#f6f8fa}code{font-family:Consolas,monospace}"
)


def _eml(to: str, subject: str, body: str) -> bytes:
    """An unsent draft with the markdown as the plain-text part and its rendering as the HTML part, so that Outlook
    shows headings, lists and tables rather than markdown syntax (owner, 2026-10-26)."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg["X-Unsent"] = "1"  # Outlook opens the file as an unsent draft
    msg.set_content(body, charset="utf-8")
    page = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_EML_STYLE}</style></head>'
            f"<body>{mdlite.to_html(body)}</body></html>\n")
    msg.add_alternative(page, subtype="html", charset="utf-8")
    msg.set_boundary("tm-" + _sha(body.encode("utf-8"))[:32])  # a random boundary would rewrite the file every run
    return msg.as_bytes(policy=email.policy.SMTP)


def load_settings(private_dir: Path | str) -> dict[str, Any]:
    """Load and validate `<private>/settings.yaml` (tm:contract/settings@1)."""
    path = Path(private_dir) / "settings.yaml"
    if not path.is_file():
        raise SetupError(f"missing {path}: deployment settings (contracts/settings.schema.json)")
    doc = load_yaml(path)
    errors = validate(doc, SETTINGS_SCHEMA) if isinstance(doc, dict) else ["<root>: not a mapping"]
    if errors:
        raise SetupError(f"{path}: " + "; ".join(errors))
    return doc


# --- derived content ----------------------------------------------------------------------------


def _schema(root: Path, name: str) -> dict[str, Any]:
    return json.loads((root / "contracts" / name).read_text(encoding="utf-8"))


def _subfields(prop: Mapping[str, Any]) -> list[str]:
    if "properties" in prop:
        return list(prop["properties"])
    items = prop.get("items")
    if isinstance(items, Mapping) and "properties" in items:
        return list(items["properties"])
    return []


def _item(name: str, prop: Mapping[str, Any]) -> tuple[str, str]:
    desc = prop.get("description", "")
    subs = _subfields(prop)
    if subs:
        desc = (desc + " " if desc else "") + "Fields: " + ", ".join(subs) + "."
    return name, desc


def data_categories(root: Path = ROOT) -> list[dict[str, Any]]:
    """Data categories derived from the contracts, never typed by hand. Each has a stable `id` (a slug) that
    purposes and retention entries refer to; titles may be reworded, ids may not. Derived once per content of the
    contracts (the list is shared; callers must not change it).

    Roster instructor fields: the identity block is identity data, `instructor` is the pseudonymous
    id, `delivers` is delivery data, and every other field is employment and training data. All
    observation payload fields are performance data. Event kinds describe the record of actions.
    """
    names = ("roster.schema.json", "observation.schema.json", "event.schema.json")
    key = ("data-categories", *(sha256_hex((Path(root) / "contracts" / n).read_bytes()) for n in names))
    return memo(key, lambda: _data_categories(root))


def _data_categories(root: Path) -> list[dict[str, Any]]:
    inst = _schema(root, "roster.schema.json")["$defs"]["instructor"]["properties"]
    identity, ident_id, employment, delivery = [], [], [], []
    for name, prop in inst.items():
        if name == "identity":
            identity += [_item(n, p) for n, p in prop["properties"].items()]
        elif name == "instructor":
            ident_id.append(_item(name, prop))
        elif name == "delivers":
            delivery.append(_item(name, prop))
        else:
            employment.append(_item(name, prop))
    obs = _schema(root, "observation.schema.json")["properties"]
    kinds = _schema(root, "event.schema.json")["properties"]["kind"]["enum"]
    roster_src = "contracts/roster.schema.json"
    return [
        {"id": "identity-data", "title": "Identity data",
         "source": f"{roster_src}, identity block. Private store only: {IDENTITIES}.", "items": identity},
        {"id": "pseudonymous-identifier", "title": "Pseudonymous identifier",
         "source": f"{roster_src}. Still personal data (GDPR Recital 26).", "items": ident_id},
        {"id": "employment-and-training-data", "title": "Employment and training data", "source": roster_src,
         "items": employment},
        {"id": "delivery-data", "title": "Delivery data", "source": roster_src, "items": delivery},
        {"id": "performance-data", "title": "Performance data",
         "source": "contracts/observation.schema.json, observation records.",
         "items": [_item(n, p) for n, p in obs.items()]},
        {"id": "record-of-actions", "title": "Record of actions",
         "source": "contracts/event.schema.json, event kinds in the append-only log.",
         "items": [(k, "") for k in kinds]},
    ]


def _categories_md(cats: list[dict[str, Any]], cite: Citer | None = None) -> str:
    """With `cite`, the contract path at the start of each source is a link listed in the table of authorities."""
    out = []
    for c in cats:
        source = c["source"]
        if cite:
            path = re.match(r"contracts/[\w.-]+\.json", source)
            if path:
                source = cite.path(path.group(0)) + source[path.end():]
        lines = [f"### {c['title']}", "", f"Source: {source}", ""]
        lines += [f"- `{n}`: {d}" if d else f"- `{n}`" for n, d in c["items"]]
        out.append("\n".join(lines))
    return "\n\n".join(out)


def _held_md(cats: list[dict[str, Any]]) -> str:
    lines = []
    for c in cats:
        names = [n.replace("_", " ") for n, _ in c["items"]]
        lines.append(f"- {c['title']}: {', '.join(names)}.")
    return "\n".join(lines)


def _recipients_md(cite: Citer | None) -> str:
    """One line per role; with `cite`, each line cites its source."""
    lines = []
    for role in ROLES:
        r = ROLE_SEES[role]
        tail = f" ({cite(*r['source'])})" if cite else ""
        lines.append(f"- {r['label']}: {r['sees']}.{tail}")
    return "\n".join(lines)


def _subjects_md(root: Path, cite: Citer) -> str:
    types = _schema(root, "roster.schema.json")["$defs"]["instructor"]["properties"]["type"]["enum"]
    section = "Privacy, consent and fairness"
    return (
        f"Instructors of {len(types)} types: {', '.join(types)} ({cite.path('contracts/roster.schema.json')}).\n\n"
        "Learners are not recorded as individuals: learner data is aggregated at import. Learners who "
        "appear in session recordings are covered by the platform's recording notice; this system "
        f"stores a link and timestamps, not the recording ({cite(SPEC, section, 'Recordings')}; "
        f"{cite(SPEC, section, 'Learner data')})."
    )


def _storage_md(library: str, cite: Citer) -> str:
    def c(para: str) -> str:
        return f" ({cite('0006', 'Decision', para)})"
    return "\n".join([
        f'- Location: a dedicated SharePoint document library, "{library}", in the Microsoft 365 tenant, '
        "synced to one machine. Not a personal OneDrive folder." + c("Location"),
        "- Access: one security group. The head of training and the programme owner write; "
        "nobody else reads raw files. Other roles see views. No sharing links. Audit log and versioning on."
        + c("Access"),
        f"- Layout: {IDENTITIES} is the only file that links instructor ids to names and emails. "
        "evidence/ holds observation notes and recording links. events/events.jsonl is the append-only log."
        + c("Layout"),
        "- One writer: a single machine appends to the event log." + c("One writer"),
        "- Backup: a nightly copy to a second company location with a SHA-256 manifest of each file. "
        "A restore is tested each quarter." + c("Backup"),
        "- Erasure: deletes the identity row and the evidence files. Events stay but can no longer be "
        "linked to a person (legal review)." + c("Erasure and retention"),
    ])


def retention_errors(doc: Mapping[str, Any], root: Path = ROOT) -> list[str]:
    """Cross-checks a retention@2 document must pass beyond its schema: every entry names a known data
    category, and no (category, purpose, jurisdiction) has more than one entry."""
    known = {c["id"] for c in data_categories(root)}
    errors: list[str] = []
    seen: set[tuple[str, str, str | None]] = set()
    for n, e in enumerate(doc.get("entries", [])):
        if e["category"] not in known:
            errors.append(f"entries/{n}: unknown data category {e['category']!r}; known ids are {sorted(known)}")
        key = (e["category"], e["purpose"], e.get("jurisdiction"))
        if key in seen:
            errors.append(f"entries/{n}: more than one entry for category {key[0]}, purpose {key[1]}, "
                          f"jurisdiction {key[2] or 'base'}")
        seen.add(key)
    return errors


PILOT_RETENTION = Path("inputs") / "retention.yaml"


def retention_file(private_dir, settings: Mapping[str, Any], root: Path = ROOT) -> Path:
    """The retention table in force for a store: `standards/retention.yaml`, or, in a pilot store (settings
    `pilot: true`, decision 0016), the generated table `inputs/retention.yaml` when it exists. A real store never reads
    a table from the store, so generated periods cannot reach real data (owner, 2026-10-27)."""
    pilot_table = Path(private_dir) / PILOT_RETENTION
    if settings.get("pilot") is True and pilot_table.is_file():
        return pilot_table
    return Path(root) / "standards" / "retention.yaml"


def load_retention(path: Path, root: Path = ROOT) -> dict[str, Any]:
    doc = load_yaml(path)
    errors = validate(doc, "retention.schema.json") if isinstance(doc, dict) else ["<root>: not a mapping"]
    errors = errors or retention_errors(doc, root)
    if errors:
        raise SetupError(f"{path}: " + "; ".join(errors))
    return doc


def _retention_md(ret: Mapping[str, Any], cats: list[dict[str, Any]], cite: Citer | None = None) -> str:
    spec = RETENTION_SPEC
    if cite:
        spec += f" ({cite(SPEC, 'Privacy, consent and fairness', 'Retention')})"
    lines = [f"Status: {ret['status']}. Basis: {ret['basis']}.", "", spec, ""]
    if not ret["entries"]:
        lines.append("No retention entries yet (to be set with legal advice).")
    title = {c["id"]: c["title"] for c in cats}
    order = {c["id"]: n for n, c in enumerate(cats)}
    for e in sorted(ret["entries"], key=lambda e: (order.get(e["category"], len(order)), e["purpose"],
                                                   e.get("jurisdiction") or "")):
        period = f"{e['period_months']} months" if "period_months" in e else f"until {e['until_event']}"
        purpose = e["purpose"].split("/", 1)[1].replace("-", " ")
        where = f", {e['jurisdiction']}" if "jurisdiction" in e else ""
        lines.append(f"- {title.get(e['category'], e['category'])} ({purpose}{where}): {period}. "
                     f"Starts: {e['starts']} Why: {e['reason']} Basis: {e['basis']}.")
    return "\n".join(lines)


def _decision(decisions_dir: Path, number: str) -> tuple[str | None, str, Path | None]:
    """(frontmatter status, '## Decision' section text, path) of a decision record."""
    found = sorted(Path(decisions_dir).glob(f"{number}-*.md"))
    if not found:
        return None, "", None
    text = found[0].read_text(encoding="utf-8")
    status = None
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if m:
        front = yaml.safe_load(m.group(1)) or {}
        status = front.get("status")
    d = re.search(r"^## Decision[ \t]*\r?\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return status, (d.group(1).strip() if d else ""), found[0]


# --- auto steps ---------------------------------------------------------------------------------


def it_request(private_dir, events, settings, now, *, root: Path = ROOT) -> list[dict[str, Any]]:
    """tm:step/it-request: the 0006 library, group and settings as one request (markdown + .eml)."""
    private = Path(private_dir)
    cite = Citer(root)
    text = _render(root, "it-request.md", library=settings["library"], it_email=settings["it_email"],
                   mailbox=settings["mailbox"], basis=cite("0006", "Decision"),
                   location=cite("0006", "Decision", "Location"), access=cite("0006", "Decision", "Access"),
                   backup=cite("0006", "Decision", "Backup"), one_writer=cite("0006", "Decision", "One writer"),
                   before_real_data=cite("0006", "Decision", "Before real data"), authorities=cite.table())
    _write(private / "generated" / "it-request.eml", _eml(settings["it_email"], IT_REQUEST_SUBJECT, text))
    return _output(private, list(events), STEP_IT_REQUEST, PROGRAMME, "generated/it-request.md",
                   text.encode("utf-8"), now, eml="generated/it-request.eml")


def ropa(private_dir, events, settings, now, *, root: Path = ROOT, retention_path: Path | None = None):
    """tm:step/ropa: the record-of-processing entry, derived from the contracts, roles, 0006, the purposes with
    their proposed bases, the base profile and the retention table as set in the file."""
    private = Path(private_dir)
    ret = load_retention(retention_path or retention_file(private, settings, root), root)
    try:
        purposes = privacy.load_purposes(root)
        _, profile = privacy.base_profile(root)
        names = privacy.profile_names(root)
    except PrivacyError as exc:
        return _blocked(list(events), STEP_ROPA, PROGRAMME, [str(exc)], now)
    cats = data_categories(root)
    try:
        cite = Citer(root)
        values = dict(
            controller_source=cite("0004", "Decision", 2),
            purposes_source=cite.path("contracts/purposes.schema.json"),
            purposes=cite.mentions(notice.purposes_ropa_md(purposes, notice.titles(cats), names)),
            lawful_basis=cite.mentions(notice.lawful_basis_md(profile)),
            subjects=_subjects_md(root, cite), categories=_categories_md(cats, cite),
            recipients_source=cite(SPEC, "Users and roles"),
            recipients=_recipients_md(cite), storage=_storage_md(settings["library"], cite),
            retention=_retention_md(ret, cats, cite),
        )
    except CitationError as exc:
        return _blocked(list(events), STEP_ROPA, PROGRAMME, [f"citation: {exc}"], now)
    text = _render(root, "ropa.md", dpo_email=settings["dpo_email"], mailbox=settings["mailbox"],
                   authorities=cite.table(), **values)
    return _output(private, list(events), STEP_ROPA, PROGRAMME, "generated/ropa.md", text.encode("utf-8"), now)


def retention_digest(root: Path, log: Iterable[Mapping[str, Any]], retention_path: Path | None = None) -> str:
    """The hash of the inputs of the retention approval as they are now (privacy.retention_inputs). A notice or variant
    approval carries it, so changing retention reopens them; raises SetupError or PrivacyError when the entries cannot
    be approved (empty, a missing pair, a breach of a verified limit)."""
    root = Path(root)
    ret = load_retention(retention_path or root / "standards" / "retention.yaml", root)
    return retention_digest_of(root, ret, log)


def retention_digest_of(root: Path, ret: Mapping[str, Any], log: Iterable[Mapping[str, Any]]) -> str:
    """`retention_digest` for retention entries already loaded."""
    return signoff.input_sha256(privacy.retention_inputs(Path(root), ret, list(log)))


def variant_inputs(
    text: str, variant: str, base_profile_sha256: str, overlay_profile_sha256: str, retention_sha256: str
) -> dict[str, str]:
    """What the variant approval page shows; the owner's sign-off covers the exact variant text, both profiles and the
    retention it was rendered with, so an edit of any reopens it even when the text does not change."""
    return {"text": text, "version": variant, "base_profile_sha256": base_profile_sha256,
            "overlay_profile_sha256": overlay_profile_sha256, "retention_sha256": retention_sha256}


def notice_inputs(text: str, version: str, base_profile_sha256: str, retention_sha256: str) -> dict[str, str]:
    """What the notice approval page shows; its signoff.input_sha256 is what the owner approves. The hashes of the base
    profile and of the retention inputs are part of it, so an edit of either reopens the approval even when the text
    does not change."""
    return {"text": text, "version": version, "base_profile_sha256": base_profile_sha256,
            "retention_sha256": retention_sha256}


def sent_variants(log: Iterable[Mapping[str, Any]]) -> set[str]:
    """The notice versions or variants some instructor has been sent (a `notice` event names it)."""
    return {e["payload"].get("notice_variant", e["payload"].get("notice_version")) for e in log if e["kind"] == "notice"}


def changed_under_sent(private: Path, log: Iterable[Mapping[str, Any]], variant: str, data: bytes) -> bool:
    """True when `data` would replace a different rendered text under a version or variant that has already been
    sent: the people who were sent it would hold a text this file no longer says."""
    path = Path(private) / _notice_path(variant)
    return variant in sent_variants(log) and path.is_file() and path.read_bytes() != data


def _notice_path(version: str) -> str:
    return f"generated/notice-{version}.md"


def notice_values(
    root: Path, settings: Mapping[str, Any], profile: Mapping[str, Any], purposes: Mapping[str, Any],
    purposes_md: str, ret: Mapping[str, Any], separation: str,
) -> dict[str, str]:
    """The text each placeholder of the notice templates stands for, for one base profile and retention table."""
    cats = data_categories(root)
    return {
        "dpo_email": settings["dpo_email"], "held": _held_md(cats), "purposes": purposes_md,
        "legitimate_interests": notice.legitimate_interests_md(purposes, profile["id"]),
        "separation": separation, "recipients": _recipients_md(None), "retention": _retention_md(ret, cats),
        "consent": notice.consent_md(purposes, profile["id"]), "complaint": notice.regulator_md(profile),
    }


def notice_text(
    private_dir,
    events,
    settings,
    now,
    *,
    root: Path = ROOT,
    decisions_dir: Path | None = None,
    retention_path: Path | None = None,
) -> list[dict[str, Any]]:
    """tm:step/notice-text: render the draft notice from the purposes (name, description, basis), the retention
    entries (period, start, reason), the base profile and decision 0005.

    Blocked while the base profile is not verified, the retention entries are missing or not approved, 0005 is open,
    a purpose has no proposed basis, or the template lacks a marker for a mandatory element of the base profile (or its
    section renders empty). The engine's `needs` gate the step the same way; the checks here are the second lock."""
    private, log = Path(private_dir), list(events)
    try:
        profile_path, profile = privacy.base_profile(root)
        purposes = privacy.load_purposes(root)
    except PrivacyError as exc:
        return _blocked(log, STEP_NOTICE_TEXT, PROGRAMME, [str(exc)], now)
    status, separation, path = _decision(decisions_dir or root / "docs" / "decisions", "0005")
    ret = load_retention(retention_path or retention_file(private, settings, root), root)
    reasons = []
    if not privacy.base_verified(log, root):
        reasons.append("base profile not verified")
    if path is None:
        reasons.append("decision 0005 (performance-management separation) not found")
    elif status != "accepted":
        reasons.append(f"decision 0005 is {status}; the notice must state its answer, so it must be accepted")
    elif not separation:
        reasons.append("decision 0005 has no '## Decision' text to quote")
    if not ret["entries"]:
        reasons.append("no retention entries set (standards/retention.yaml has entries: [])")
    else:
        gaps = privacy.coverage_gaps(purposes, ret["entries"], base_only=True)
        reasons += gaps
        if not gaps and not privacy.retention_approved(log, root, ret):
            reasons.append("retention not approved")
    purposes_md, basis_reasons = notice.purposes_md(purposes, profile["id"])
    reasons += basis_reasons
    if reasons:
        return _blocked(log, STEP_NOTICE_TEXT, PROGRAMME, reasons, now)
    version = settings["notice_version"]
    rendered = _render(root, "privacy-notice.md", version=version,
                       **notice_values(root, settings, profile, purposes, purposes_md, ret, separation))
    if settings.get("simulated") is True:  # decision 0020: a simulated store renders the draft templates, labelled
        rendered = notice.simulated(rendered)
    problems = notice.element_problems(rendered, [e["id"] for e in profile["notice_elements"]])
    if problems:
        return _blocked(log, STEP_NOTICE_TEXT, PROGRAMME, problems, now)
    data = notice.strip_markers(rendered).encode("utf-8")
    if changed_under_sent(private, log, version, data):
        return _blocked(log, STEP_NOTICE_TEXT, PROGRAMME,
                        [f"notice text changed under version {version}: bump notice_version in settings"], now)
    return _output(private, log, STEP_NOTICE_TEXT, PROGRAMME, _notice_path(version), data, now,
                   text_sha256=_sha(data), notice_version=version, retention_sha256=retention_digest_of(root, ret, log))


def _registrations(log: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """The latest `registration` payload of each instructor (later events win)."""
    return {e["subject_uri"]: e["payload"] for e in log if e["kind"] == "registration"}


def _identities(private: Path) -> dict[str, dict[str, Any]]:
    path = private / IDENTITIES
    if not path.is_file():
        return {}
    doc = load_yaml(path) or {}
    return {row["instructor"]: dict(row["identity"]) for row in doc.get("instructors", [])}


def notice_drafts(private_dir, events, settings, now, *, root: Path = ROOT) -> list[dict[str, Any]]:
    """tm:step/notice-drafts: one unsent .eml per registered instructor, from the approved text only.

    An instructor whose jurisdiction the base profile covers gets the base notice; any other gets their jurisdiction's
    variant (`<version>-<code>`), tagged `[tm-notice <variant>]`, once the owner has approved the exact variant. An
    instructor whose variant cannot be used (no jurisdiction recorded, no profile, not rendered, not approved) gets
    no draft and a blocked check that names why; the others are not held up."""
    private, log = Path(private_dir), list(events)
    version = settings["notice_version"]
    path = private / _notice_path(version)
    if not path.is_file():
        return _blocked(log, STEP_NOTICE_DRAFTS, PROGRAMME, [f"notice text {version} not rendered"], now)
    text = path.read_text(encoding="utf-8")
    try:
        profile_path, base = privacy.base_profile(root)
        profile_sha = privacy.profile_inputs(profile_path, root)["sha256"]
    except PrivacyError as exc:
        return _blocked(log, STEP_NOTICE_DRAFTS, PROGRAMME, [str(exc)], now)
    try:
        retention_sha = retention_digest(root, log, retention_file(private, settings, root))
    except (PrivacyError, SetupError) as exc:
        return _blocked(log, STEP_NOTICE_DRAFTS, PROGRAMME, [str(exc)], now)
    approval = _latest(log, "signoff", PROGRAMME, STEP_NOTICE_APPROVED)
    want = signoff.input_sha256(notice_inputs(text, version, profile_sha, retention_sha))
    if approval is None:
        return _blocked(log, STEP_NOTICE_DRAFTS, PROGRAMME, [f"notice text {version} not approved"], now)
    if approval["payload"].get("decision") != "approve" or approval["payload"].get("input_sha256") != want:
        return _blocked(log, STEP_NOTICE_DRAFTS, PROGRAMME,
                        [f"latest notice approval does not approve the current notice text {version}"], now)
    ids = _identities(private)
    registrations = _registrations(log)
    out: list[dict[str, Any]] = []
    for uri in sorted(registrations):
        who = ids.get(uri)
        if who is None:
            out += _blocked(log, STEP_NOTICE_DRAFTS, uri, [f"no identity row in {IDENTITIES}"], now)
            continue
        code = registrations[uri].get("jurisdiction")
        if not isinstance(code, str):
            out += _blocked(log, STEP_NOTICE_DRAFTS, uri, ["no jurisdiction recorded, so no notice variant"], now)
            continue
        variant = notice_variant(version, code, base["codes"])
        body_text, reasons = (text, []) if variant == version else _variant_text(
            private, log, root, code, variant, profile_sha, retention_sha)
        if reasons:
            out += _blocked(log, STEP_NOTICE_DRAFTS, uri, reasons, now)
            continue
        subject_line = f"Privacy notice: instructor development [tm-notice {variant}]"
        body = f"Dear {who['name']},\n\n{body_text}"
        rel = f"generated/notice-drafts/{_slug(uri)}.eml"
        out += _output(private, log, STEP_NOTICE_DRAFTS, uri, rel, _eml(who["email"], subject_line, body), now,
                       text_sha256=_sha(body_text.encode("utf-8")), notice_version=version, notice_variant=variant)
    return out


def _variant_text(
    private: Path, log: Sequence[Mapping[str, Any]], root: Path, code: str, variant: str, base_sha: str,
    retention_sha: str,
) -> tuple[str, list[str]]:
    """(the approved text of a jurisdiction's notice variant, []) or ("", the reasons it cannot be used yet)."""
    try:
        found = privacy.overlay_profile(code, root)
    except PrivacyError as exc:
        return "", [str(exc)]
    if found is None:
        return "", [f"no profile for {code}"]
    path = private / _notice_path(variant)
    if not path.is_file():
        return "", [f"notice variant {variant} is not rendered"]
    text = path.read_text(encoding="utf-8")
    overlay_sha = privacy.profile_inputs(found[0], root)["sha256"]
    inputs = variant_inputs(text, variant, base_sha, overlay_sha, retention_sha)
    subject = workflow.jurisdiction_uri(code)
    if privacy.approved_covers(log, privacy.STEP_VARIANT_APPROVED, inputs, subject):
        return text, []
    if _latest(log, "signoff", subject, privacy.STEP_VARIANT_APPROVED) is None:
        return "", [f"notice variant {variant} is not approved"]
    return "", [f"latest approval does not approve the current notice variant {variant}"]


def _registration(row: Mapping[str, Any], as_of: str) -> dict[str, Any]:
    payload = {k: row[k] for k in ("type", "organisation", "level", "languages", "regions", "jurisdiction")}
    payload["engagement"] = dict(row["engagement"])
    payload["delivers"] = [dict(d) for d in row.get("delivers", [])]
    payload["roster_as_of"] = as_of
    return payload


def _without_as_of(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "roster_as_of"}


def import_prerequisites(
    log: Iterable[Mapping[str, Any]], root: Path = ROOT, retention_path: Path | None = None
) -> list[str]:
    """What is still missing before real data may enter the store (0006, Before real data; privacy-jurisdictions design
    section 4), from the facts themselves: the library exists, legal has verified the base profile as it is now, the
    DPO's DPIA clears the base triggers and purposes as they are now, and the head of training has approved the
    retention entries as they are now. Empty when the import may go ahead."""
    root, log = Path(root), list(log)
    missing: list[str] = []
    if not any(e["kind"] == "check" and e["subject_uri"] == PROGRAMME and e["payload"].get("step") == "tm:step/library-exists"
               and e["payload"].get("result") == "ok" for e in log):
        missing.append("the library does not exist yet (no ok library-exists check)")
    if not privacy.base_verified(log, root):
        missing.append("the base profile is not verified for the file as it is now")
    if not privacy.dpia_current(log, root):
        missing.append("the DPIA screening is not cleared for the base triggers and purposes as they are now")
    try:
        ret = load_retention(retention_path or root / "standards" / "retention.yaml", root)
        if not privacy.retention_approved(log, root, ret):
            missing.append("the retention entries are not approved as they are now")
    except SetupError as exc:
        missing.append(f"the retention table is unusable ({exc})")
    return missing


def pilot_check(private_dir, settings: Mapping[str, Any] | None, doc: Any) -> None:
    """Decision 0016, checked before a roster is read into the store or copied into it.

    A store in the user's own OneDrive folder must be marked `pilot: true`; a pilot store takes only generated
    instructors, whose emails are on reserved domains. `settings` None reads `<private>/settings.yaml` when it exists.
    Raises SetupError naming each refused instructor by id and domain, never by address."""
    private = Path(private_dir)
    if settings is None:
        settings = load_settings(private) if (private / "settings.yaml").is_file() else {}
    pilot = settings.get("pilot") is True
    if not pilot and in_personal_onedrive(private):
        raise SetupError(f"roster import refused: {private} is in a personal OneDrive folder, which may hold "
                         "generated data only; set 'pilot: true' in settings.yaml (decision 0016)")
    if pilot:
        refusals = roster_module.pilot_refusals(doc)
        if refusals:
            raise SetupError("roster import refused: this is a pilot store (settings 'pilot: true', decision 0016), "
                             "which takes generated instructors only, with emails on reserved domains such as "
                             "example.com: " + "; ".join(refusals))


def import_roster(
    private_dir, roster_path, events, now, *, root: Path = ROOT, retention_path: Path | None = None,
    settings: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """tm:step/roster-import: identities to the private store, references to events.

    Refused (SetupError naming each missing item) unless the base workflow is complete: see `import_prerequisites`.
    The engine's `needs` gate the command first; this is the second lock, on the facts.

    A changed level refuses the whole import: levels move only by decision (spec). Any other change
    becomes a new `registration` event; later events win. A pilot store refuses real instructors (`pilot_check`).
    """
    private, log = Path(private_dir), list(events)
    missing = import_prerequisites(log, root, retention_path)
    if missing:
        raise SetupError("roster import refused, missing: " + "; ".join(missing))
    doc = roster_module.load(Path(roster_path))
    pilot_check(private, settings, doc)
    errors = roster_module.check_roster(doc, root)
    if errors:
        raise SetupError(f"{roster_path}: check-roster failed: " + "; ".join(errors))

    reg: dict[str, dict[str, Any]] = {}
    level: dict[str, str] = {}
    for e in log:
        if e["kind"] == "registration":
            reg[e["subject_uri"]] = e["payload"]
        elif e["kind"] == "level_change":
            level[e["subject_uri"]] = e["payload"]["to"]

    out: list[dict[str, Any]] = []
    refused: list[str] = []
    for row in doc["instructors"]:
        uri = row["instructor"]
        payload = _registration(row, doc["as_of"])
        if uri not in reg:
            out.append(_event("registration", uri, payload, now))
            out.append(_event("level_change", uri, {"from": None, "to": row["level"], "basis": "roster baseline"}, now))
            continue
        current = level.get(uri, reg[uri].get("level"))
        if row["level"] != current:
            refused.append(f"{uri}: roster level {row['level']} differs from recorded level {current}")
        elif _without_as_of(payload) != _without_as_of(reg[uri]):
            out.append(_event("registration", uri, payload, now))
    if refused:
        raise SetupError("roster import refused; levels move only by decision (spec): " + "; ".join(refused))

    ids = _identities(private)
    for row in doc["instructors"]:
        ids[row["instructor"]] = dict(row["identity"])
    body = {"instructors": [{"instructor": uri, "identity": ids[uri]} for uri in sorted(ids)]}
    data = (
        "# Private: the only file linking tm:instructor URIs to names and emails (decision 0006).\n"
        "# Written by the teachermodel roster import; do not commit.\n"
        + yaml.safe_dump(body, sort_keys=True, allow_unicode=True)
    ).encode("utf-8")
    return out + _output(private, log, STEP_ROSTER_IMPORT, PROGRAMME, IDENTITIES, data, now)


def gap_list(
    private_dir,
    events,
    settings,
    now,
    *,
    clearances: Iterable[Clearance] = (),
    rules: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> list[dict[str, Any]]:
    """tm:step/gap-list: every registered delivery (instructor, unit, mode) without an ok staffing check.

    The check is asked as delivery scheduling would ask it (integration review finding 8): for a partner instructor
    (registration type partner) for the registration's organisation in each of its regions (the worst verdict counts), so a
    partner's scoped clearance covers its own deliveries; and with the instructor's latest blocking bench decision, so an
    exit or a return to co-teaching shows as a gap ("bench decision: ..."). Overrides are not read: one covers one date.

    Writes batch-approve rows. `changed` marks a row that was not in the previous output; when the
    row set is the same as the previous output, the previous output stands unchanged.
    """
    private, log = Path(private_dir), list(events)
    rules = rules or load_standards(root)["rules"]
    cl = list(clearances)
    on = now.date() if isinstance(now, datetime) else now
    reg = _registrations(log)
    order = {"ok": 0, "warn": 1, "block": 2}
    found: dict[str, str] = {}
    for uri in sorted(reg):
        partner = reg[uri].get("organisation") if reg[uri].get("type") == "partner" else None
        regions = (reg[uri].get("regions") or [None]) if partner else [None]
        blocking = bench_blocks.latest_blocking(log, uri, on)
        bench = (blocking["decision"], blocking["at"]) if blocking else None
        for d in reg[uri].get("delivers", []):
            for mode in d["modes"]:
                res = max((staffing_check(cl, uri, d["unit"], mode, on, rules, partner=partner, region=region, bench=bench)
                           for region in regions), key=lambda r: order[r["verdict"]])
                if res["verdict"] == "ok":
                    continue
                # Fixed wording (no day counts) so the gap list does not change from one day to the next.
                window = rules["staffing"]["warn_expiry_days"]
                benched = [r for r in res["reasons"] if r in BENCH_BLOCKS.values()]
                if res["verdict"] == "block" and benched:
                    why = benched[0]
                elif res["verdict"] == "block":
                    why = "no valid clearance"
                elif any("recheck" in r for r in res["reasons"]):
                    why = f"conditional recheck due within {window} days"
                else:
                    why = f"clearance expires within {window} days"
                found[f"{uri} {d['unit']} {mode}"] = f"{uri} delivers {d['unit']} in {mode} mode: {why}"

    rel = "generated/gap-list.json"
    prev_rows = None
    if (private / rel).is_file():
        try:
            prev_rows = json.loads((private / rel).read_text(encoding="utf-8"))["rows"]
        except (ValueError, KeyError, TypeError):
            prev_rows = None
    prev = {(r["key"], r["summary"]) for r in prev_rows} if prev_rows is not None else None
    if prev is not None and prev == set(found.items()):
        rows = prev_rows
    else:
        rows = [{"key": k, "summary": s, "changed": prev is None or (k, s) not in prev} for k, s in sorted(found.items())]
    data = (json.dumps({"rows": rows}, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    return _output(private, log, STEP_GAP_LIST, PROGRAMME, rel, data, now)
