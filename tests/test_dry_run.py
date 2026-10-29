"""W3 dry-run: the step `tm:step/dry-run` (standards/workflows/dry-run.yaml), its page, the sign-off hook that writes the
`dry_run` event (dry-run@1) and records.dry_runs. Fictional people only.

Plan: docs/plans/2026-10-24-increment-2-plan.md, "Machine contracts" and "C. W3 dry-run".
"""

import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from clearer_helpers import calibrate, set_level
from conftest import EXAMPLE_ROSTER_PATH, make_fictional_store
from privacy_helpers import import_roster_ungated, make_privacy_root, tm_data

from teachermodel import app, events, rules, units
from teachermodel.flows import dry_run as flow
from teachermodel.records import dry_runs
from teachermodel.standards import ROOT, check_standards, load_standards, validate

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
LATER = T0 + timedelta(hours=3)
ALL_DRIVERS = ("connector", "graph", "fixture")
STEP = "tm:step/dry-run"
UNIT = "sl:unit/example-agent-loop@1"
PROFESSIONAL = "tm:instructor/p3x9d"  # cleared; delivers the example unit in-person, remote and hybrid
CANDIDATE = "tm:candidate/p3x9d--example-agent-loop-1--remote"
CLEARER_1, CLEARER_2 = "tm:person/clearer-1", "tm:person/clearer-2"
# A person who is both the professional instructor and a clearer: the same mailbox as the roster instructor.
SELF = "tm:person/prof-clearer"
SELF_MAIL = "professional@example.com"
MAIL = {CLEARER_1: "clearer.one@example.com", CLEARER_2: "clearer.two@example.com", SELF: SELF_MAIL}
NOTE = "FIXTURE-NOTE the sandbox key had a stale quota"


def page_name(signer, candidate=CANDIDATE):
    return f"dry-run--{candidate.split('/', 1)[1]}--{signer.split('/', 1)[1]}.html"


# A dry-run clearer is a person holding the clearer role who is mapped to an instructor at level clearer that is calibrated
# on the day (integration review finding 5); the role in the people list alone is nothing.
MAPPED = {CLEARER_1: "tm:instructor/k7m2q", CLEARER_2: "tm:instructor/c5w1t"}


def with_clearers(private, mapped=None):
    """The fictional people plus two clearers (mapped to roster instructors) and one clearer who is also the professional
    instructor (by mailbox: unmapped). The levels and calibrations come after the roster import (`make_clearers`)."""
    mapped = MAPPED if mapped is None else mapped
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for person, mail in MAIL.items():
        row = {"person": person, "name": "Fictional " + person.split("/")[1], "email": mail, "roles": ["clearer"]}
        if person in mapped:
            row["instructor"] = mapped[person]
        doc["people"].append(row)
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def make_clearers(private, mapped=None, levels=True, calibrated=True):
    """The mapped instructors become clearers by level and are calibrated (after the roster import: it sets the levels)."""
    for instructor in sorted(set((MAPPED if mapped is None else mapped).values())):
        if levels:
            set_level(private, instructor, "clearer")
        if calibrated:
            calibrate(private, instructor)


def _build(base, root=None):
    private = make_fictional_store(base)
    roster = base / "roster-in.yaml"
    shutil.copy(EXAMPLE_ROSTER_PATH, roster)
    with_clearers(private)
    import_roster_ungated(private, roster, T0)
    make_clearers(private)
    app.do_tick(private, now=T0, **({"root": root} if root is not None else {}))


def build_store(base):
    _build(base)


def build_edited_root(base):
    _build(base, make_privacy_root(base))


@pytest.fixture
def store(fictional_store, example_roster, cached_world):
    """The clearers added, the roster imported, the clearers levelled and calibrated, one tick: built once per session,
    copied into this test's tmp_path."""
    cached_world("dry_run_store", build_store)
    return fictional_store


@pytest.fixture
def edited_root(tmp_path, fictional_store, example_roster, cached_world):
    """A repo-data root whose example unit a test may edit, and a store that has candidates and pages for it."""
    cached_world("dry_run_edited_root", build_edited_root)
    return tmp_path / "root", fictional_store


def edit_unit(root, fn):
    path = root / "standards" / "units" / "example-agent-loop@1.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def dry_run_page(private, signer=CLEARER_1):
    return tm_data(private / "pages" / page_name(signer))


def answers(page, *, fail=(), failure="rate-limit", skip=()):
    """What a clearer's page returns: every checklist item passed, but those in `fail` (with a note)."""
    (checks,) = [f for f in page["fields"] if f["name"] == "checks"]
    out = {i["id"]: {"result": "fail" if i["id"] in fail else "pass", "note": NOTE if i["id"] in fail else ""}
           for i in checks["items"] if i["id"] not in skip}
    return {"checks": out, "failure_injected": failure, "note": NOTE + " (free text)"}


def receipt(private, page, sender, *, sid, fields, decision="approve", signer=None, now=T0, name="r1.json"):
    """A receipt carrying one sign-off built from `page`, mailed by `sender`."""
    doc = {
        "schema": "tm:contract/signoff@1", "id": sid, "step": page["step"], "subject_uri": page["subject_uri"],
        "input_sha256": page["input_sha256"], "decision": decision, "fields": fields, "signer": signer or page["signer"],
        "signed_at": (now + timedelta(minutes=30)).isoformat(), "page_template_sha256": page["page_template_sha256"],
    }
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    (tagged,) = [o for o in plan["ops"] if o["op"] == "mail.tagged"]
    msg = {"sender": sender, "subject": f"[tm-signoff {sid}]", "received": (now + timedelta(minutes=40)).isoformat(),
           "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]}
    body = {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": (private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
        "driver": "fixture", "run_at": (now + timedelta(hours=1)).isoformat(),
        "results": [{"op_id": tagged["op_id"], "status": "ok", "data": {"messages": [msg]}}],
    }
    path = private / "receipts" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def sign(private, fields, *, sid="d0d0d0d0d0d0d0d0", decision="approve", root=ROOT, page=None, signer=CLEARER_1,
         sender=None, name="r1.json", at=T0):
    """Mail the sign-off at `at` (after the plan it answers) and ingest it three hours later."""
    page = page or dry_run_page(private)
    path = receipt(private, page, sender or MAIL[signer], sid=sid, fields=fields, decision=decision, signer=signer,
                   now=at, name=name)
    return app.do_ingest(private, path, now=at + timedelta(hours=3), allowed_drivers=ALL_DRIVERS, root=root)


def log(private, kind):
    return [e for e in app.read_events(private) if e["kind"] == kind]


def runs(private):
    return [e for e in log(private, "dry_run") if e["subject_uri"] == CANDIDATE]


def open_now(private, root=ROOT, now=LATER):
    return {(d.step, d.subject) for d in app.due_steps(app.load_state(private, root), now.date())}


def tick(private, root=ROOT, now=LATER):
    app.do_tick(private, now=now, root=root)


# --- the workflow file ---------------------------------------------------------------------------


def test_the_workflow_file_defines_one_human_step_per_candidate():
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/dry-run"]
    (st,) = wf["steps"]
    assert st["id"] == STEP and st["type"] == "human" and st["role"] == "clearer" and st["subject"] == "candidate"
    assert st["page"] == "approve"
    assert st["done_when"] == {"kind": "signoff", "match": {"step": STEP}, "bind": "input"}
    assert st["due"]["basis"] == "operational default"  # decision 0002: a wait is a default, not a finding
    assert "dry-run-protocol" in wf["basis"] or "W3" in wf["basis"]


def test_the_standards_validate_with_the_dry_run_file():
    assert check_standards(ROOT) == []


def test_the_step_has_a_page_builder_and_a_hook():
    from teachermodel import flows

    assert STEP in flows.PAGE_SPECS and flows.SIGNOFF_HOOKS[STEP]


# --- the step opens per candidate -----------------------------------------------------------------


def test_the_step_is_open_for_each_candidate(store):
    due = open_now(store)  # (k7m2q and c5w1t are clearers by level here, so they have candidates of their own too)
    assert {s for s in due if s[0] == STEP and "p3x9d" in s[1]} == {
        (STEP, "tm:candidate/p3x9d--example-agent-loop-1--hybrid"),
        (STEP, "tm:candidate/p3x9d--example-agent-loop-1--in-person"),
        (STEP, CANDIDATE),
    }


def test_a_candidate_may_wait_a_labelled_default_from_the_day_it_was_opened(store):
    (opened,) = [e for e in log(store, "subject") if e["subject_uri"] == CANDIDATE]
    (d,) = [d for d in app.due_steps(app.load_state(store), T0.date()) if d.step == STEP and d.subject == CANDIDATE]
    wf = {w["id"]: w for w in load_standards()["workflows"]["workflows"]}["tm:workflow/dry-run"]
    assert d.due == date.fromisoformat(opened["at"][:10]) + timedelta(days=wf["steps"][0]["due"]["days"])
    assert not d.overdue and d.role == "clearer" and d.type == "human"


# --- the page --------------------------------------------------------------------------------------


def test_one_page_per_clearer_and_never_the_candidates_own_instructor(store):
    pages = sorted(p.name for p in (store / "pages").glob(f"dry-run--{CANDIDATE.split('/', 1)[1]}--*.html"))
    assert pages == [page_name(CLEARER_1), page_name(CLEARER_2)]  # prof-clearer shares the instructor's mailbox
    # the same person may clear someone else's candidate: the SME's candidates would not exclude them
    st = app.load_state(store)
    assert flow.is_candidates_instructor(st, SELF, PROFESSIONAL)
    assert not flow.is_candidates_instructor(st, SELF, "tm:instructor/k7m2q")
    assert not flow.is_candidates_instructor(st, CLEARER_1, PROFESSIONAL)


def test_a_person_mapped_to_the_instructor_is_the_instructor_whatever_their_mailbox(store):
    st = app.load_state(store)
    st.people = [*st.people, {"person": "tm:person/mapped", "name": "M", "email": "elsewhere@example.com",
                              "roles": ["clearer"], "instructor": PROFESSIONAL}]
    assert flow.is_candidates_instructor(st, "tm:person/mapped", PROFESSIONAL)
    assert not flow.is_candidates_instructor(st, "tm:person/mapped", "tm:instructor/k7m2q")
    assert "tm:person/mapped" not in {s["signer"] for s in app.PAGE_SPECS[STEP](st, CANDIDATE)}


def test_no_clearer_besides_the_instructor_is_a_page_problem(store):
    st = app.load_state(store)
    st.people = [p for p in st.people if p["person"] == SELF or "clearer" not in p["roles"]]
    with pytest.raises(app.PageProblem, match="clearer"):
        app.PAGE_SPECS[STEP](st, CANDIDATE)


def dry_run_pages(private):
    return sorted(p.name for p in (private / "pages").glob(f"dry-run--{CANDIDATE.split('/', 1)[1]}--*.html"))


def started(fictional_store, example_roster, mapped=None, **kw):
    with_clearers(fictional_store, mapped)
    import_roster_ungated(fictional_store, example_roster, T0)
    make_clearers(fictional_store, mapped, **kw)
    app.do_tick(fictional_store, now=T0)
    return fictional_store


def test_a_clearer_role_with_no_mapping_is_offered_no_page(fictional_store, example_roster):
    started(fictional_store, example_roster, mapped={CLEARER_1: MAPPED[CLEARER_1]})  # CLEARER_2 holds the role, no mapping
    assert dry_run_pages(fictional_store) == [page_name(CLEARER_1)]


def test_a_mapping_to_an_instructor_who_is_not_a_clearer_by_level_is_offered_no_page(fictional_store, example_roster):
    started(fictional_store, example_roster, levels=False)
    assert dry_run_pages(fictional_store) == []
    st = app.load_state(fictional_store)
    with pytest.raises(app.PageProblem, match="clearer"):
        app.PAGE_SPECS[STEP](st, CANDIDATE)


def test_a_clearer_who_never_calibrated_is_offered_no_page(fictional_store, example_roster):
    started(fictional_store, example_roster, calibrated=False)
    assert dry_run_pages(fictional_store) == []


def test_a_clearer_whose_calibration_has_lapsed_is_offered_no_page(fictional_store, example_roster):
    started(fictional_store, example_roster, calibrated=False)
    calibrate(fictional_store, "k7m2q", "c5w1t", at="2026-03-01T08:00:00+00:00")  # six months: ended on 2026-09-01
    app.do_pages(fictional_store, now=T0)
    assert dry_run_pages(fictional_store) == []
    calibrate(fictional_store, "c5w1t")  # a fresh pass brings one back
    app.do_pages(fictional_store, now=T0)
    assert dry_run_pages(fictional_store) == [page_name(CLEARER_2)]


def test_a_clearer_role_alone_cannot_sign_a_dry_run(fictional_store, example_roster):
    started(fictional_store, example_roster)
    path = fictional_store / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/stray", "name": "Fictional Stray", "email": "stray@example.com",
                          "roles": ["clearer"]})  # holds the role, no mapping to any instructor
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    page = dry_run_page(fictional_store)
    rep = sign(fictional_store, answers(page), page=page, signer="tm:person/stray", sender="stray@example.com")
    assert "1 signoff" in rep.summary  # the identity check passes: the people list says clearer
    assert runs(fictional_store) == []
    (refused,) = [e for e in log(fictional_store, "check") if e["payload"].get("result") == "dry_run_refused"]
    assert "calibrated clearer" in " ".join(refused["payload"]["reasons"])
    assert "stray" not in json.dumps(refused)


def test_a_clearer_whose_calibration_lapsed_before_they_signed_is_refused(fictional_store, example_roster):
    started(fictional_store, example_roster)
    later = datetime(2027, 3, 2, 8, 0, tzinfo=timezone.utc)  # 2026-09-01 plus six months ended on 2027-03-01
    rep = sign(fictional_store, answers(dry_run_page(fictional_store)), at=later)
    assert "1 signoff" in rep.summary
    assert runs(fictional_store) == []
    (refused,) = [e for e in log(fictional_store, "check") if e["payload"].get("result") == "dry_run_refused"]
    assert "calibrated clearer" in " ".join(refused["payload"]["reasons"])


def test_a_calibrated_mapped_clearer_signs_as_before(fictional_store, example_roster):
    started(fictional_store, example_roster)
    rep = sign(fictional_store, answers(dry_run_page(fictional_store)), signer=CLEARER_2, page=dry_run_page(
        fictional_store, CLEARER_2))
    assert "1 dry_run" in rep.summary, rep.all_lines()


def test_the_page_is_built_from_the_unit_file(store):
    page = dry_run_page(store)
    unit = units.load(UNIT)
    assert page["template"] == "approve" and page["role"] == "clearer" and page["subject_uri"] == CANDIDATE
    inputs = page["inputs"]
    assert inputs["candidate"] == CANDIDATE and inputs["instructor"] == PROFESSIONAL
    assert inputs["unit"] == UNIT and inputs["mode"] == "remote"
    assert inputs["environment"] == unit["environment"]
    assert inputs["environment_sha256"] == units.environment_sha256(unit)  # inputs bind to the unit's hash
    assert inputs["failure_catalogue"] == unit["failure_catalogue"]
    fields = {f["name"]: f for f in page["fields"]}
    assert set(fields) == {"checks", "failure_injected", "note"}
    assert fields["checks"]["kind"] == "checklist" and fields["checks"]["required"] is True
    assert fields["failure_injected"]["kind"] == "enum" and fields["failure_injected"]["required"] is True
    assert fields["failure_injected"]["options"] == ["rate-limit", "none"]  # the catalogue, then "none"
    assert fields["note"]["kind"] == "textarea" and fields["note"]["required"] is False


def test_the_checklist_has_preflight_clock_failure_and_fallback_items(store):
    (checks,) = [f for f in dry_run_page(store)["fields"] if f["name"] == "checks"]
    ids = [i["id"] for i in checks["items"]]
    assert ids == ["preflight-environment", "preflight-accounts", "preflight-api-keys", "preflight-data",
                   "preflight-network", "preflight-model", "clock", "failure-handled", "fallback-exercised"]
    assert units.load(UNIT)["environment"] in dict((i["id"], i["label"]) for i in checks["items"])["preflight-environment"]
    assert dry_run_page(store)["inputs"]["checks"] == ids  # the set of items is part of what the signer signs


def test_the_preflight_items_cover_step_one_of_the_protocol():
    protocol = (ROOT / "standards" / "dry-run-protocol.md").read_text(encoding="utf-8").lower()
    for word in ("accounts", "api keys", "rate limits", "data", "network", "model version"):
        assert word in protocol  # the items below are those words; if the protocol moves, so must they
    labels = " ".join(label.lower() for _, label in flow.PREFLIGHT)
    for word in ("accounts", "api keys", "rate limits", "data", "network", "model version"):
        assert word in labels


def test_a_unit_run_sheet_adds_one_item_per_step(edited_root):
    root, private = edited_root
    edit_unit(root, lambda d: d.update(run_sheet=[{"id": "intro", "action": "Welcome and set up", "minutes": 10},
                                                   {"id": "lab-one", "action": "Build the loop"}]))
    st = app.load_state(private, root)
    (spec,) = [s for s in app.PAGE_SPECS[STEP](st, CANDIDATE) if s["signer"] == CLEARER_1]
    (checks,) = [f for f in spec["fields"] if f["name"] == "checks"]
    items = {i["id"]: i["label"] for i in checks["items"]}
    assert "step-intro" in items and "step-lab-one" in items
    assert "Welcome and set up" in items["step-intro"] and "10" in items["step-intro"]
    assert list(items).index("step-intro") < list(items).index("step-lab-one") < list(items).index("clock")
    assert spec["inputs"]["run_sheet"] == st_unit_run_sheet(root)


def st_unit_run_sheet(root):
    return units.load(UNIT, root)["run_sheet"]


def test_the_page_renders(store):
    html = (store / "pages" / page_name(CLEARER_1)).read_text(encoding="utf-8")
    assert "Dry run" in html and "rate-limit" in html and "fallback" in html.lower()


# --- a passed dry run ------------------------------------------------------------------------------


def passed_event(private):
    rep = sign(private, answers(dry_run_page(private)))
    assert rep.ok and "1 signoff" in rep.summary and "1 dry_run" in rep.summary, rep.all_lines()
    (event,) = runs(private)
    return event


def test_a_passed_dry_run_is_recorded_per_the_contract(store):
    event = passed_event(store)
    unit = units.load(UNIT)
    assert event["actor"] == CLEARER_1 and event["subject_uri"] == CANDIDATE
    assert event["payload"] == {
        "candidate": CANDIDATE, "instructor": PROFESSIONAL, "unit": UNIT, "mode": "remote", "passed": True,
        "checks": {i: "pass" for i in dry_run_page(store, CLEARER_2)["inputs"]["checks"]},
        "failure_injected": "rate-limit", "fallback_exercised": True,
        "environment_sha256": units.environment_sha256(unit), "signoff_id": "d0d0d0d0d0d0d0d0",
    }
    assert events.check_event(event) == [] and validate(event["payload"], "dry-run.schema.json", ROOT) == []
    assert event["id"] == flow.dry_run_event_id("d0d0d0d0d0d0d0d0")
    assert event["at"][:10] == (T0 + timedelta(minutes=30)).date().isoformat()  # the run date is when it was signed


def test_a_passed_dry_run_closes_the_step_for_that_candidate_only(store):
    passed_event(store)
    due = open_now(store)
    assert (STEP, CANDIDATE) not in due
    assert (STEP, "tm:candidate/p3x9d--example-agent-loop-1--hybrid") in due


def test_notes_go_to_a_private_document_and_never_into_the_events(store):
    sign(store, answers(dry_run_page(store), fail=["preflight-data"]))
    doc = json.loads((store / "dry-runs" / "d0d0d0d0d0d0d0d0.json").read_text(encoding="utf-8"))
    assert NOTE in json.dumps(doc) and doc["signoff_id"] == "d0d0d0d0d0d0d0d0" and doc["candidate"] == CANDIDATE
    assert doc["notes"] == {"preflight-data": NOTE} and NOTE in doc["note"]
    assert NOTE not in (store / "events" / "events.jsonl").read_text(encoding="utf-8")
    (event,) = runs(store)
    assert set(event["payload"]) == {"candidate", "instructor", "unit", "mode", "passed", "checks", "failure_injected",
                                     "fallback_exercised", "environment_sha256", "signoff_id"}


def test_the_log_still_verifies_and_a_replay_adds_nothing(store):
    passed_event(store)
    before = app.read_events(store)
    path = store / "receipts" / "r1.json"
    rep = app.do_ingest(store, path, now=LATER + timedelta(hours=1), allowed_drivers=ALL_DRIVERS)
    assert "0 event(s)" in rep.summary
    assert app.read_events(store) == before
    assert events.verify(store / "events" / "events.jsonl") == []


# --- what makes a run not passed --------------------------------------------------------------------


def test_no_failure_injected_means_not_passed_and_the_step_stays_open(store):
    sign(store, answers(dry_run_page(store), failure="none"))
    (event,) = runs(store)
    assert event["payload"]["passed"] is False and event["payload"]["failure_injected"] is None
    assert set(event["payload"]["checks"].values()) == {"pass"}  # every check passed; the missing failure alone fails it
    assert events.check_event(event) == []
    tick(store)
    assert (STEP, CANDIDATE) in open_now(store)  # the signed run did not pass, so the step reopened (new page, new hash)


def test_a_failure_that_is_not_in_the_catalogue_is_no_failure(store):
    sign(store, answers(dry_run_page(store), failure="made-up"))
    (event,) = runs(store)
    assert event["payload"]["passed"] is False and event["payload"]["failure_injected"] is None


def test_a_failed_check_means_not_passed(store):
    sign(store, answers(dry_run_page(store), fail=["failure-handled"]))
    (event,) = runs(store)
    p = event["payload"]
    assert p["passed"] is False and p["checks"]["failure-handled"] == "fail" and p["failure_injected"] == "rate-limit"
    assert events.check_event(event) == []
    assert (STEP, CANDIDATE) in open_now(store)


def test_the_fallback_not_exercised_means_not_passed(store):
    sign(store, answers(dry_run_page(store), fail=["fallback-exercised"]))
    (event,) = runs(store)
    assert event["payload"]["passed"] is False and event["payload"]["fallback_exercised"] is False
    assert events.check_event(event) == []


def test_an_unanswered_item_counts_as_failed(store):
    sign(store, answers(dry_run_page(store), skip=["preflight-network"]))
    (event,) = runs(store)
    assert event["payload"]["checks"]["preflight-network"] == "fail" and event["payload"]["passed"] is False


def test_changes_requested_records_no_dry_run(store):
    sign(store, answers(dry_run_page(store), fail=["clock"]), decision="changes")
    assert runs(store) == []
    assert (STEP, CANDIDATE) in open_now(store)  # a request for changes never completes the step


def test_a_changes_decision_is_logged_as_a_signoff_only_and_a_later_approval_still_closes_the_step(store):
    first = dry_run_page(store)
    sign(store, answers(first, fail=["clock"]), decision="changes", sid="c1c1c1c1c1c1c1c1")
    decisions = [(e["payload"]["signoff_id"], e["payload"]["decision"]) for e in log(store, "signoff")
                 if e["payload"]["step"] == STEP]
    assert decisions == [("c1c1c1c1c1c1c1c1", "changes")]  # recorded for the audit trail, nothing else
    assert runs(store) == [] and not [e for e in log(store, "check") if e["payload"].get("result") == flow.REFUSED]
    tick(store)
    assert (STEP, CANDIDATE) in open_now(store)
    again = dry_run_page(store)
    assert again["input_sha256"] == first["input_sha256"]  # a request for changes does not change what the page shows
    sign(store, answers(again), sid="c2c2c2c2c2c2c2c2", page=again, name="r2.json", at=LATER)
    assert [e["payload"]["passed"] for e in runs(store)] == [True]
    assert (STEP, CANDIDATE) not in open_now(store)


def test_a_run_not_passed_then_a_run_passed_closes_the_step(store):
    first = dry_run_page(store)
    sign(store, answers(first, failure="none"), sid="a1a1a1a1a1a1a1a1", name="r1.json")
    tick(store)
    again = dry_run_page(store)
    assert again["inputs"]["earlier_unsuccessful"] == ["a1a1a1a1a1a1a1a1"]
    assert again["input_sha256"] != first["input_sha256"]
    sign(store, answers(again), sid="b2b2b2b2b2b2b2b2", page=again, name="r2.json", at=LATER)
    assert [e["payload"]["passed"] for e in runs(store)] == [False, True]
    assert (STEP, CANDIDATE) not in open_now(store)


# --- the instructor cannot sign their own dry run ---------------------------------------------------


def test_the_instructor_signing_as_a_clearer_is_refused(store):
    page = dry_run_page(store)  # a page built for another clearer; only the signer and sender are forged
    rep = sign(store, answers(page), page=page, signer=SELF, sender=SELF_MAIL)
    assert "1 signoff" in rep.summary  # the sign-off passes the engine's role check: SELF holds the clearer role
    assert runs(store) == []  # but nothing is recorded as a dry run
    (refused,) = [e for e in log(store, "check") if e["payload"].get("result") == "dry_run_refused"]
    assert refused["subject_uri"] == CANDIDATE and refused["payload"]["step"] == STEP
    assert refused["payload"]["signoff_id"] == "d0d0d0d0d0d0d0d0"
    assert "instructor" in " ".join(refused["payload"]["reasons"])
    assert SELF not in json.dumps(refused) and SELF_MAIL not in json.dumps(refused)
    tick(store)
    assert (STEP, CANDIDATE) in open_now(store)  # the step reopened: the refused sign-off no longer covers its page
    assert dry_run_page(store)["inputs"]["earlier_unsuccessful"] == ["d0d0d0d0d0d0d0d0"]
    assert not (store / "pages" / page_name(SELF)).exists()


# --- a changed unit voids the dry run -----------------------------------------------------------------


def test_a_changed_environment_voids_the_run_in_the_records_and_reopens_the_step(edited_root):
    root, private = edited_root
    page = tm_data(private / "pages" / page_name(CLEARER_1))
    assert sign(private, answers(page), root=root, page=page).ok
    hashes = flow.current_environment_hashes([UNIT], root)
    assert len(dry_runs(app.read_events(private), hashes)) == 1
    assert (STEP, CANDIDATE) not in open_now(private, root)

    edit_unit(root, lambda d: d.update(environment=d["environment"] + " with a newer model version"))

    changed = flow.current_environment_hashes([UNIT], root)
    assert changed[UNIT] != hashes[UNIT]
    assert dry_runs(app.read_events(private), changed) == []  # the records: no longer counted
    assert (STEP, CANDIDATE) in open_now(private, root)  # the engine: the step reopens through its bound input


def test_a_changed_failure_catalogue_or_run_sheet_voids_it_too(edited_root):
    root, private = edited_root
    page = tm_data(private / "pages" / page_name(CLEARER_1))
    sign(private, answers(page), root=root, page=page)
    events_now = app.read_events(private)
    for change in (
        lambda d: d["failure_catalogue"].append({"id": "bad-output", "inject": "x", "expected_handling": "y"}),
        lambda d: d.update(run_sheet=[{"id": "intro", "action": "Welcome"}]),
    ):
        edit_unit(root, change)
        assert dry_runs(events_now, flow.current_environment_hashes([UNIT], root)) == []
        assert (STEP, CANDIDATE) in open_now(private, root)


def test_a_change_to_the_rest_of_the_unit_does_not_void_it(edited_root):
    root, private = edited_root
    page = tm_data(private / "pages" / page_name(CLEARER_1))
    sign(private, answers(page), root=root, page=page)
    edit_unit(root, lambda d: d.update(title="A new title", status="active"))
    assert len(dry_runs(app.read_events(private), flow.current_environment_hashes([UNIT], root))) == 1
    assert (STEP, CANDIDATE) not in open_now(private, root)


# --- the stale sign-off is refused at ingest -----------------------------------------------------------


def test_a_sign_off_made_before_the_unit_changed_is_refused(edited_root):
    root, private = edited_root
    page = tm_data(private / "pages" / page_name(CLEARER_1))
    edit_unit(root, lambda d: d.update(environment=d["environment"] + " changed"))
    rep = sign(private, answers(page), root=root, page=page)
    assert "stale" in " ".join(rep.lines) and runs(private) == []


# --- records.dry_runs ----------------------------------------------------------------------------------

H1, H2 = "a" * 64, "b" * 64


def run_event(*, at="2026-10-27T10:00:00+00:00", env=H1, passed=True, unit=UNIT, instructor=PROFESSIONAL, mode="remote",
              kind="dry_run", n=[0]):
    n[0] += 1
    failure = "rate-limit" if passed else None
    payload = {"candidate": events_candidate(instructor, unit, mode), "instructor": instructor, "unit": unit,
               "mode": mode, "passed": passed, "checks": {"clock": "pass" if passed else "fail"},
               "failure_injected": failure, "fallback_exercised": passed, "environment_sha256": env,
               "signoff_id": f"{n[0]:016x}"}
    return events.make_event(kind, payload["candidate"], "tm:person/clearer-1", payload, at=at)


def events_candidate(instructor, unit, mode):
    from teachermodel.workflow import candidate_uri

    return candidate_uri(instructor, unit, mode)


def test_a_passed_run_on_the_current_environment_counts():
    got = dry_runs([run_event()], {UNIT: H1})
    assert got == [rules.DryRun(instructor=PROFESSIONAL, unit=UNIT, mode="remote", passed=True, at=date(2026, 10, 27))]


def test_a_run_on_another_environment_is_left_out():
    assert dry_runs([run_event(env=H2)], {UNIT: H1}) == []


def test_a_run_on_a_unit_not_in_the_mapping_is_left_out():
    assert dry_runs([run_event()], {"sl:unit/other@1": H1}) == []
    assert dry_runs([run_event()], {}) == []


def test_a_run_that_did_not_pass_is_returned_as_not_passed():
    got = dry_runs([run_event(passed=False)], {UNIT: H1})
    assert [r.passed for r in got] == [False]


def test_other_event_kinds_and_other_units_are_ignored_and_the_result_is_oldest_first():
    log = [
        run_event(at="2026-10-29T10:00:00+00:00"),
        run_event(kind="check"),  # a different kind carrying the same payload
        run_event(at="2026-10-27T10:00:00+00:00", mode="hybrid"),
        run_event(at="2026-10-28T10:00:00+00:00", unit="sl:unit/other@1"),
    ]
    got = dry_runs(log, {UNIT: H1, "sl:unit/other@1": H1})
    assert [(r.at.isoformat(), r.unit, r.mode) for r in got] == [
        ("2026-10-27", UNIT, "hybrid"), ("2026-10-28", "sl:unit/other@1", "remote"), ("2026-10-29", UNIT, "remote")]


def test_only_the_environment_that_is_current_for_each_unit_counts():
    log = [run_event(env=H1, at="2026-10-27T10:00:00+00:00"), run_event(env=H2, at="2026-10-28T10:00:00+00:00")]
    got = dry_runs(log, {UNIT: H2})
    assert [r.at for r in got] == [date(2026, 10, 28)]


def test_the_records_feed_the_clearance_rule():
    got = dry_runs([run_event()], {UNIT: H1})
    assert got and isinstance(got[0], rules.DryRun)  # the zero-iteration trap: the list below is not empty
    assert [r for r in got if r.instructor == PROFESSIONAL and r.unit == UNIT and r.mode == "remote" and r.passed]


def test_current_hashes_read_the_unit_files_and_skip_a_unit_that_cannot_be_read():
    got = flow.current_environment_hashes([UNIT, "sl:unit/no-such-unit@1"])
    assert got == {UNIT: units.environment_sha256(units.load(UNIT))}


def test_the_candidate_in_a_real_event_matches_the_workflow_helper():
    assert events_candidate(PROFESSIONAL, UNIT, "remote") == CANDIDATE
    assert re.fullmatch(r"[0-9a-f]{32}", flow.dry_run_event_id("d0d0d0d0d0d0d0d0"))
