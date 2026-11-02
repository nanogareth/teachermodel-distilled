"""Orchestration over a fictional private store (plan Task 9). Fictional people only."""

import json
import re
import shutil as _shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from privacy_helpers import (
    STEP_DPIA,
    STEP_ROPA_APPROVED,
    STEP_RETENTION,
    STEP_VERIFIED,
    import_roster_ungated,
    ready_for_roster,
    seed_check,
    sign_step,
)

from teachermodel import app, bridge, events, setup, signoff
from teachermodel.flows.onboarding import LEVEL_STEP
from teachermodel.standards import ROOT, validate

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
SME = "tm:instructor/k7m2q"
PARTNER = "tm:instructor/r8n4h"
ALL_DRIVERS = ("connector", "graph", "fixture")
IT_PAGE = "it-done--teachermodel--it-1.html"
DPO_PAGE = "dpia-screening--teachermodel--dpo-1.html"
VERIFY_PAGE = "base-profile-verified--teachermodel--legal-1.html"
ROPA_PAGE = "ropa-approved--teachermodel--dpo-1.html"


def tm_data(page_path) -> dict:
    page = page_path.read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="tm-data">(.*?)</script>', page, re.S)
    assert m, "no tm-data block"
    return json.loads(m.group(1))


def event_steps(private, kind="step"):
    return [e["payload"].get("step") for e in app.read_events(private) if e["kind"] == kind]


def queue(private, now=T0):
    return app.do_next(private, now=now).lines


def test_load_state_empty_log(fictional_store):
    st = app.load_state(fictional_store)
    assert st.events == [] and st.roster is None
    assert set(st.subjects) == {"tm:programme/teachermodel"}
    assert st.identities["pat.it@example.com"][0]["roles"] == {"it"}
    assert st.settings["notice_version"] == "2026-11"


def test_tick_runs_auto_steps_and_writes_pages(fictional_store):
    reports = app.do_tick(fictional_store, now=T0)
    assert [r.summary.split(":")[0] for r in reports] == ["run", "plan", "pages", "next"]
    steps = event_steps(fictional_store)
    assert "tm:step/it-request" in steps and "tm:step/ropa" in steps
    assert (fictional_store / "generated" / "it-request.eml").is_file()
    lines = queue(fictional_store)
    assert len(lines) == 3
    assert "tm:step/it-done" in lines[0]
    assert any("tm:step/base-profile-verified" in ln for ln in lines) and any("tm:step/ropa-approved" in ln for ln in lines)
    pages = sorted(p.name for p in (fictional_store / "pages").glob("*.html"))
    assert pages == [VERIFY_PAGE, IT_PAGE, ROPA_PAGE]
    for page in (VERIFY_PAGE, IT_PAGE, ROPA_PAGE):
        assert (fictional_store / "pages" / page.replace(".html", ".input.json")).is_file()


def test_run_is_idempotent(fictional_store):
    app.do_run(fictional_store, now=T0)
    first = len(app.read_events(fictional_store))
    app.do_run(fictional_store, now=T0 + timedelta(hours=1))
    assert len(app.read_events(fictional_store)) == first


def test_plan_writes_latest_files(fictional_store):
    app.do_plan(fictional_store, now=T0)  # empty log: look back from today
    plans = fictional_store / "plans"
    plan = json.loads((plans / "latest.json").read_text(encoding="utf-8"))
    assert validate(plan, "plan.schema.json") == []
    digest = (plans / "latest.sha256").read_text(encoding="ascii").strip()
    assert digest == bridge.plan_sha256(plan)
    assert (plans / "20261026T080000Z.json").is_file()
    assert [o["op"] for o in plan["ops"]] == ["mail.tagged"]
    assert plan["ops"][0]["args"]["since"] == "2026-10-26"
    app.do_run(fictional_store, now=T0)
    app.do_plan(fictional_store, now=T0 + timedelta(hours=1))
    plan2 = json.loads((plans / "latest.json").read_text(encoding="utf-8"))
    assert plan2["ops"][0]["args"]["since"] == "2026-10-25"  # one day before the first event


def test_run_reports_roster_waiting_when_due(fictional_store, privacy_root):
    # roster-import needs library-exists, the verified base profile, the DPIA and the retention approval
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    seed_check(fictional_store, "tm:step/library-exists")
    for step in (STEP_VERIFIED, STEP_DPIA, STEP_RETENTION):
        sign_step(fictional_store, privacy_root, step)
    rep = app.do_run(fictional_store, now=T0, root=privacy_root)
    assert any(line.startswith("waiting: run teachermodel import-roster") for line in rep.lines)


def test_import_roster_copies_and_registers(fictional_store, privacy_root, example_roster):
    ready_for_roster(fictional_store, privacy_root)
    rep = app.do_import_roster(fictional_store, example_roster, now=T0, root=privacy_root)
    assert "import-roster:" in rep.summary
    assert [p.name for p in (fictional_store / "imports").iterdir()] == ["roster-20261026T080000Z.yaml"]
    assert (fictional_store / "identities" / "roster.yaml").is_file()
    st = app.load_state(fictional_store, privacy_root)
    assert {SME, PARTNER} <= set(st.subjects)
    assert st.registrations[SME]["engagement"]["manager"] == "tm:person/eng-manager-1"
    assert "sme.engineer@example.com" in st.identities
    again = app.do_import_roster(fictional_store, example_roster, now=T0 + timedelta(hours=1), root=privacy_root)
    assert "0 event(s)" in again.summary


def test_pages_one_per_signer(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    st = app.load_state(fictional_store)
    specs = app.PAGE_SPECS["tm:step/shadow-delivery"](st, PARTNER)
    assert sorted(s["signer"] for s in specs) == ["tm:person/coord-1", "tm:person/coord-2"]
    assert len({app.page_stem(s["step"], s["subject_uri"], s["signer"]) for s in specs}) == 2
    assert {f["name"] for f in specs[0]["fields"]} == {"date", "delivery_ref", "note"}


def test_commitment_page_signer_comes_from_registration(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    st = app.load_state(fictional_store)
    (spec,) = app.PAGE_SPECS["tm:step/commitment-manager"](st, SME)
    assert spec["signer"] == "tm:person/eng-manager-1" and spec["role"] == "manager"
    assert spec["inputs"]["engagement"]["protected_hours_per_month"] == 16
    (lead,) = app.PAGE_SPECS["tm:step/commitment-partner-lead"](st, PARTNER)
    assert lead["signer"] == "tm:person/partner-lead-1"
    st.people = [p for p in st.people if "manager" not in p["roles"]]
    with pytest.raises(app.PageProblem, match="role manager"):
        app.PAGE_SPECS["tm:step/commitment-manager"](st, SME)


def test_self_assessment_signer_is_the_instructor(fictional_store, example_roster):
    import_roster_ungated(fictional_store, example_roster, T0)
    st = app.load_state(fictional_store)
    (spec,) = app.PAGE_SPECS["tm:step/baseline-self-assessment"](st, SME)
    assert spec["signer"] == SME and spec["template"] == "self_assessment"
    assert len(spec["fields"]) >= 2


def test_every_human_step_has_a_page_builder():
    wf = app.load_standards()["workflows"]
    human = {st["id"] for w in wf["workflows"] for st in w["steps"] if st["type"] == "human"}
    assert human == set(app.PAGE_SPECS)


# --- ingest -----------------------------------------------------------------------------------


def signed_receipt(private, *, now=T0, **overrides):
    """A receipt carrying the IT person's sign-off of tm:step/it-done, built from the generated page."""
    page = tm_data(private / "pages" / IT_PAGE)
    doc = {
        "schema": "tm:contract/signoff@1",
        "id": "0123456789abcdef",
        "step": page["step"],
        "subject_uri": page["subject_uri"],
        "input_sha256": page["input_sha256"],
        "decision": "approve",
        "fields": {},
        "signer": page["signer"],
        "signed_at": (now + timedelta(minutes=30)).isoformat(),
        "page_template_sha256": page["page_template_sha256"],
    } | overrides
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    (tagged,) = [o for o in plan["ops"] if o["op"] == "mail.tagged"]
    msg = {"sender": "pat.it@example.com", "subject": "[tm-signoff 0123456789abcdef]",
           "received": (now + timedelta(minutes=40)).isoformat(),
           "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]}
    receipt = {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": (private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
        "driver": "fixture",
        "run_at": (now + timedelta(hours=1)).isoformat(),
        "results": [{"op_id": tagged["op_id"], "status": "ok", "data": {"messages": [msg]}}],
    }
    path = private / "receipts" / "r1.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_ingest_receipt_end_to_end(fictional_store, fictional_names):
    app.do_tick(fictional_store, now=T0)
    assert any("tm:step/it-done" in line for line in queue(fictional_store))
    path = signed_receipt(fictional_store)
    later = T0 + timedelta(hours=2)
    rep = app.do_ingest(fictional_store, path, now=later, allowed_drivers=ALL_DRIVERS)
    assert rep.ok and "1 signoff" in rep.summary and "0 rejected" in rep.summary
    after = queue(fictional_store, now=later)
    assert not any("tm:step/it-done" in line for line in after)
    assert any("tm:step/library-exists" in line for line in after)
    stored = json.loads((fictional_store / "signoffs" / "0123456789abcdef.json").read_text(encoding="utf-8"))
    assert stored["signer"] == "tm:person/it-1"
    raw = (fictional_store / app.EVENT_LOG).read_text(encoding="utf-8")
    for needle in fictional_names:
        assert needle not in raw
    # replaying the same receipt changes nothing
    again = app.do_ingest(fictional_store, path, now=later, allowed_drivers=ALL_DRIVERS)
    assert "0 event(s)" in again.summary
    assert event_steps(fictional_store, "signoff") == ["tm:step/it-done"]


def test_ingest_rejects_stale_input(fictional_store):
    app.do_tick(fictional_store, now=T0)
    path = signed_receipt(fictional_store, input_sha256="0" * 64)
    later = T0 + timedelta(hours=2)
    rep = app.do_ingest(fictional_store, path, now=later, allowed_drivers=ALL_DRIVERS)
    assert "1 rejected" in rep.summary and any("stale" in line for line in rep.lines)
    assert event_steps(fictional_store, "signoff") == []
    assert any("tm:step/it-done" in line for line in queue(fictional_store, now=later))


def test_fixture_driver_refused_by_default(fictional_store):
    app.do_tick(fictional_store, now=T0)
    path = signed_receipt(fictional_store)
    rep = app.do_ingest(fictional_store, path, now=T0 + timedelta(hours=2))
    assert rep.ok is False and event_steps(fictional_store, "signoff") == []


def test_direct_signoff_refused(fictional_store):
    app.do_tick(fictional_store, now=T0)
    page = tm_data(fictional_store / "pages" / IT_PAGE)
    direct = fictional_store / "direct.json"
    direct.write_text(json.dumps({"schema": "tm:contract/signoff@1", "id": "0123456789abcdef",
                                  "step": page["step"]}), encoding="utf-8")
    with pytest.raises(app.AppError, match="sign-offs arrive only via a receipt"):
        app.do_ingest(fictional_store, direct, now=T0)
    assert event_steps(fictional_store, "signoff") == []


def test_ingest_unknown_plan_refused(fictional_store):
    app.do_tick(fictional_store, now=T0)
    receipt = {"schema": "tm:contract/receipt@1", "plan_sha256": "0" * 64, "driver": "connector",
               "run_at": T0.isoformat(), "results": []}
    path = fictional_store / "receipts" / "x.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(app.AppError, match="no plan"):
        app.do_ingest(fictional_store, path, now=T0)


def test_ingest_needs_exactly_one_owner(fictional_store):
    app.do_tick(fictional_store, now=T0)
    path = signed_receipt(fictional_store)
    people = fictional_store / "identities" / "people.yaml"
    people.write_text(people.read_text(encoding="utf-8").replace("programme-owner", "coordinator"), encoding="utf-8")
    with pytest.raises(app.AppError, match="programme-owner"):
        app.do_ingest(fictional_store, path, now=T0 + timedelta(hours=2), allowed_drivers=ALL_DRIVERS)


def test_queue_schema_rejects_extra_fields():
    doc = app.queue_document([], T0)
    assert validate(doc, "queue.schema.json", ROOT) == []
    assert validate({**doc, "items": [{"step": "tm:step/x", "name": "Pat"}]}, "queue.schema.json", ROOT)


# --- level change on decision; inputs re-derived at ingest -------------------------------------


def page_receipt(private, page_name, sender, *, sid, now=T0, name="r2.json", **overrides):
    """A receipt carrying one sign-off built from the generated page `page_name`, mailed by `sender`."""
    page = tm_data(private / "pages" / page_name)
    answers = {}
    if page["template"] == "batch_approve":  # what the page produces when every row is approved
        answers = {"rows": {r["key"]: "approve" for r in page["inputs"]["rows"]}}
    doc = {
        "schema": "tm:contract/signoff@1", "id": sid, "step": page["step"], "subject_uri": page["subject_uri"],
        "input_sha256": page["input_sha256"], "decision": "approve", "fields": answers, "signer": page["signer"],
        "signed_at": (now + timedelta(minutes=30)).isoformat(),
        "page_template_sha256": page["page_template_sha256"],
    } | overrides
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    (tagged,) = [o for o in plan["ops"] if o["op"] == "mail.tagged"]
    msg = {"sender": sender, "subject": f"[tm-signoff {sid}]", "received": (now + timedelta(minutes=40)).isoformat(),
           "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]}
    receipt = {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": (private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
        "driver": "fixture", "run_at": (now + timedelta(hours=1)).isoformat(),
        "results": [{"op_id": tagged["op_id"], "status": "ok", "data": {"messages": [msg]}}],
    }
    path = private / "receipts" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def seed_signoffs(private, subject, *steps):
    for step in steps:
        events.append(private / app.EVENT_LOG, events.make_event(
            "signoff", subject, "tm:person/seed", {"step": step, "decision": "approve"},
            at="2026-10-25T08:00:00+00:00"))


LEAD_PAGE = "lead-observed-level--k7m2q--hot-1.html"
HEAD = "hal.head@example.com"
LATER = T0 + timedelta(hours=2)


def lead_ready(private, roster):
    import_roster_ungated(private, roster, T0)
    seed_signoffs(private, SME, "tm:step/co-delivery", "tm:step/commitment-manager")
    app.do_tick(private, now=T0)


def level_changes(private, uri=SME):
    return [e for e in app.read_events(private) if e["kind"] == "level_change" and e["subject_uri"] == uri]


def test_lead_observed_approval_appends_level_change(fictional_store, example_roster):
    lead_ready(fictional_store, example_roster)
    assert [e["payload"]["to"] for e in level_changes(fictional_store)] == ["co-deliver"]
    path = page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="aaaaaaaaaaaaaaaa")
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 level_change" in rep.summary and "1 signoff" in rep.summary
    assert app.current_level(app.load_state(fictional_store), SME) == "lead-observed"
    last = level_changes(fictional_store)[-1]
    assert last["payload"] == {"from": "co-deliver", "to": "lead-observed", "basis": "signoff aaaaaaaaaaaaaaaa"}
    assert last["actor"] == "tm:person/hot-1"
    assert events.verify(fictional_store / app.EVENT_LOG) == []
    before = app.read_events(fictional_store)
    again = app.do_ingest(fictional_store, path, now=LATER + timedelta(hours=1), allowed_drivers=ALL_DRIVERS)
    assert "0 event(s)" in again.summary
    assert app.read_events(fictional_store) == before


def test_level_change_event_id_derives_from_signoff_id(fictional_store, example_roster):
    lead_ready(fictional_store, example_roster)
    app.do_ingest(fictional_store, page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="bbbbbbbbbbbbbbbb"), now=LATER,
                  allowed_drivers=ALL_DRIVERS)
    first = level_changes(fictional_store)[-1]["id"]
    assert first == app.level_change_id("bbbbbbbbbbbbbbbb")
    assert app.level_change_id("cccccccccccccccc") != first


@pytest.mark.parametrize("overrides", [{"decision": "reject"}, {"input_sha256": "0" * 64}])
def test_no_level_change_without_an_approving_accepted_signoff(fictional_store, example_roster, overrides):
    lead_ready(fictional_store, example_roster)
    path = page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="dddddddddddddddd", **overrides)
    app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert app.current_level(app.load_state(fictional_store), SME) == "co-deliver"
    assert len(level_changes(fictional_store)) == 1  # only the roster baseline


def test_other_steps_do_not_change_level(fictional_store, example_roster):
    app.do_tick(fictional_store, now=T0)
    app.do_ingest(fictional_store, signed_receipt(fictional_store), now=LATER, allowed_drivers=ALL_DRIVERS)
    assert level_changes(fictional_store) == []


GAP_PAGE = "gap-list-approved--teachermodel--owner-1.html"
OWNER = "olive.owner@example.com"


def gap_ready(private, roster):
    import_roster_ungated(private, roster, T0)
    app.do_tick(private, now=T0)


def change_gap_list(private, tmp_path, roster):
    """Import a roster with one more delivery mode, then regenerate the gap list: a different row set."""
    doc = yaml.safe_load(roster.read_text(encoding="utf-8"))
    doc["instructors"][0]["delivers"][0]["modes"].append("remote")
    changed = tmp_path / "roster-changed.yaml"
    changed.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    import_roster_ungated(private, changed, T0 + timedelta(minutes=5))
    st = app.load_state(private)
    new = app.append_new(private, setup.gap_list(private, st.events, st.settings, T0 + timedelta(minutes=6),
                                                 rules=st.standards["rules"]))
    assert new, "the regenerated gap list must differ"


def test_input_change_after_pages_makes_signoff_stale(fictional_store, example_roster, tmp_path):
    gap_ready(fictional_store, example_roster)
    path = page_receipt(fictional_store, GAP_PAGE, OWNER, sid="eeeeeeeeeeeeeeee")  # signed from the old page
    change_gap_list(fictional_store, tmp_path, example_roster)  # no `pages` re-run
    sidecar = fictional_store / "pages" / GAP_PAGE.replace(".html", ".input.json")
    assert sidecar.is_file()  # the written record still says the old input
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 rejected" in rep.summary and any("stale" in line for line in rep.lines)
    assert event_steps(fictional_store, "signoff") == []


def test_regenerated_page_signoff_is_accepted(fictional_store, example_roster, tmp_path):
    gap_ready(fictional_store, example_roster)
    change_gap_list(fictional_store, tmp_path, example_roster)
    app.do_tick(fictional_store, now=T0 + timedelta(minutes=10))
    path = page_receipt(fictional_store, GAP_PAGE, OWNER, sid="ffffffffffffffff", now=T0 + timedelta(minutes=10))
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary


def test_ingest_without_builder_output_is_rejected(fictional_store):
    app.do_tick(fictional_store, now=T0)
    path = signed_receipt(fictional_store)
    (fictional_store / "generated" / "it-request.md").unlink()  # the IT page can no longer be rebuilt
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 rejected" in rep.summary and any("no current input" in line for line in rep.lines)
    assert event_steps(fictional_store, "signoff") == []


def test_ingest_ignores_a_tampered_sidecar(fictional_store):
    app.do_tick(fictional_store, now=T0)
    page = tm_data(fictional_store / "pages" / IT_PAGE)
    sidecar = fictional_store / "pages" / IT_PAGE.replace(".html", ".input.json")
    sidecar.write_text(json.dumps({"tampered": True}), encoding="utf-8")
    ok = signed_receipt(fictional_store, input_sha256=page["input_sha256"])  # the real hash still passes
    assert "1 signoff" in app.do_ingest(fictional_store, ok, now=LATER, allowed_drivers=ALL_DRIVERS).summary


# --- review fixes ------------------------------------------------------------------------------------

DANA = "dana.dpo@example.com"
PROGRAMME = "tm:programme/teachermodel"


def seed_library_exists(private):
    events.append(private / app.EVENT_LOG, events.make_event(
        "check", PROGRAMME, "tm:system/teachermodel", {"step": "tm:step/library-exists", "result": "ok"},
        at="2026-10-25T08:00:00+00:00"))


def dpia_receipt(private, dpo_decision, *, sid, name="r-dpia.json", **overrides):
    fields = {"dpo-decision": dpo_decision, "rationale": "fictional"} if dpo_decision else {}
    return page_receipt(private, DPO_PAGE, DANA, sid=sid, name=name, fields=fields, **overrides)


def dpia_ready(private):
    """The profile is verified (legal), the ROPA approved (DPO) and the DPIA page exists."""
    seed_library_exists(private)
    app.do_tick(private, now=T0)
    sign_step(private, ROOT, STEP_VERIFIED, at="2026-10-25T09:00:00+00:00")
    sign_step(private, ROOT, STEP_ROPA_APPROVED, at="2026-10-25T09:02:00+00:00")
    app.do_tick(private, now=T0)


@pytest.mark.parametrize("decision", ["dpia-required", "needs-more-information", None])
def test_dpia_required_or_undecided_does_not_unlock_roster_import(fictional_store, decision):
    dpia_ready(fictional_store)
    path = dpia_receipt(fictional_store, decision, sid="1111111111111111")
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 rejected" in rep.summary and any("DPIA required or undecided" in line for line in rep.lines)
    assert event_steps(fictional_store, "signoff") == [STEP_VERIFIED, STEP_ROPA_APPROVED]
    assert not any("tm:step/roster-import" in line for line in queue(fictional_store, now=LATER))
    assert any("tm:step/dpia-screening" in line for line in queue(fictional_store, now=LATER))


def test_dpia_not_required_unlocks_roster_import_once_retention_is_approved(fictional_store, privacy_root):
    seed_library_exists(fictional_store)
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    sign_step(fictional_store, privacy_root, STEP_VERIFIED, at="2026-10-25T09:00:00+00:00")
    sign_step(fictional_store, privacy_root, STEP_ROPA_APPROVED, at="2026-10-25T09:02:00+00:00")
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    assert not any("tm:step/roster-import" in line for line in app.do_next(fictional_store, now=T0, root=privacy_root).lines)
    rep = app.do_ingest(fictional_store, dpia_receipt(fictional_store, "dpia-not-required", sid="2222222222222222"),
                        now=LATER, allowed_drivers=ALL_DRIVERS, root=privacy_root)
    assert "0 rejected" in rep.summary and event_steps(fictional_store, "signoff") == [STEP_VERIFIED, STEP_ROPA_APPROVED, STEP_DPIA]
    still = app.do_next(fictional_store, now=LATER, root=privacy_root).lines
    assert not any("tm:step/roster-import" in line for line in still)  # retention is not approved yet
    sign_step(fictional_store, privacy_root, STEP_RETENTION, at="2026-10-25T10:00:00+00:00")
    assert any("tm:step/roster-import" in line for line in app.do_next(fictional_store, now=LATER, root=privacy_root).lines)


def test_dpia_screening_alone_does_not_unlock_roster_import_for_the_real_standards(fictional_store):
    dpia_ready(fictional_store)
    rep = app.do_ingest(fictional_store, dpia_receipt(fictional_store, "dpia-not-required", sid="2222222222222222"),
                        now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "0 rejected" in rep.summary and event_steps(fictional_store, "signoff") == [STEP_VERIFIED, STEP_ROPA_APPROVED, STEP_DPIA]
    assert not any("tm:step/roster-import" in line for line in queue(fictional_store, now=LATER))  # no retention yet


def test_dpia_changes_decision_is_recorded_but_leaves_the_step_open(fictional_store):
    dpia_ready(fictional_store)
    path = dpia_receipt(fictional_store, "dpia-required", sid="3333333333333333", decision="changes")
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "0 rejected" in rep.summary and event_steps(fictional_store, "signoff") == [STEP_VERIFIED, STEP_ROPA_APPROVED, STEP_DPIA]
    assert any("tm:step/dpia-screening" in line for line in queue(fictional_store, now=LATER))
    assert not any("tm:step/roster-import" in line for line in queue(fictional_store, now=LATER))


def test_dpia_page_decision_is_derived_not_hard_coded():
    page = (app.pagegen.PAGE_TEMPLATES / "dpia_screening.html").read_text(encoding="utf-8")
    assert 'value="record"' not in page and "data-decision" not in page


# --- plan since / mailbox -----------------------------------------------------------------------------


def plan_of(private):
    return json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))


def tagged_args(private):
    (op,) = [o for o in plan_of(private)["ops"] if o["op"] == "mail.tagged"]
    return op["args"]


def test_plan_names_the_mailbox_and_the_bare_tag(fictional_store):
    app.do_plan(fictional_store, now=T0)
    args = tagged_args(fictional_store)
    assert args["mailbox"] == "signoffs@example.com" and args["tag"] == "tm-signoff"


def test_since_moves_forward_with_each_ok_mailbox_read(fictional_store):
    app.do_tick(fictional_store, now=T0)
    assert tagged_args(fictional_store)["since"] == "2026-10-25"  # no read yet: a day before the first event
    day = T0 + timedelta(days=10)
    path = signed_receipt(fictional_store, now=day)  # run_at = day + 1h
    ingest_at = day + timedelta(hours=2)
    rep = app.do_ingest(fictional_store, path, now=ingest_at, allowed_drivers=ALL_DRIVERS)
    assert "0 rejected" in rep.summary
    reads = [e for e in app.read_events(fictional_store) if e["payload"].get("result") == "mailbox_read"]
    assert len(reads) == 1 and reads[0]["kind"] == "check" and reads[0]["payload"]["step"] is None
    app.do_plan(fictional_store, now=ingest_at)
    assert tagged_args(fictional_store)["since"] == (day + timedelta(hours=1) - timedelta(days=2)).date().isoformat()
    # replaying the same receipt adds no second read event
    again = app.do_ingest(fictional_store, path, now=ingest_at, allowed_drivers=ALL_DRIVERS)
    assert "0 event(s)" in again.summary


def test_a_failed_mailbox_read_does_not_move_since(fictional_store):
    app.do_tick(fictional_store, now=T0)
    day = T0 + timedelta(days=10)
    path = signed_receipt(fictional_store, now=day)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["results"][0]["status"] = "error"
    path.write_text(json.dumps(doc), encoding="utf-8")
    app.do_ingest(fictional_store, path, now=day + timedelta(hours=2), allowed_drivers=ALL_DRIVERS)
    assert not [e for e in app.read_events(fictional_store) if e["payload"].get("result") == "mailbox_read"]
    app.do_plan(fictional_store, now=day + timedelta(hours=2))
    assert tagged_args(fictional_store)["since"] == "2026-10-25"


# --- batch rows ---------------------------------------------------------------------------------------


def batch_rows(private, page_name):
    return [r["key"] for r in tm_data(private / "pages" / page_name)["inputs"]["rows"]]


@pytest.mark.parametrize("bad", ["reject", "unreviewed"])
def test_gap_list_approval_with_a_row_not_approved_is_rejected(fictional_store, example_roster, bad):
    gap_ready(fictional_store, example_roster)
    keys = batch_rows(fictional_store, GAP_PAGE)
    assert len(keys) >= 2
    rows = {k: "approve" for k in keys} | {keys[0]: bad}
    path = page_receipt(fictional_store, GAP_PAGE, OWNER, sid="4444444444444444", fields={"rows": rows})
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 rejected" in rep.summary and any("batch rows not all approved" in line for line in rep.lines)
    assert event_steps(fictional_store, "signoff") == []


def test_gap_list_approval_without_rows_is_rejected(fictional_store, example_roster):
    gap_ready(fictional_store, example_roster)
    path = page_receipt(fictional_store, GAP_PAGE, OWNER, sid="5555555555555555", fields={})
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 rejected" in rep.summary and event_steps(fictional_store, "signoff") == []


def test_lead_observed_level_does_not_change_when_its_row_is_rejected(fictional_store, example_roster):
    lead_ready(fictional_store, example_roster)
    (key,) = batch_rows(fictional_store, LEAD_PAGE)
    path = page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="6666666666666666", fields={"rows": {key: "reject"}})
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 rejected" in rep.summary and "level_change" not in rep.summary
    assert app.current_level(app.load_state(fictional_store), SME) == "co-deliver"
    assert len(level_changes(fictional_store)) == 1
    # approving the row afterwards still works
    ok = page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="7777777777777777", name="r3.json")
    assert "1 level_change" in app.do_ingest(fictional_store, ok, now=LATER, allowed_drivers=ALL_DRIVERS).summary


# --- retention approval binding -----------------------------------------------------------------------


def test_retention_page_is_not_built_while_there_are_no_entries(fictional_store):
    app.do_tick(fictional_store, now=T0)
    st = app.load_state(fictional_store)  # the real standards/retention.yaml: no entries yet
    with pytest.raises(app.PageProblem, match="retention entries still empty"):
        app.PAGE_SPECS["tm:step/retention-approved"](st, PROGRAMME)


def test_pages_reports_the_retention_problem_and_writes_no_page(fictional_store):
    dpia_ready(fictional_store)
    sign_step(fictional_store, ROOT, STEP_DPIA, at="2026-10-25T09:05:00+00:00")
    rep = app.do_pages(fictional_store, now=T0)
    assert any("retention entries still empty" in line for line in rep.lines)
    assert not list((fictional_store / "pages").glob("retention-approved--*.html"))


def test_retention_signoff_is_stale_after_the_periods_change(fictional_store, privacy_root):
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    sign_step(fictional_store, privacy_root, STEP_VERIFIED, at="2026-10-25T09:00:00+00:00")
    sign_step(fictional_store, privacy_root, STEP_DPIA, at="2026-10-25T09:05:00+00:00")
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    page = "retention-approved--teachermodel--hot-1.html"
    path = page_receipt(fictional_store, page, "hal.head@example.com", sid="8888888888888888")
    retention = privacy_root / "standards" / "retention.yaml"
    doc = yaml.safe_load(retention.read_text(encoding="utf-8"))
    doc["entries"][0]["period_months"] = 36
    retention.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS, root=privacy_root)
    assert "1 rejected" in rep.summary and any("stale" in line for line in rep.lines)


def test_retention_approval_must_decide_every_row(fictional_store, privacy_root):
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    sign_step(fictional_store, privacy_root, STEP_VERIFIED, at="2026-10-25T09:00:00+00:00")
    sign_step(fictional_store, privacy_root, STEP_DPIA, at="2026-10-25T09:05:00+00:00")
    app.do_tick(fictional_store, now=T0, root=privacy_root)
    page = "retention-approved--teachermodel--hot-1.html"
    keys = batch_rows(fictional_store, page)
    assert len(keys) == 4
    short = page_receipt(fictional_store, page, "hal.head@example.com", sid="9999999999999999",
                         fields={"rows": {k: "approve" for k in keys[:-1]}})
    rep = app.do_ingest(fictional_store, short, now=LATER, allowed_drivers=ALL_DRIVERS, root=privacy_root)
    assert "1 rejected" in rep.summary and event_steps(fictional_store, "signoff") == [STEP_VERIFIED, STEP_DPIA]
    ok = page_receipt(fictional_store, page, "hal.head@example.com", sid="7777777777777771", name="r3.json")
    rep = app.do_ingest(fictional_store, ok, now=LATER, allowed_drivers=ALL_DRIVERS, root=privacy_root)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary


# --- write before append, restoring a missing stored copy ---------------------------------------------


def test_a_failed_document_write_appends_no_events(fictional_store, monkeypatch):
    app.do_tick(fictional_store, now=T0)
    path = signed_receipt(fictional_store)
    before = app.read_events(fictional_store)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(app, "_write_private", boom)
    with pytest.raises(OSError):
        app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert app.read_events(fictional_store) == before
    assert not (fictional_store / "signoffs" / "0123456789abcdef.json").exists()
    monkeypatch.undo()
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)  # the retry succeeds whole
    assert "1 signoff" in rep.summary and (fictional_store / "signoffs" / "0123456789abcdef.json").is_file()


def test_a_missing_stored_copy_of_an_accepted_signoff_is_restored(fictional_store):
    app.do_tick(fictional_store, now=T0)
    path = signed_receipt(fictional_store)
    app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    stored = fictional_store / "signoffs" / "0123456789abcdef.json"
    original = stored.read_bytes()
    stored.unlink()
    rep = app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "0 event(s)" in rep.summary and "1 sign-off document(s) stored" in rep.summary
    assert stored.read_bytes() == original
    assert event_steps(fictional_store, "signoff") == ["tm:step/it-done"]


def test_a_different_document_under_an_accepted_id_is_not_stored(fictional_store):
    app.do_tick(fictional_store, now=T0)
    app.do_ingest(fictional_store, signed_receipt(fictional_store), now=LATER, allowed_drivers=ALL_DRIVERS)
    stored = fictional_store / "signoffs" / "0123456789abcdef.json"
    stored.unlink()
    forged = signed_receipt(fictional_store, fields={"note": "something else"})
    rep = app.do_ingest(fictional_store, forged, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "0 sign-off document(s) stored" in rep.summary and not stored.exists()


# --- one mailbox, two identities ----------------------------------------------------------------------


def test_a_person_who_is_also_a_roster_instructor_loads_and_signs_as_the_person(fictional_store, example_roster, tmp_path):
    doc = yaml.safe_load(example_roster.read_text(encoding="utf-8"))
    doc["instructors"][3]["identity"]["email"] = "PAT.IT@example.com"  # the IT person also teaches
    shared = tmp_path / "roster-shared.yaml"
    shared.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    import_roster_ungated(fictional_store, shared, T0)
    st = app.load_state(fictional_store)  # used to raise "duplicate email across identity sources"
    uris = [e["uri"] for e in st.identities["pat.it@example.com"]]
    assert uris[0] == "tm:person/it-1" and len(uris) == 2 and uris[1].startswith("tm:instructor/")
    app.do_tick(fictional_store, now=T0)
    rep = app.do_ingest(fictional_store, signed_receipt(fictional_store), now=LATER, allowed_drivers=ALL_DRIVERS)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary


# --- flow registries: auto steps and sign-off hooks extend app without editing it -----------------------

FAKE_WORKFLOW = """\
schema_version: 1
id: tm:standards/workflows-fake
status: draft
workflows:
  - id: tm:workflow/fake
    name: Fake
    basis: test
    event_kinds: [step]
    steps:
      - id: tm:step/fake-auto
        name: Fake auto
        type: auto
        role: programme-owner
        subject: programme
        needs: []
        done_when: {kind: step, match: {step: tm:step/fake-auto}}
        basis: test
"""


def fake_root(tmp_path):
    root = tmp_path / "fake-root"
    for part in ("standards", "contracts", "docs"):
        _shutil.copytree(ROOT / part, root / part)
    (root / "standards" / "workflows" / "zz-fake.yaml").write_text(FAKE_WORKFLOW, encoding="utf-8")
    return root


def test_a_registered_auto_step_runs_and_refreshes(fictional_store, tmp_path, registries):
    root = fake_root(tmp_path)
    content = ["one"]
    calls = []

    @registries.auto_step("tm:step/fake-auto", refresh=True)
    def run_fake(st, subject, now):
        calls.append(subject)
        return [events.make_event("step", subject, "tm:system/teachermodel",
                                  {"step": "tm:step/fake-auto", "content": content[0]},
                                  id=signoff.input_sha256({"fake": content[0]})[:32], at=now.isoformat())]

    rep = app.do_run(fictional_store, now=T0, root=root)
    assert "tm:step/fake-auto: 1 event(s) appended" in rep.lines
    assert calls == ["tm:programme/teachermodel"]  # the main loop ran it; the refresh pass skips a step attempted this call
    assert event_steps(fictional_store).count("tm:step/fake-auto") == 1
    content[0] = "two"  # a source changed: the refresh pass runs the done step again
    rep = app.do_run(fictional_store, now=T0 + timedelta(hours=1), root=root)
    assert "tm:step/fake-auto: refreshed, 1 event(s) appended" in rep.lines
    assert event_steps(fictional_store).count("tm:step/fake-auto") == 2


def test_the_registry_refuses_a_second_runner_and_an_unknown_scope(registries):
    with pytest.raises(ValueError, match="already registered"):
        registries.auto_step("tm:step/ropa")(lambda st, subject, now: [])
    with pytest.raises(ValueError, match="per must be one of"):
        registries.auto_step("tm:step/other", per="planet")


def test_the_registries_are_restored_between_tests():
    assert "tm:step/fake-auto" not in app.AUTO_STEPS
    assert [h.__name__ for h in app.SIGNOFF_HOOKS[LEVEL_STEP]] == ["_level_change"]


def test_an_on_signoff_hook_returns_events_and_documents(fictional_store, example_roster, registries):
    lead_ready(fictional_store, example_roster)
    seen = []

    @registries.on_signoff(LEVEL_STEP)
    def fake_hook(st, signed, document, now):
        seen.append((signed["payload"]["signoff_id"], document["fields"], app.current_level(st, signed["subject_uri"])))
        note = events.make_event("step", signed["subject_uri"], "tm:system/teachermodel",
                                 {"step": "tm:step/fake-hook", "signoff": document["id"]},
                                 id=signoff.input_sha256({"hook": document["id"]})[:32], at=now.isoformat())
        return [note], [(f"generated/fake-hook-{document['id']}.json", {"signoff": document["id"]})]

    path = page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="eeeeeeeeeeeeeeee")
    app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert [s[0] for s in seen] == ["eeeeeeeeeeeeeeee"]
    assert seen[0][1]["rows"] and seen[0][2] == "lead-observed"  # the full stored sign-off; the level change is in view
    tail = [e["kind"] for e in app.read_events(fictional_store)][-4:-1]  # the mailbox-read check closes the ingest
    assert tail == ["signoff", "level_change", "step"]  # sign-off events first, then what the hooks returned, in order
    written = fictional_store / "generated" / "fake-hook-eeeeeeeeeeeeeeee.json"
    assert json.loads(written.read_text(encoding="utf-8")) == {"signoff": "eeeeeeeeeeeeeeee"}
    before = app.read_events(fictional_store)
    app.do_ingest(fictional_store, path, now=LATER + timedelta(hours=1), allowed_drivers=ALL_DRIVERS)
    assert app.read_events(fictional_store) == before and len(seen) == 1  # a replay accepts nothing, so no hook runs


def test_an_on_signoff_hook_does_not_run_for_a_rejected_signoff(fictional_store, example_roster, registries):
    lead_ready(fictional_store, example_roster)
    seen = []
    registries.on_signoff(LEVEL_STEP)(lambda st, signed, document, now: (seen.append(1), ([], []))[1])
    path = page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="ffffffffffffffff", decision="reject")
    app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
    assert seen == []


def test_a_hook_document_cannot_leave_the_private_dir_or_reach_the_log(fictional_store, example_roster, registries):
    lead_ready(fictional_store, example_roster)
    path = page_receipt(fictional_store, LEAD_PAGE, HEAD, sid="9999999999999999")
    before = app.read_events(fictional_store)
    for bad in ("../escaped.json", "events/events.jsonl"):
        hook = registries.on_signoff(LEVEL_STEP)(lambda st, signed, document, now, bad=bad: ([], [(bad, {})]))
        with pytest.raises(app.AppError, match="refusing to write"):
            app.do_ingest(fictional_store, path, now=LATER, allowed_drivers=ALL_DRIVERS)
        registries.SIGNOFF_HOOKS[LEVEL_STEP].remove(hook)
        assert app.read_events(fictional_store) == before


# --- content checks: a flow rules on the content of an approving sign-off before ingest accepts it -----------------


def test_a_content_check_runs_on_approving_signoffs_of_its_step_only(registries):
    seen = []

    @registries.content_check("tm:step/fake-step")
    def check(st, document):
        seen.append(document["step"])
        return ["field x: required"] if not document["fields"].get("x") else []

    approve = {"step": "tm:step/fake-step", "decision": "approve", "fields": {}}
    assert registries.content_reasons(None, approve) == ["field x: required"]
    assert registries.content_reasons(None, {**approve, "fields": {"x": 1}}) == []
    assert registries.content_reasons(None, {**approve, "decision": "changes"}) == []  # never completes a step
    assert registries.content_reasons(None, {**approve, "step": "tm:step/other"}) == []
    assert seen == ["tm:step/fake-step"] * 2


def test_a_content_check_that_raises_rejects_rather_than_aborting(registries):
    @registries.content_check("tm:step/fake-step")
    def broken(st, document):
        raise KeyError("fields")

    assert registries.content_reasons(None, {"step": "tm:step/fake-step", "decision": "approve"}) == [
        "content check failed"]


def test_the_content_checks_are_restored_between_tests():
    from teachermodel import flows

    assert "tm:step/fake-step" not in flows.CONTENT_CHECKS
    assert set(flows.CONTENT_CHECKS) == {"tm:step/observe", "tm:step/calibration-score", "tm:step/clearer-decision-1",
                                         "tm:step/clearer-decision-2", "tm:step/head-resolves", "tm:step/levels-decided",
                                         "tm:step/second-score",
                                         "tm:step/coach-observe", "tm:step/coach-feedback", "tm:step/practice-task",
                                         "tm:step/coach-reobserve", "tm:step/log-activity",
                                         "tm:step/bench-decision", "tm:step/override-decision", "tm:step/assign-observer",
                                         "tm:step/reply-or-appeal", "tm:step/appeal-decision",
                                         "tm:step/recalibration-exercise"}
