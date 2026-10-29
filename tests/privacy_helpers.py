"""Helpers for tests that need a repo-data root with fictional privacy files (importable: pythonpath has tests/)."""

import shutil as _shutil
from pathlib import Path as _Path

import yaml as _yaml

from teachermodel.standards import ROOT as _ROOT

FIXTURE_PRIVACY = _Path(__file__).parent / "fixtures" / "privacy"
BASE_URI = "tm:jurisdiction/xx"


def edit_yaml(path, fn):
    """Load a YAML file, apply `fn` to the document and write it back."""
    doc = _yaml.safe_load(_Path(path).read_text(encoding="utf-8"))
    fn(doc)
    _Path(path).write_text(_yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def complete_retention_entries(purposes, months=24):
    """One fictional base entry per (category, purpose) pair; placeholders, not advice."""
    return [
        {"category": cat, "purpose": p["id"], "period_months": months, "starts": "The engagement ends.",
         "reason": f"Fictional reason for keeping {cat} that long.", "basis": "legitimate-interests"}
        for p in purposes["purposes"] for cat in p["categories"]
    ]


def make_privacy_root(tmp_path, *, entries="complete"):
    """A copy of standards/, contracts/ and docs/ whose standards/privacy and retention.yaml are the fictional
    fixtures: base profile `xx`, two purposes (four category-purpose pairs), retention for every pair.
    `entries="empty"` leaves retention.yaml with no entries."""
    root = _Path(tmp_path) / "root"
    for part in ("standards", "contracts", "docs"):
        _shutil.copytree(_ROOT / part, root / part)
    privacy = root / "standards" / "privacy"
    _shutil.rmtree(privacy)
    (privacy / "jurisdictions").mkdir(parents=True)
    _shutil.copy(FIXTURE_PRIVACY / "jurisdiction-base.yaml", privacy / "jurisdictions" / "xx.yaml")
    purposes = _yaml.safe_load((FIXTURE_PRIVACY / "purposes.yaml").read_text(encoding="utf-8"))
    purposes["purposes"][1]["proposed_basis"] = {
        BASE_URI: {"basis": "consent", "reason": "Optional: an instructor can say no with no consequence.",
                   "notice_text": "Fictional notice sentence for reuse. You can say no, with no consequence."}}
    (privacy / "purposes.yaml").write_text(_yaml.safe_dump(purposes, sort_keys=False), encoding="utf-8")
    retention = _yaml.safe_load((FIXTURE_PRIVACY / "retention.yaml").read_text(encoding="utf-8"))
    retention["entries"] = [] if entries == "empty" else complete_retention_entries(purposes)
    (root / "standards" / "retention.yaml").write_text(_yaml.safe_dump(retention, sort_keys=False), encoding="utf-8")
    # The real templates are drafts (rendering refuses them); the fictional base profile gets a finished one.
    _shutil.copy(FIXTURE_PRIVACY / "privacy-notice.md", root / "standards" / "templates" / "privacy-notice.md")
    return root


# --- driving the privacy-base workflow without a mail round trip ---------------------------------------

import hashlib as _hashlib  # noqa: E402
import json as _json  # noqa: E402
import re as _re  # noqa: E402

PROGRAMME = "tm:programme/teachermodel"
STEP_VERIFIED = "tm:step/base-profile-verified"
STEP_ROPA_APPROVED = "tm:step/ropa-approved"
STEP_DPIA = "tm:step/dpia-screening"
STEP_RETENTION = "tm:step/retention-approved"
STEP_NOTICE_APPROVED = "tm:step/notice-approved"
LEGAL = "legal.lena@example.com"


def tm_data(page_path):
    """The tm-data block of a generated page."""
    page = _Path(page_path).read_text(encoding="utf-8")
    m = _re.search(r'<script type="application/json" id="tm-data">(.*?)</script>', page, _re.S)
    assert m, "no tm-data block"
    return _json.loads(m.group(1))


def sign_step(private, root, step, *, subject=PROGRAMME, decision="approve", at="2026-10-25T09:00:00+00:00"):
    """Append the sign-off event a person would produce for `step`: it covers the inputs the page shows now,
    exactly as the engine re-derives them. Returns the event."""
    from teachermodel import app, events

    st = app.load_state(private, root)
    digest = app._current_input_reader(st)(step, subject)
    assert digest is not None, f"no page can be built for {step} now"
    sid = _hashlib.sha256(f"{step}|{subject}|{at}|{decision}".encode()).hexdigest()[:16]
    payload = {"step": step, "decision": decision, "fields_sha256": "c" * 64, "input_sha256": digest,
               "signoff_id": sid, "page_template_sha256": "b" * 64, "signed_at": at}
    event = events.make_event("signoff", subject, "tm:person/seed", payload, at=at)
    events.append(private / app.EVENT_LOG, event)
    return event


def seed_check(private, step, *, at="2026-10-25T08:00:00+00:00", result="ok"):
    from teachermodel import app, events

    events.append(private / app.EVENT_LOG, events.make_event(
        "check", PROGRAMME, "tm:system/teachermodel", {"step": step, "result": result}, at=at))


def prerequisite_events(root, *, library=True, verified=True, dpia=True, retention=True, dpia_decision="approve",
                        at="2026-10-26T09:00:00+00:00"):
    """The event list of a store that is ready for the roster import: the library check, legal's verification of the
    base profile of `root`, the DPO's DPIA and the head of training's retention approval, each as the page would have
    hashed it. A flag set False leaves that one out (dpia_decision="changes" records a DPIA that clears nothing)."""
    from teachermodel import events, privacy, setup, signoff

    def signed(step, inputs, decision="approve"):
        payload = {"step": step, "decision": decision, "fields_sha256": "c" * 64,
                   "input_sha256": signoff.input_sha256(inputs), "signoff_id": signoff.input_sha256([step, at])[:16],
                   "page_template_sha256": "b" * 64, "signed_at": at}
        return events.make_event("signoff", PROGRAMME, "tm:person/seed", payload, at=at)

    root = _Path(root)
    log = []
    if library:
        log.append(events.make_event("check", PROGRAMME, "tm:system/teachermodel",
                                     {"step": "tm:step/library-exists", "result": "ok"}, at=at))
    path, _ = privacy.base_profile(root)
    if verified:
        log.append(signed(STEP_VERIFIED, privacy.profile_inputs(path, root)))
    if dpia:
        log.append(signed(STEP_DPIA, privacy.dpia_inputs(log, root), dpia_decision))
    if retention:
        ret = setup.load_retention(root / "standards" / "retention.yaml", root)
        log.append(signed(STEP_RETENTION, privacy.retention_inputs(root, ret, log)))
    return log


def ready_for_roster(private, root, now=None):
    """tick, the library check and the three bound sign-offs: the state in which the roster import may run."""
    from datetime import datetime, timezone

    from teachermodel import app

    app.do_tick(private, now=now or datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc), root=root)
    seed_check(private, "tm:step/library-exists")
    for step in (STEP_VERIFIED, STEP_ROPA_APPROVED, STEP_DPIA, STEP_RETENTION):
        sign_step(private, root, step)


def import_roster_ungated(private, roster, now):
    """Import a roster into a fictional store whatever the store's own state is, for tests that need an imported roster
    but are not about the base workflow. The prerequisites of the lock in setup.import_roster come from a fictional
    privacy root beside the store; only the import's own events are appended to the store."""
    from teachermodel import app, setup

    base = _Path(private).parent / "prereq"
    root = base / "root"
    if not root.exists():
        make_privacy_root(base)
    log = prerequisite_events(root) + app.read_events(_Path(private))
    app.append_new(_Path(private), setup.import_roster(private, roster, log, now, root=root))


def due_ids(private, root, today):
    """The set of (step, subject) due on `today`."""
    from teachermodel import app

    return {(d.step, d.subject) for d in app.due_steps(app.load_state(private, root), today)}


# --- a fictional California-coded overlay beside the fictional base ---------------------------------------

OVERLAY_URI = "tm:jurisdiction/us-ca"
OVERLAY_TEMPLATE = """## For residents of Fictional State

<!-- element: categories-collected -->
The categories of personal information we collect about you are:

$held

We keep them for these periods:

$retention

Purposes under the Fictional Privacy Rights Act:

$overlay_purposes
"""


def add_overlay(root, *, limits=(), triggers=(), template=OVERLAY_TEMPLATE, base_codes=("IE",)):
    """Add the fictional overlay as `us-ca` (code US-CA) to a root made by `make_privacy_root`: every purpose gets a
    disclosed-purpose basis for it, `limits` and `triggers` are its retention limits and DPIA triggers, and `template`
    is its notice template (None for none). The base profile is re-coded to `base_codes` (IE by default, so the
    example roster's Irish instructors are base and the Californian and German ones are not). Returns the overlay path."""
    root = _Path(root)
    jur = root / "standards" / "privacy" / "jurisdictions"
    edit_yaml(jur / "xx.yaml", lambda d: d.__setitem__("codes", list(base_codes)))
    purposes_path = root / "standards" / "privacy" / "purposes.yaml"
    purposes = _yaml.safe_load(purposes_path.read_text(encoding="utf-8"))
    for p in purposes["purposes"]:
        p.setdefault("proposed_basis", {})[OVERLAY_URI] = {
            "basis": "disclosed-purpose", "reason": "Fictional: disclosed at collection and kept to that purpose.",
            "notice_text": "Fictional notice sentence for the overlay. We use this only for the purpose above."}
    purposes_path.write_text(_yaml.safe_dump(purposes, sort_keys=False), encoding="utf-8")
    doc = _yaml.safe_load((FIXTURE_PRIVACY / "jurisdiction-overlay.yaml").read_text(encoding="utf-8"))
    doc.update(id=OVERLAY_URI, name="Fictional State (test overlay as California)", codes=["US-CA"],
               lawful_bases={p["id"]: ["disclosed-purpose"] for p in purposes["purposes"]},
               retention_limits=[dict(x) for x in limits], dpia_triggers=[dict(x) for x in triggers])
    path = jur / "us-ca.yaml"
    path.write_text(_yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    tpl = root / "standards" / "templates" / "privacy-notice-us-ca.md"
    if template is None:
        tpl.unlink(missing_ok=True)
    else:
        tpl.write_text(template, encoding="utf-8", newline="\n")
    return path


def cover_roster(root, codes=("IE", "US-CA", "DE")):
    """Re-code the fictional base profile so it covers the example roster's jurisdictions (no overlay subjects), for
    tests that want one notice for every instructor."""
    edit_yaml(_Path(root) / "standards" / "privacy" / "jurisdictions" / "xx.yaml", lambda d: d.__setitem__("codes", list(codes)))
