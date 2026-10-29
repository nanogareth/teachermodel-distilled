"""Setup workflow auto steps (workflow-automation-design §7; plan Task 8). Fictional data only."""

import copy
import email
import email.policy
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from privacy_helpers import cover_roster, edit_yaml, make_privacy_root, prerequisite_events

from teachermodel import config, events, privacy, setup, signoff
from teachermodel.bridge import SYSTEM_ACTOR
from teachermodel.rules import Clearance
from teachermodel.standards import ROOT, validate
from teachermodel.workflow import PROGRAMME

NOW = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
EXAMPLE_ROSTER = ROOT / "standards" / "templates" / "roster.example.yaml"
SETTINGS = {
    "schema": "tm:contract/settings@1",
    "library": "TeacherModel Private",
    "mailbox": "signoffs@example.com",
    "it_email": "it.requests@example.com",
    "dpo_email": "dpo@example.com",
    "notice_version": "2026-11",
}
SEPARATION = "Option 1. Records stay with the training function; performance reviews receive clearance status, not scores."
OWNER = "tm:person/owner-1"


def roster_doc():
    return yaml.safe_load(EXAMPLE_ROSTER.read_text(encoding="utf-8"))


def write_roster(path: Path, doc) -> Path:
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def private(tmp_path):
    p = tmp_path / "private"
    p.mkdir()
    return p


@pytest.fixture
def accepted_0005(tmp_path):
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "0005-performance-management-separation.md").write_text(
        "---\nstatus: accepted\ndate: 2026-11-01\nsupersedes: null\n---\n"
        "# 0005 Separation from employment performance management\n\n"
        f"## Context\nFictional.\n\n## Decision\n{SEPARATION}\n\n## Consequences\nNone.\n",
        encoding="utf-8",
    )
    return d


CATEGORY_IDS = [c["id"] for c in setup.data_categories()]


def retention_entries(months):
    """Fictional placeholders, one per data category (not advice, not proposals); [] when months is None."""
    if months is None:
        return []
    return [
        {"category": cid, "purpose": "tm:purpose/test-clearance", "period_months": months,
         "starts": "The engagement ends.", "reason": f"Fictional reason for keeping {cid} that long.",
         "basis": "legitimate-interests"}
        for cid in CATEGORY_IDS
    ]


def retention_file(tmp_path, value):
    doc = yaml.safe_load((ROOT / "standards" / "retention.yaml").read_text(encoding="utf-8"))
    doc["entries"] = retention_entries(value)
    path = tmp_path / "retention.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def check_all(evs):
    for e in evs:
        assert events.check_event(e) == [], e
    return evs


def kinds(evs):
    return [e["kind"] for e in evs]


def parse_eml(path: Path):
    return email.message_from_bytes(path.read_bytes(), policy=email.policy.default)


def signoff_event(step, inputs, *, decision="approve", at="2026-10-24T10:00:00+00:00", sid="a" * 16):
    """The sign-off a page for `step` would produce for `inputs` (the dict the page shows)."""
    payload = {
        "step": step, "decision": decision, "fields_sha256": "c" * 64, "input_sha256": signoff.input_sha256(inputs),
        "signoff_id": sid, "page_template_sha256": "b" * 64, "signed_at": at,
    }
    return events.make_event("signoff", PROGRAMME, OWNER, payload, at=at)


def profile_sha(root):
    path, _ = privacy.base_profile(root)
    return privacy.profile_inputs(path, root)["sha256"]


def verified(root, at="2026-10-24T07:00:00+00:00", sid="e" * 16):
    """Legal's verification of the base profile in `root`, as the page would have hashed it."""
    path, _ = privacy.base_profile(root)
    return signoff_event(privacy.STEP_BASE_PROFILE_VERIFIED, privacy.profile_inputs(path, root), at=at, sid=sid)


def retention_approval(root, ret=None, decision="approve", at="2026-10-24T08:00:00+00:00", sid="a" * 16):
    """The head of training's approval of the retention entries in `root` (or of the document `ret`)."""
    ret = ret or setup.load_retention(root / "standards" / "retention.yaml", root)
    inputs = privacy.retention_inputs(root, ret, [verified(root)])
    return signoff_event(setup.STEP_RETENTION_APPROVED, inputs, decision=decision, at=at, sid=sid)


def ready_log(root):
    """What the notice step and the roster import need: the library check, the profile verified, the DPIA cleared and
    retention approved."""
    return prerequisite_events(root)


def do_import(private, root, roster, log=(), now=NOW):
    """setup.import_roster for the fictional privacy root, with the prerequisites of the lock in the log."""
    return setup.import_roster(private, roster, [*ready_log(root), *log], now, root=root)


def approve(root, text, at="2026-10-24T10:00:00+00:00", sid="d" * 16):
    """The owner's approval of the notice `text` against the base profile of `root`."""
    inputs = setup.notice_inputs(text, "2026-11", profile_sha(root), setup.retention_digest(root, ready_log(root)))
    return signoff_event(setup.STEP_NOTICE_APPROVED, inputs, at=at, sid=sid)


def rendered_notice(private, root):
    evs = setup.notice_text(private, ready_log(root), SETTINGS, NOW, root=root)
    assert kinds(evs) == ["step"], evs
    return evs, (private / evs[0]["payload"]["output"]).read_text(encoding="utf-8")


# --- settings, roles, retention -----------------------------------------------------------------


def test_load_settings_validates(private):
    with pytest.raises(setup.SetupError, match="settings.yaml"):
        setup.load_settings(private)
    (private / "settings.yaml").write_text(yaml.safe_dump({**SETTINGS, "mailbox": "not-an-email"}), encoding="utf-8")
    with pytest.raises(setup.SetupError, match="mailbox"):
        setup.load_settings(private)
    (private / "settings.yaml").write_text(yaml.safe_dump(SETTINGS), encoding="utf-8")
    assert setup.load_settings(private) == SETTINGS


def test_role_sees_covers_every_role():
    assert set(setup.ROLE_SEES) == set(config.ROLES)
    assert setup.ROLE_SEES["instructor"]["sees"] == "Their own record only"


def test_real_retention_file_is_a_v2_draft_with_no_entries_yet():
    doc = yaml.safe_load((ROOT / "standards" / "retention.yaml").read_text(encoding="utf-8"))
    assert validate(doc, "retention.schema.json") == []
    assert doc["schema_version"] == 2 and doc["status"] == "draft" and doc["entries"] == []


def test_retention_schema_rejects_bad_entries():
    doc = {"schema_version": 2, "status": "draft", "basis": "test", "entries": retention_entries(24)}
    assert validate(doc, "retention.schema.json") == []
    bad = [{**doc["entries"][0], "period_months": -1}, *doc["entries"][1:]]
    assert validate({**doc, "entries": bad}, "retention.schema.json")


def test_load_retention_refuses_an_unknown_category(tmp_path):
    path = retention_file(tmp_path, 24)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["entries"][0]["category"] = "observations"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(setup.SetupError, match="unknown data category 'observations'"):
        setup.load_retention(path)


def test_load_retention_refuses_a_repeated_category_and_purpose(tmp_path):
    path = retention_file(tmp_path, 24)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["entries"].append(dict(doc["entries"][0]))
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(setup.SetupError, match="more than one entry"):
        setup.load_retention(path)
    doc["entries"][-1]["jurisdiction"] = "tm:jurisdiction/us-ca"  # an overlay entry is a different rule
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert len(setup.load_retention(path)["entries"]) == 7


# --- IT request and ROPA ------------------------------------------------------------------------


def test_it_request_names_0006_settings(private):
    evs = check_all(setup.it_request(private, [], SETTINGS, NOW))
    assert kinds(evs) == ["step"]
    ev = evs[0]
    assert ev["actor"] == SYSTEM_ACTOR and ev["subject_uri"] == PROGRAMME
    assert ev["payload"]["step"] == "tm:step/it-request"
    assert ev["payload"]["output"] == "generated/it-request.md"
    md = (private / "generated" / "it-request.md").read_bytes()
    assert ev["payload"]["output_sha256"] == hashlib.sha256(md).hexdigest()
    text = md.decode("utf-8")
    for needle in ("TeacherModel Private", "security group", "sharing links", "audit log", "versioning",
                   "nightly copy"):
        assert needle.lower() in text.lower(), needle


def test_ropa_categories_follow_schema(private, tmp_path):
    root = tmp_path / "root"
    for part in ("contracts", "standards", "docs"):
        shutil.copytree(ROOT / part, root / part)
    schema_path = root / "contracts" / "roster.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    inst = schema["$defs"]["instructor"]["properties"]
    inst["on_call_rota"] = {"type": "string", "description": "Fictional new field"}
    inst["identity"]["properties"]["pronouns"] = {"type": "string"}
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    check_all(setup.ropa(private, [], SETTINGS, NOW, root=root))
    text = (private / "generated" / "ropa.md").read_text(encoding="utf-8")
    assert "on_call_rota" in text and "pronouns" in text
    identity = text.split("### Identity data", 1)[1].split("###", 1)[0]
    assert "pronouns" in identity and "on_call_rota" not in identity

    # known-negative: the real schema has neither field
    real = tmp_path / "real"
    real.mkdir()
    setup.ropa(real, [], SETTINGS, NOW)
    real_text = (real / "generated" / "ropa.md").read_text(encoding="utf-8")
    assert "on_call_rota" not in real_text and "pronouns" not in real_text
    for needle in ("hr_ref", "scores", "evidence_ref", "level_change", "Their own record only",
                   "TeacherModel Private", "No retention entries yet"):
        assert needle in real_text, needle


# --- notice text --------------------------------------------------------------------------------


def test_notice_refused_while_0005_open(private, tmp_path):
    d = tmp_path / "decisions-open"
    d.mkdir()
    (d / "0005-performance-management-separation.md").write_text(
        "---\nstatus: proposed\ndate: 2026-10-23\nsupersedes: null\n---\n# 0005 x\n\n## Decision\nOpen.\n",
        encoding="utf-8",
    )
    evs = check_all(setup.notice_text(private, [], SETTINGS, NOW, decisions_dir=d))
    assert kinds(evs) == ["check"]
    p = evs[0]["payload"]
    assert p["step"] == "tm:step/notice-text" and p["result"] == "blocked"
    assert any("0005" in r and "proposed" in r for r in p["reasons"])
    assert not (private / "generated" / "notice-2026-11.md").exists()


def test_notice_refused_null_retention(private, accepted_0005, tmp_path):
    evs = setup.notice_text(private, [], SETTINGS, NOW, decisions_dir=accepted_0005,
                            retention_path=retention_file(tmp_path, None))
    assert kinds(evs) == ["check"]
    reasons = evs[0]["payload"]["reasons"]
    assert any("no retention entries" in r for r in reasons)
    assert not any("0005" in r for r in reasons)


def test_notice_renders_when_unblocked(private, privacy_root):
    evs, text = rendered_notice(private, privacy_root)
    check_all(evs)
    p = evs[0]["payload"]
    assert p["output"] == "generated/notice-2026-11.md"
    assert p["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert not any(line.startswith("DRAFT") for line in text.splitlines())  # a finished template has no banner
    _, separation, _ = setup._decision(privacy_root / "docs" / "decisions", "0005")
    assert separation in text
    assert "24 months" in text and "not set" not in text
    assert "Their own record only" in text and "appeal" in text
    assert "<!--" not in text


# --- emails -------------------------------------------------------------------------------------


def test_eml_has_x_unsent_and_tag(private, privacy_root):
    cover_roster(privacy_root)  # one notice for every instructor of the example roster
    setup.it_request(private, [], SETTINGS, NOW)
    msg = parse_eml(private / "generated" / "it-request.eml")
    assert msg["X-Unsent"] == "1"
    assert msg["To"] == "it.requests@example.com"
    assert msg["Subject"] == "teachermodel private store request [tm-setup it-request]"
    # Outlook shows the HTML part: headings and lists, not markdown (owner, 2026-10-26); the plain part is the markdown.
    assert msg.get_content_type() == "multipart/alternative"
    page = msg.get_body(("html",)).get_content()
    assert "<h1" in page and "<ol>" in page and "# Request" not in page
    assert msg.get_body(("plain",)).get_content().replace("\r\n", "\n").startswith("# Request: private store")
    again = (private / "generated" / "it-request.eml").read_bytes()
    setup.it_request(private, [], SETTINGS, NOW)
    assert (private / "generated" / "it-request.eml").read_bytes() == again  # the boundary is not random

    log = do_import(private, privacy_root, EXAMPLE_ROSTER)
    _, text = rendered_notice(private, privacy_root)
    log.append(approve(privacy_root, text))
    drafts = check_all(setup.notice_drafts(private, log, SETTINGS, NOW, root=privacy_root))
    assert len(drafts) == 4 and all(d["kind"] == "step" for d in drafts)
    sme = next(d for d in drafts if d["subject_uri"] == "tm:instructor/k7m2q")
    assert sme["payload"]["output"] == "generated/notice-drafts/k7m2q.eml"
    msg = parse_eml(private / "generated" / "notice-drafts" / "k7m2q.eml")
    assert msg["X-Unsent"] == "1"
    assert msg["To"] == "sme.engineer@example.com"
    assert msg["Subject"] == "Privacy notice: instructor development [tm-notice 2026-11]"
    assert msg.get_body(("plain",)).get_content().replace("\r\n", "\n") == "Dear Example SME Engineer,\n\n" + text  # mail uses CRLF
    assert sme["payload"]["text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_notice_drafts_need_approved_hash(private, privacy_root):
    cover_roster(privacy_root)  # one notice for every instructor of the example roster
    log = do_import(private, privacy_root, EXAMPLE_ROSTER)
    _, text = rendered_notice(private, privacy_root)

    blocked = setup.notice_drafts(private, log, SETTINGS, NOW, root=privacy_root)
    assert kinds(blocked) == ["check"] and blocked[0]["payload"]["result"] == "blocked"

    wrong = approve(privacy_root, text + "edited\n")
    blocked = check_all(setup.notice_drafts(private, log + [wrong], SETTINGS, NOW, root=privacy_root))
    assert kinds(blocked) == ["check"]
    assert blocked[0]["payload"]["step"] == "tm:step/notice-drafts"
    assert not (private / "generated" / "notice-drafts").exists()

    # an approval of the right text against another profile is not an approval of this one
    other = signoff_event(setup.STEP_NOTICE_APPROVED, setup.notice_inputs(text, "2026-11", "f" * 64, "e" * 64))
    assert kinds(setup.notice_drafts(private, log + [other], SETTINGS, NOW, root=privacy_root)) == ["check"]

    right = approve(privacy_root, text)
    assert kinds(setup.notice_drafts(private, log + [right], SETTINGS, NOW, root=privacy_root)) == ["step"] * 4


# --- roster import ------------------------------------------------------------------------------


def test_import_writes_no_names_to_events(private, privacy_root):
    evs = check_all(do_import(private, privacy_root, EXAMPLE_ROSTER))
    assert kinds(evs).count("registration") == 4 and kinds(evs).count("level_change") == 4
    assert kinds(evs)[-1] == "step" and evs[-1]["payload"]["output"] == "identities/roster.yaml"
    base = next(e for e in evs if e["kind"] == "level_change" and e["subject_uri"] == "tm:instructor/k7m2q")
    assert base["payload"] == {"from": None, "to": "co-deliver", "basis": "roster baseline"}
    reg = next(e for e in evs if e["kind"] == "registration" and e["subject_uri"] == "tm:instructor/k7m2q")
    assert reg["payload"]["engagement"]["manager"] == "tm:person/eng-manager-1"
    assert reg["payload"]["roster_as_of"] == "2026-10-24"

    log_path = private / "events" / "events.jsonl"
    for e in evs:
        events.append(log_path, e)
    log_text = log_path.read_text(encoding="utf-8").lower()
    secrets = []
    for row in roster_doc()["instructors"]:
        secrets += [v for v in row["identity"].values()]
    assert secrets
    for s in secrets:
        assert s.lower() not in log_text, s
    ids = (private / "identities" / "roster.yaml").read_text(encoding="utf-8")
    assert all(s in ids for s in secrets)


def test_reimport_level_change_refused(private, privacy_root, tmp_path):
    log = do_import(private, privacy_root, EXAMPLE_ROSTER)
    before = (private / "identities" / "roster.yaml").read_bytes()
    doc = roster_doc()
    doc["instructors"][0]["level"] = "cleared"
    doc["instructors"][1]["identity"]["name"] = "Example Renamed Instructor"
    path = write_roster(tmp_path / "changed.yaml", doc)
    with pytest.raises(setup.SetupError, match="tm:instructor/k7m2q"):
        do_import(private, privacy_root, path, log, LATER)
    assert (private / "identities" / "roster.yaml").read_bytes() == before


def test_reimport_unchanged_is_noop(private, privacy_root, tmp_path):
    log = do_import(private, privacy_root, EXAMPLE_ROSTER)
    assert do_import(private, privacy_root, EXAMPLE_ROSTER, log, LATER) == []

    # known-positive: a changed non-level field gives one new registration and nothing else
    doc = roster_doc()
    doc["instructors"][1]["languages"] = ["en", "fr", "de"]
    again = do_import(private, privacy_root, write_roster(tmp_path / "langs.yaml", doc), log, LATER)
    assert kinds(again) == ["registration"]
    assert again[0]["subject_uri"] == "tm:instructor/p3x9d"
    assert again[0]["payload"]["languages"] == ["en", "fr", "de"]


def test_import_refuses_invalid_roster(private, privacy_root, tmp_path):
    doc = roster_doc()
    doc["instructors"][0]["level"] = "grand-master"
    with pytest.raises(setup.SetupError, match="level"):
        do_import(private, privacy_root, write_roster(tmp_path / "bad.yaml", doc))
    assert not (private / "identities").exists()


# --- gap list -----------------------------------------------------------------------------------


def test_gap_list_flags_uncleared_delivery(private, privacy_root):
    log = do_import(private, privacy_root, EXAMPLE_ROSTER)
    evs = check_all(setup.gap_list(private, log, SETTINGS, NOW))
    assert kinds(evs) == ["step"] and evs[0]["payload"]["output"] == "generated/gap-list.json"
    rows = json.loads((private / "generated" / "gap-list.json").read_text(encoding="utf-8"))["rows"]
    keys = {r["key"] for r in rows}
    assert len(rows) == 5  # k7m2q: 2 modes; p3x9d: 3 modes; c5w1t and r8n4h deliver nothing
    assert "tm:instructor/p3x9d sl:unit/example-agent-loop@1 remote" in keys
    assert all(r["changed"] is True for r in rows)
    blob = json.dumps(rows).lower()
    for row in roster_doc()["instructors"]:
        assert row["identity"]["name"].lower() not in blob

    # a valid clearance removes that row; the remaining rows were in the previous output
    cleared = Clearance(id="tm:clearance/x1", instructor="tm:instructor/p3x9d", unit="sl:unit/example-agent-loop@1",
                        modes=("remote",), outcome="cleared", issued=NOW.date().replace(month=1),
                        expires=NOW.date().replace(year=2027))
    log += evs
    evs = setup.gap_list(private, log, SETTINGS, LATER, clearances=[cleared])
    assert kinds(evs) == ["step"]
    rows = json.loads((private / "generated" / "gap-list.json").read_text(encoding="utf-8"))["rows"]
    assert len(rows) == 4 and "tm:instructor/p3x9d sl:unit/example-agent-loop@1 remote" not in {r["key"] for r in rows}
    assert all(r["changed"] is False for r in rows)


# --- idempotency --------------------------------------------------------------------------------


def test_auto_steps_idempotent(private, privacy_root):
    cover_roster(privacy_root)  # one notice for every instructor of the example roster
    log = ready_log(privacy_root)
    log += setup.it_request(private, log, SETTINGS, NOW)
    log += setup.ropa(private, log, SETTINGS, NOW, root=privacy_root)
    log += setup.notice_text(private, log, SETTINGS, NOW, root=privacy_root)
    log += setup.import_roster(private, EXAMPLE_ROSTER, log, NOW, root=privacy_root)
    log += setup.gap_list(private, log, SETTINGS, NOW)
    text = (private / "generated" / "notice-2026-11.md").read_text(encoding="utf-8")
    log.append(approve(privacy_root, text))
    log += setup.notice_drafts(private, log, SETTINGS, NOW, root=privacy_root)
    assert kinds(log).count("step") == 1 + 1 + 1 + 1 + 1 + 4

    assert setup.it_request(private, log, SETTINGS, LATER) == []
    assert setup.ropa(private, log, SETTINGS, LATER, root=privacy_root) == []
    assert setup.notice_text(private, log, SETTINGS, LATER, root=privacy_root) == []
    assert setup.import_roster(private, EXAMPLE_ROSTER, log, LATER, root=privacy_root) == []
    assert setup.gap_list(private, log, SETTINGS, LATER) == []
    assert setup.notice_drafts(private, log, SETTINGS, LATER, root=privacy_root) == []

    # a blocked step reports once, not on every run
    blocked = setup.notice_text(private, [], SETTINGS, NOW, root=privacy_root)
    assert setup.notice_text(private, blocked, SETTINGS, LATER, root=privacy_root) == []

    # known-positive: a changed setting re-renders the IT request
    changed = {**SETTINGS, "library": "TeacherModel Records"}
    assert kinds(setup.it_request(private, log, changed, LATER)) == ["step"]


# --- verification and retention approval gate the notice ------------------------------------------------------


def notice_reasons(private, root, log):
    evs = setup.notice_text(private, log, SETTINGS, NOW, root=root)
    return kinds(evs), (evs[0]["payload"].get("reasons", []) if evs[0]["kind"] == "check" else [])


def test_notice_blocked_until_the_profile_is_verified(private, privacy_root):
    assert notice_reasons(private, privacy_root, [retention_approval(privacy_root)]) == (
        ["check"], ["base profile not verified"])
    # a verification that does not approve counts for nothing
    no = verified(privacy_root)
    no["payload"]["decision"] = "changes"
    assert notice_reasons(private, privacy_root, [no, retention_approval(privacy_root)])[1] == [
        "base profile not verified"]
    assert not (private / "generated" / "notice-2026-11.md").exists()
    assert notice_reasons(private, privacy_root, ready_log(privacy_root))[0] == ["step"]


def test_notice_blocked_until_the_periods_are_approved(private, privacy_root):
    assert notice_reasons(private, privacy_root, [verified(privacy_root)]) == (["check"], ["retention not approved"])
    # a sign-off that does not approve counts for nothing
    no = retention_approval(privacy_root, decision="changes")
    assert notice_reasons(private, privacy_root, [verified(privacy_root), no])[1] == ["retention not approved"]
    assert not (private / "generated" / "notice-2026-11.md").exists()


def test_notice_blocked_when_the_periods_changed_after_approval(private, privacy_root):
    log = ready_log(privacy_root)
    edit_yaml(privacy_root / "standards" / "retention.yaml", lambda d: d["entries"][0].__setitem__("period_months", 36))
    assert notice_reasons(private, privacy_root, log) == (["check"], ["retention not approved"])


def test_notice_blocked_when_the_profile_changed_after_approval(private, privacy_root):
    log = ready_log(privacy_root)
    path, _ = privacy.base_profile(privacy_root)
    path.write_bytes(path.read_bytes() + b"# edited after verification\n")
    kinds_, reasons = notice_reasons(private, privacy_root, log)
    assert kinds_ == ["check"] and "base profile not verified" in reasons and "retention not approved" in reasons


def test_the_latest_approving_retention_signoff_decides(private, privacy_root):
    old = retention_approval(privacy_root, at="2026-10-24T08:00:00+00:00", sid="a" * 16)
    edit_yaml(privacy_root / "standards" / "retention.yaml", lambda d: d["entries"][0].__setitem__("period_months", 36))
    new = retention_approval(privacy_root, at="2026-10-24T09:00:00+00:00", sid="b" * 16)
    assert notice_reasons(private, privacy_root, [verified(privacy_root), old, new])[0] == ["step"]
    assert notice_reasons(private, privacy_root, [verified(privacy_root), new, old])[1] == ["retention not approved"]


def test_no_entries_report_only_the_empty_reason(private, tmp_path):
    root = make_privacy_root(tmp_path / "empty", entries="empty")
    reasons = notice_reasons(private, root, [verified(root)])[1]
    assert reasons and all("no retention entries" in r for r in reasons)


def test_a_missing_pair_is_named_and_not_reported_as_unapproved(private, privacy_root):
    edit_yaml(privacy_root / "standards" / "retention.yaml", lambda d: d.__setitem__("entries", d["entries"][:-1]))
    reasons = notice_reasons(private, privacy_root, [verified(privacy_root)])[1]
    assert reasons == ["no base retention entry for delivery-data / tm:purpose/test-reuse"]


def test_a_purpose_without_a_proposed_basis_is_named(private, privacy_root):
    edit_yaml(privacy_root / "standards" / "privacy" / "purposes.yaml",
              lambda d: d["purposes"][1].pop("proposed_basis"))
    reasons = notice_reasons(private, privacy_root, ready_log(privacy_root))[1]
    assert reasons == ["purpose tm:purpose/test-reuse has no proposed basis for tm:jurisdiction/xx"]


def test_notice_and_ropa_state_each_entry_with_its_reason(private, privacy_root):
    _, text = rendered_notice(private, privacy_root)
    assert "performance-data" in text or "Performance data" in text
    assert "24 months" in text and "Fictional reason for keeping performance-data that long." in text
    assert "The engagement ends." in text and "not set" not in text
    other = private.parent / "ropa"
    other.mkdir()
    ropa = setup.ropa(other, [], SETTINGS, NOW, root=privacy_root)
    assert "Fictional reason for keeping performance-data that long." in (other / ropa[0]["payload"]["output"]).read_text(
        encoding="utf-8")


def test_an_event_ended_entry_reads_as_until_that_event(tmp_path):
    path = retention_file(tmp_path, 24)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = doc["entries"][0]
    entry.pop("period_months")
    entry["until_event"] = "the instructor asks for deletion"
    entry["jurisdiction"] = "tm:jurisdiction/us-ca"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    md = setup._retention_md(setup.load_retention(path), setup.data_categories())
    assert "until the instructor asks for deletion" in md and "tm:jurisdiction/us-ca" in md


def test_ropa_renders_whatever_the_approvals(private, tmp_path):
    retention = retention_file(tmp_path, 24)
    assert kinds(setup.ropa(private, [], SETTINGS, NOW, retention_path=retention)) == ["step"]
    other = tmp_path / "again"
    other.mkdir()
    assert kinds(setup.ropa(other, [verified(ROOT)], SETTINGS, NOW, retention_path=retention)) == ["step"]
    # a changed retention file is no reason to block it: the entry shows the periods as set
    third = tmp_path / "third"
    third.mkdir()
    assert kinds(setup.ropa(third, [], SETTINGS, NOW, retention_path=retention_file(third, 36))) == ["step"]


def test_ropa_lists_purposes_with_every_proposed_basis_and_the_base_profile(private):
    ropa = setup.ropa(private, [], SETTINGS, NOW)
    text = (private / ropa[0]["payload"]["output"]).read_text(encoding="utf-8")
    assert "Clearance decision" in text and "tm:purpose/clearance-decision" in text
    assert "Proposed basis, " in text and "tm:jurisdiction/us-ca" in text and "disclosed purpose" in text
    assert "Base profile tm:jurisdiction/ie" in text and "General Data Protection Regulation" in text
    assert "Data categories: Identity data" in text


def test_legal_role_sees_profiles_and_the_processing_record_not_instructor_records():
    row = setup.ROLE_SEES["legal"]
    assert "privacy profile" in row["sees"] and "processing" in row["sees"]
    assert "no instructor records" in row["sees"].lower()
    assert row["source"] == (setup.PRIVACY_DESIGN, "2")


def test_data_categories_have_stable_ids():
    cats = setup.data_categories()
    assert [c["id"] for c in cats] == [
        "identity-data", "pseudonymous-identifier", "employment-and-training-data", "delivery-data",
        "performance-data", "record-of-actions",
    ]
    assert len({c["id"] for c in cats}) == len(cats)
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9-]*", c["id"]) for c in cats)
    assert [c["title"] for c in cats][0] == "Identity data" and "Record of actions" in {c["title"] for c in cats}
