"""Plan/receipt bridge: build_plan idempotence and fail-closed receipt ingest (spec sections 5, 6, 11)."""

import json
from datetime import date

import pytest

from teachermodel import bridge, events, signoff
from teachermodel.standards import load_standards, validate
from teachermodel.workflow import PROGRAMME, Due, next_steps
from teachermodel.workflow import subjects as engine_subjects

WF = load_standards()["workflows"]


def subjects(events, base_codes=("IE",), notice_version=None):
    """The engine has no default base codes (the caller supplies the base profile's); these tests use Ireland's."""
    return engine_subjects(events, base_codes, notice_version)


NOW ="2026-10-26T08:00:00+00:00"
TODAY = date(2026, 10, 26)
ALICE = "tm:instructor/alice"  # fictional
BOB = "tm:instructor/bob"  # fictional
ALICE_MAIL = "alice@example.com"
OWNER_MAIL = "owner@example.com"
SETTINGS = {
    "library": "TeacherModel",
    "signoff_tag": "tm-signoff",
    "mailbox": "signoffs@example.com",
    "notice_tag": "[tm-notice 1]",
    "since": "2026-10-20",
}
RECIPIENTS = {ALICE: ALICE_MAIL}
H = "a" * 64
INPUT = signoff.input_sha256({"x": 1})
PEOPLE = [
    {"person": "tm:person/it-1", "name": "Pat Example", "email": "pat.it@example.com", "roles": ["it"]},
    {"person": "tm:person/mgr-1", "name": "Sam Example", "email": "sam.mgr@example.com", "roles": ["manager"]},
    {"person": "tm:person/mgr-2", "name": "Max Example", "email": "max.mgr@example.com", "roles": ["manager"]},
]
ROSTER = {
    "instructors": [
        {"instructor": ALICE, "identity": {"email": ALICE_MAIL}},
        {"instructor": BOB, "identity": {"email": "bob@example.com"}},
    ]
}
IDS = signoff.identities(PEOPLE, ROSTER)
OWNER = "tm:person/owner"
SUBJECTS = {
    PROGRAMME: {"kind": "programme"},
    ALICE: {"kind": "instructor", "type": "sme-engineer", "level": "shadow"},
    BOB: {"kind": "instructor", "type": "sme-engineer", "level": "shadow"},
}
REGS = {
    ALICE: {"type": "sme-engineer", "level": "shadow", "engagement": {"manager": "tm:person/mgr-1"}},
    BOB: {"type": "sme-engineer", "level": "shadow", "engagement": {"manager": "tm:person/mgr-2"}},
}
IT_DONE = "tm:step/it-done"


def due(step, subject=PROGRAMME, type_="verify", role="programme-owner"):
    return Due(step=step, workflow="tm:workflow/setup", subject=subject, role=role, due=None, overdue=False, page=None, type=type_)


LIB = due("tm:step/library-exists")
NOTICE = due("tm:step/notice-sent", ALICE)


def plan_for(*dues, created="2026-10-26"):
    plan, problems = bridge.build_plan(list(dues), settings=SETTINGS, recipients=RECIPIENTS, created=created)
    assert problems == []
    return plan


def op_of(plan, name):
    return next(o for o in plan["ops"] if o["op"] == name)


def receipt_for(plan, results, plan_sha=None, **kw):
    return {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": plan_sha or bridge.plan_sha256(plan),
        "driver": "fixture",
        "run_at": NOW,
        "results": results,
    } | kw


def res(op, status="ok", data=None, **kw):
    return {"op_id": op["op_id"], "status": status, "data": data if data is not None else {}, **kw}


def apply(plan, receipt, **kw):
    args = dict(
        workflows=WF,
        identities=IDS,
        current_input=lambda step, subject: INPUT,
        subjects=SUBJECTS,
        registrations=REGS,
        open_steps={(IT_DONE, PROGRAMME)},
        seen_ids=set(),
        existing_ids=set(),
        known_templates={H},
        owner_email=OWNER_MAIL,
        notice_version="1",
        now=NOW,
        allowed_drivers=("fixture",),
        current_rows=lambda s, sub: None,
    )
    args.update(kw)
    return bridge.apply_receipt(receipt, plan, **args)


def empty_results(plan, **overrides):
    """ok-and-empty answers for the standing mailbox op, so a test only fills what it cares about."""
    out = []
    for o in plan["ops"]:
        if o["op"] == "mail.tagged":
            out.append(res(o, data={"messages": []}))
        else:
            out.append(overrides.get(o["op"], res(o, "not_found")))
    return out


def signoff_doc(**kw):
    doc = {
        "schema": "tm:contract/signoff@1",
        "id": "0123456789abcdef",
        "step": IT_DONE,
        "subject_uri": PROGRAMME,
        "input_sha256": INPUT,
        "decision": "approve",
        "fields": {},
        "signer": "tm:person/it-1",
        "signed_at": "2026-10-26T07:00:00+00:00",
        "page_template_sha256": H,
    }
    doc.update(kw)
    return doc


def mail_with(doc, sender="pat.it@example.com", name="signoff.json", subject="[tm-signoff 0123456789abcdef]"):
    content = doc if isinstance(doc, str) else json.dumps(doc)
    return {"sender": sender, "subject": subject, "received": "2026-10-26T06:00:00Z",
            "attachments": [{"name": name, "content": content}]}


def with_mail(plan, *messages):
    out = empty_results(plan)
    for r in out:
        if r["op_id"] == op_of(plan, "mail.tagged")["op_id"]:
            r["data"] = {"messages": list(messages)}
    return out


def signoff_events(r):
    return [e for e in r.events if e["kind"] == "signoff"]


def rejected_checks(r):
    return [e for e in r.events if e["payload"].get("result") == "rejected"]


def sent_msg(**kw):
    m = {"sender": OWNER_MAIL, "to": [ALICE_MAIL], "subject": "Privacy notice [tm-notice 1]",
         "sentDateTime": "2026-10-23T10:00:00Z"}
    m.update(kw)
    return m


def notice_receipt(*messages):
    plan = plan_for(NOTICE)
    sent = op_of(plan, "mail.sent")
    return plan, sent, receipt_for(plan, empty_results(plan, **{"mail.sent": res(sent, data={"messages": list(messages)})}))


# --- receipt authenticity -------------------------------------------------------------------


def test_wrong_plan_hash_rejected():
    plan = plan_for(LIB)
    other = plan_for(LIB, NOTICE)
    r = apply(plan, receipt_for(plan, [res(op_of(plan, "site.library"), data={"exists": True})], plan_sha=bridge.plan_sha256(other)))
    assert r.events == []
    assert len(r.rejected) == 1 and "plan_sha256" in r.rejected[0]


def test_invalid_receipt_schema_rejected():
    plan = plan_for(LIB)
    r = apply(plan, {"schema": "tm:contract/receipt@1"})
    assert r.events == [] and r.rejected


def test_fixture_driver_only_when_explicitly_allowed():
    plan = plan_for(LIB)
    rc = receipt_for(plan, empty_results(plan))
    kw = dict(workflows=WF, identities=IDS, current_input=lambda s, sub: INPUT, current_rows=lambda s, sub: None,
              subjects=SUBJECTS, registrations=REGS,
              open_steps=set(), seen_ids=set(), existing_ids=set(), known_templates={H}, owner_email=OWNER_MAIL,
              notice_version="1", now=NOW)
    r = bridge.apply_receipt(rc, plan, **kw)  # default: connector, graph
    assert r.events == [] and r.rejected == ["receipt driver is not allowed"]
    assert bridge.apply_receipt(rc | {"driver": "connector"}, plan, **kw).events
    assert bridge.apply_receipt(rc | {"driver": "graph"}, plan, **kw).events
    assert bridge.apply_receipt(rc, plan, allowed_drivers=("fixture",), **kw).events


def test_run_at_before_plan_created_rejected():
    plan = plan_for(LIB, created="2026-10-26")
    r = apply(plan, receipt_for(plan, empty_results(plan), run_at="2026-10-25T23:59:59+00:00"))
    assert r.events == [] and r.rejected
    assert apply(plan, receipt_for(plan, empty_results(plan), run_at="2026-10-26T00:00:00+00:00")).events  # edge


def test_run_at_in_future_rejected():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, empty_results(plan), run_at="2026-10-26T08:00:01+00:00"))
    assert r.events == [] and r.rejected
    assert apply(plan, receipt_for(plan, empty_results(plan), run_at=NOW)).events  # edge: run_at == now


def test_unparseable_run_at_rejected():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, empty_results(plan), run_at="not a time at all"))
    assert r.events == [] and r.rejected


def test_receipt_cannot_be_replayed_against_a_later_plan():
    old = plan_for(LIB, created="2026-10-26")
    later = plan_for(LIB, created="2026-10-27")
    assert [o["op_id"] for o in old["ops"]] == [o["op_id"] for o in later["ops"]]  # same ops, other day
    rc = receipt_for(old, empty_results(old))
    r = apply(later, rc, now="2026-10-27T08:00:00+00:00")
    assert r.events == [] and "plan_sha256" in r.rejected[0]


# --- ops: library, errors, missing ----------------------------------------------------------


def test_error_op_leaves_step_open():
    plan = plan_for(LIB)
    lib = op_of(plan, "site.library")
    prior = [events.make_event("signoff", PROGRAMME, OWNER, {"step": IT_DONE, "decision": "approve"}, at="2026-10-20T09:00:00+00:00")]
    assert any(d.step == LIB.step for d in next_steps(WF, prior, subjects(prior), TODAY))
    r = apply(plan, receipt_for(plan, empty_results(plan, **{"site.library": res(lib, "error", error="timeout")})))
    chk = [e for e in r.events if e["payload"].get("op_id") == lib["op_id"]]
    assert len(chk) == 1 and chk[0]["kind"] == "check"
    assert chk[0]["payload"] == {"step": LIB.step, "op_id": lib["op_id"], "result": "error"}  # driver text not stored
    log = prior + r.events
    assert all(events.check_event(e) == [] for e in log)
    assert any(d.step == LIB.step for d in next_steps(WF, log, subjects(log), TODAY))


def test_missing_op_is_check_event():
    plan = plan_for(LIB)
    lib = op_of(plan, "site.library")
    results = [x for x in empty_results(plan) if x["op_id"] != lib["op_id"]]
    r = apply(plan, receipt_for(plan, results))
    chk = [e for e in r.events if e["payload"].get("op_id") == lib["op_id"]]
    assert len(chk) == 1
    assert chk[0]["kind"] == "check" and chk[0]["payload"]["result"] == "missing"
    assert chk[0]["payload"]["step"] == LIB.step


def test_library_exists_completes_step():
    plan = plan_for(LIB)
    lib = op_of(plan, "site.library")
    prior = [events.make_event("signoff", PROGRAMME, OWNER, {"step": IT_DONE, "decision": "approve"}, at="2026-10-20T09:00:00+00:00")]
    r = apply(plan, receipt_for(plan, empty_results(plan, **{"site.library": res(lib, data={"exists": True})})))
    assert all(events.check_event(e) == [] for e in r.events)
    log = prior + r.events
    assert not any(d.step == LIB.step for d in next_steps(WF, log, subjects(log), TODAY))


def test_library_not_exists_is_not_found():
    plan = plan_for(LIB)
    lib = op_of(plan, "site.library")
    r = apply(plan, receipt_for(plan, empty_results(plan, **{"site.library": res(lib, data={"exists": False})})))
    chk = [e for e in r.events if e["payload"].get("op_id") == lib["op_id"]]
    assert chk[0]["payload"]["result"] == "not_found"


def test_non_ok_inbox_op_writes_check_event():
    plan = plan_for(LIB)
    results = empty_results(plan)
    for x in results:
        if x["op_id"] == op_of(plan, "mail.tagged")["op_id"]:
            x["status"] = "error"
            x["error"] = "mailbox unavailable for jane.doe@example.com"
    r = apply(plan, receipt_for(plan, results))
    assert any(e["payload"].get("result") == "error" for e in r.events)
    assert not signoff_events(r)
    assert "jane" not in json.dumps(r.events)


# --- strict mail.sent evidence --------------------------------------------------------------


def test_notice_sent_sets_given_on():
    plan, sent, rc = notice_receipt(sent_msg(sentDateTime="2026-10-23T10:00:00Z"), sent_msg(sentDateTime="2026-10-22T16:30:00Z"))
    r = apply(plan, rc)
    notices = [e for e in r.events if e["kind"] == "notice"]
    assert len(notices) == 1
    n = notices[0]
    assert n["subject_uri"] == ALICE and n["actor"] == bridge.SYSTEM_ACTOR
    assert n["payload"] == {"step": NOTICE.step, "notice_version": "1", "notice_variant": "1", "given_on": "2026-10-22",
                         "op_id": sent["op_id"]}
    assert events.check_event(n) == []


def test_notice_given_on_is_the_utc_date():
    plan, _, rc = notice_receipt(sent_msg(sentDateTime="2026-10-22T23:30:00-02:00"))  # 01:30 UTC on the 23rd
    (n,) = [e for e in apply(plan, rc).events if e["kind"] == "notice"]
    assert n["payload"]["given_on"] == "2026-10-23"


def test_notice_matching_is_case_insensitive():
    plan, _, rc = notice_receipt(sent_msg(sender="OWNER@Example.com", to=["Alice@EXAMPLE.com", "other@example.com"]))
    assert [e for e in apply(plan, rc).events if e["kind"] == "notice"]


def test_notice_since_and_now_are_inclusive():
    plan, _, rc = notice_receipt(sent_msg(sentDateTime="2026-10-20T00:00:00Z"))
    assert [e for e in apply(plan, rc).events if e["kind"] == "notice"]
    plan, _, rc = notice_receipt(sent_msg(sentDateTime=NOW))
    assert [e for e in apply(plan, rc).events if e["kind"] == "notice"]


@pytest.mark.parametrize(
    "msg",
    [
        sent_msg(sender="mallory@example.com"),
        sent_msg(to=["someone-else@example.com"]),
        sent_msg(to=[]),
        sent_msg(subject="lunch"),
        sent_msg(sentDateTime="2026-10-19T23:59:59Z"),  # before since
        sent_msg(sentDateTime="2026-10-26T08:00:01Z"),  # after now
        sent_msg(sentDateTime="2026-10-26T08:00:01+00:00"),
        {"sentDateTime": "2026-10-23T10:00:00Z"},  # a bare timestamp is no evidence
    ],
)
def test_notice_strict_negatives(msg):
    plan, sent, rc = notice_receipt(msg)
    r = apply(plan, rc)
    assert not [e for e in r.events if e["kind"] == "notice"]
    chk = [e for e in r.events if e["payload"].get("op_id") == sent["op_id"]]
    assert len(chk) == 1 and chk[0]["payload"]["result"] == "not_found"


def test_notice_one_qualifying_message_among_noise_counts():
    plan, _, rc = notice_receipt(sent_msg(sender="mallory@example.com", sentDateTime="2026-10-21T00:00:00Z"), sent_msg())
    (n,) = [e for e in apply(plan, rc).events if e["kind"] == "notice"]
    assert n["payload"]["given_on"] == "2026-10-23"  # the unqualified earlier message is ignored


def test_known_negative_mail_sent():
    plan = plan_for(NOTICE)
    sent = op_of(plan, "mail.sent")
    for result in (res(sent, data={"messages": []}), res(sent, "not_found"), res(sent, "error", error="x")):
        r = apply(plan, receipt_for(plan, empty_results(plan, **{"mail.sent": result})))
        assert not [e for e in r.events if e["kind"] == "notice"]
        chk = [e for e in r.events if e["payload"].get("op_id") == sent["op_id"]]
        assert len(chk) == 1 and chk[0]["kind"] == "check" and chk[0]["payload"]["result"] != "ok"


@pytest.mark.parametrize(
    "bad",
    [
        {"sentDateTime": 20261023, "sender": OWNER_MAIL, "to": [ALICE_MAIL], "subject": "[tm-notice 1]"},
        sent_msg(sentDateTime="garbage"),
        "x",
        None,
        sent_msg(sender=None),
    ],
)
def test_notice_malformed_message_does_not_abort(bad):
    plan, sent, rc = notice_receipt(bad, sent_msg())
    r = apply(plan, rc)
    assert [e for e in r.events if e["kind"] == "notice"]  # the good message still counts
    assert all(events.check_event(e) == [] for e in r.events)


def test_notice_messages_not_a_list_is_error_check():
    plan = plan_for(NOTICE)
    sent = op_of(plan, "mail.sent")
    r = apply(plan, receipt_for(plan, empty_results(plan, **{"mail.sent": res(sent, data={"messages": "oops"})})))
    chk = [e for e in r.events if e["payload"].get("op_id") == sent["op_id"]]
    assert chk[0]["payload"]["result"] == "error"


# --- sign-off ingest ------------------------------------------------------------------------


def test_signoff_attachment_accepted():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc()))))
    so = signoff_events(r)
    assert len(so) == 1 and so[0]["actor"] == "tm:person/it-1" and so[0]["at"] == NOW
    assert so[0]["payload"]["signoff_id"] == "0123456789abcdef"
    assert events.check_event(so[0]) == []


def test_accepted_signoff_keeps_fields_out_of_the_log():
    plan = plan_for(LIB)
    doc = signoff_doc(fields={"note": "Jane Doe said X", "email": "jane@example.com"})
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))))
    (so,) = signoff_events(r)
    assert "fields" not in so["payload"]
    assert so["payload"]["fields_sha256"] == signoff.fields_sha256(doc)
    assert "jane" not in json.dumps(r.events).lower()
    assert r.private == [("signoffs/0123456789abcdef.json", doc)]


def test_private_documents_only_for_accepted_signoffs():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(input_sha256="b" * 64)))))
    assert r.private == [] and rejected_checks(r)


def test_stale_signoff_rejected_as_check_event():
    plan = plan_for(LIB)
    stale = signoff_doc(input_sha256=signoff.input_sha256({"x": 2}))
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(stale))))
    assert not signoff_events(r)
    chk = rejected_checks(r)
    assert len(chk) == 1 and chk[0]["kind"] == "check"
    assert chk[0]["payload"]["signoff_id"] == "0123456789abcdef"
    assert chk[0]["payload"]["step"] == IT_DONE
    assert chk[0]["payload"]["reasons"][0].startswith("stale: ")
    assert events.check_event(chk[0]) == []


def test_wrong_sender_rejected():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(), sender="mallory@example.com"))))
    assert not signoff_events(r)
    assert rejected_checks(r)


def test_duplicate_signoff_ignored():
    plan = plan_for(LIB)
    doc = signoff_doc()
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))), seen_ids={doc["id"]})  # already in the log
    assert not signoff_events(r) and not rejected_checks(r)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc), mail_with(doc))))  # twice in one receipt
    assert len(signoff_events(r)) == 1 and len(r.private) == 1


def test_a_signoff_mail_without_its_file_is_flagged_once_per_id():
    # 2026-10-27 pilot: three sign-offs mailed without the .json; the ingest said nothing
    plan = plan_for(LIB)
    bare = mail_with(signoff_doc())
    bare["attachments"] = [{"name": "image.png", "content_base64": "iVBORw0KGgo="}]  # a signature image
    inbox_copy = dict(bare, received="2026-10-26T06:00:05Z", attachments=[])
    r = apply(plan, receipt_for(plan, with_mail(plan, bare, inbox_copy)))
    chk = rejected_checks(r)
    assert len(chk) == 1 and chk[0]["payload"]["reasons"] == ["no sign-off file attached"]
    assert chk[0]["payload"]["signoff_id"] == "0123456789abcdef"
    assert events.check_event(chk[0]) == [] and not signoff_events(r)
    assert r.rejected == ["0123456789abcdef: no sign-off file attached"] * 2  # each copy is reported


def test_a_signoff_mail_without_a_usable_id_is_flagged_by_its_sender_and_subject():
    plan = plan_for(LIB)
    bare = dict(mail_with(signoff_doc(), subject="RE: [tm-signoff probe]"), attachments=[])
    r = apply(plan, receipt_for(plan, with_mail(plan, bare, dict(bare, received="2026-10-26T07:00:00Z"))))
    chk = rejected_checks(r)
    assert len(chk) == 1 and chk[0]["payload"]["signoff_id"] is None


def test_a_resent_signoff_is_accepted_after_the_bare_mail_was_flagged():
    plan = plan_for(LIB)
    doc = signoff_doc()
    bare = dict(mail_with(doc), attachments=[])
    r = apply(plan, receipt_for(plan, with_mail(plan, bare, mail_with(doc))))
    assert len(signoff_events(r)) == 1 and len(rejected_checks(r)) == 1


def test_unparseable_attachment_rejected():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with("{not json"))))
    chk = rejected_checks(r)
    assert len(chk) == 1 and chk[0]["payload"]["reasons"] == ["not JSON"]
    assert events.check_event(chk[0]) == []


def test_no_current_input_rejected():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc()))), current_input=lambda s, sub: None)
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["no current input for step"]
    assert not signoff_events(r)


def test_unknown_page_template_rejected():
    plan = plan_for(LIB)
    doc = signoff_doc(page_template_sha256="0" * 64)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))))
    assert not signoff_events(r)
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["unknown page template"]
    assert apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))), known_templates={"0" * 64}).events


# --- when a sign-off was signed (integration review finding 1) -------------------------------


def test_a_signoff_signed_before_the_step_opened_is_rejected():
    plan = plan_for(LIB)
    seen = []

    def opened_on(step, subject):
        seen.append((step, subject))
        return date(2026, 10, 25)

    doc = signoff_doc(signed_at="2026-10-20T07:00:00+00:00")
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))), opened_on=opened_on)
    assert not signoff_events(r) and r.private == []
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["signed_at is before the step opened"]
    assert seen == [(IT_DONE, PROGRAMME)]
    day = signoff_doc(signed_at="2026-10-25T00:00:00+00:00")  # the day it opened counts
    assert signoff_events(apply(plan, receipt_for(plan, with_mail(plan, mail_with(day))), opened_on=opened_on))


def test_a_signoff_signed_after_the_ingest_clock_plus_a_day_is_rejected():
    plan = plan_for(LIB)
    late = signoff_doc(signed_at="2026-10-27T08:00:01+00:00")  # NOW is 2026-10-26T08:00:00
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(late))))
    assert not signoff_events(r)
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["signed_at is in the future"]
    skew = signoff_doc(signed_at="2026-10-27T08:00:00+00:00")  # a day of clock skew is allowed
    assert signoff_events(apply(plan, receipt_for(plan, with_mail(plan, mail_with(skew)))))


def test_an_unknown_opening_day_sets_no_lower_bound():
    plan = plan_for(LIB)
    old = signoff_doc(signed_at="2020-01-01T00:00:00+00:00")
    assert signoff_events(apply(plan, receipt_for(plan, with_mail(plan, mail_with(old))), opened_on=lambda s, sub: None))


def test_the_backdating_scenario_a_signoff_cannot_claim_a_day_before_its_subject_existed():
    # An observer signs a sign-off for an assignment opened on the 26th but stamps it the 3rd, hoping to date their
    # evidence (and the observation event's `at`) before any rule that bites on the later date.
    plan = plan_for(LIB)
    assignment = "tm:assignment/0123456789abcdef"
    subjects_ = {**SUBJECTS, assignment: {"kind": "assignment", "observer": ALICE, "instructor": BOB,
                                          "candidate": "tm:candidate/bob--u-1--remote", "unit": "sl:unit/u@1",
                                          "mode": "remote", "length": "full", "lead": True, "delivery_ref": "d-1"}}
    ids = signoff.identities(PEOPLE, ROSTER, clearers=[ALICE])
    common = dict(subjects=subjects_, identities=ids, open_steps={("tm:step/observe", assignment)},
                  opened_on=lambda s, sub: date(2026, 10, 26))
    doc = signoff_doc(step="tm:step/observe", subject_uri=assignment, signer=ALICE, signed_at="2026-10-26T07:00:00+00:00")
    honest = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc, sender=ALICE_MAIL))), **common)
    assert len(signoff_events(honest)) == 1  # the same sign-off, stamped on the day the assignment opened, counts
    backdated = {**doc, "signed_at": "2026-10-03T09:00:00+00:00"}
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(backdated, sender=ALICE_MAIL))), **common)
    assert not signoff_events(r)
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["signed_at is before the step opened"]


def test_non_approving_decision_is_recorded_but_does_not_complete_the_step():
    plan = plan_for(LIB)
    doc = signoff_doc(decision="reject")
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))))
    (so,) = signoff_events(r)
    assert so["payload"]["decision"] == "reject"
    log = [events.make_event("step", PROGRAMME, bridge.SYSTEM_ACTOR, {"step": "tm:step/it-request"}, at="2026-10-20T09:00:00+00:00")] + r.events
    assert any(d.step == IT_DONE for d in next_steps(WF, log, subjects(log), TODAY))


# --- subject-bound signers, open steps, step types ------------------------------------------


def mgr_doc(subject=ALICE, signer="tm:person/mgr-1", **kw):
    return signoff_doc(id="fedcba9876543210", step="tm:step/commitment-manager", subject_uri=subject, signer=signer, **kw)


def mgr_apply(doc, sender, **kw):
    plan = plan_for(LIB)
    base = dict(open_steps={("tm:step/commitment-manager", ALICE), ("tm:step/commitment-manager", BOB)})
    base.update(kw)
    return apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc, sender=sender))), **base)


def test_manager_must_be_the_subjects_manager():
    r = mgr_apply(mgr_doc(), "sam.mgr@example.com")
    (so,) = signoff_events(r)
    assert so["subject_uri"] == ALICE and so["actor"] == "tm:person/mgr-1"
    # a different manager who holds the role is still not Alice's manager
    r = mgr_apply(mgr_doc(signer="tm:person/mgr-2"), "max.mgr@example.com")
    assert not signoff_events(r)
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["signer is not the expected tm:person/mgr-1"]


def test_instructor_cannot_sign_for_another_instructor():
    plan = plan_for(LIB)
    doc = signoff_doc(id="fedcba9876543211", step="tm:step/baseline-self-assessment", subject_uri=BOB, signer=ALICE)
    open_ = {("tm:step/baseline-self-assessment", BOB), ("tm:step/baseline-self-assessment", ALICE)}
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc, sender=ALICE_MAIL))), open_steps=open_)
    assert not signoff_events(r)
    assert rejected_checks(r)[0]["payload"]["reasons"] == [f"signer is not the expected {BOB}"]
    own = signoff_doc(id="fedcba9876543212", step="tm:step/baseline-self-assessment", subject_uri=ALICE, signer=ALICE)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(own, sender=ALICE_MAIL))), open_steps=open_)
    assert len(signoff_events(r)) == 1


def test_subject_bound_role_without_registration_rejected():
    r = mgr_apply(mgr_doc(), "sam.mgr@example.com", registrations={})
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["no expected signer"]
    r = mgr_apply(mgr_doc(), "sam.mgr@example.com", registrations={ALICE: {"type": "sme-engineer"}})
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["no expected signer"]
    assert not signoff_events(r)


def test_subject_kind_must_match_step():
    # an instructor step signed against the programme subject
    r = mgr_apply(mgr_doc(subject=PROGRAMME), "sam.mgr@example.com", open_steps={("tm:step/commitment-manager", PROGRAMME)})
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["subject kind does not match step"]
    # a programme step signed against an instructor
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(subject_uri=ALICE)))), open_steps={(IT_DONE, ALICE)})
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["subject kind does not match step"]


def test_unknown_subject_rejected_and_logged_under_the_programme():
    ghost = "tm:instructor/ghost"
    r = mgr_apply(mgr_doc(subject=ghost), "sam.mgr@example.com", open_steps={("tm:step/commitment-manager", ghost)})
    (chk,) = rejected_checks(r)
    assert chk["payload"]["reasons"] == ["unknown subject"]
    assert chk["subject_uri"] == PROGRAMME and events.check_event(chk) == []


def test_only_open_steps_take_signoffs():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc()))), open_steps=set())
    assert not signoff_events(r)
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["step not open"]
    # open for another subject is not open for this one
    r = mgr_apply(mgr_doc(), "sam.mgr@example.com", open_steps={("tm:step/commitment-manager", BOB)})
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["step not open"]


@pytest.mark.parametrize("step", ["tm:step/library-exists", "tm:step/it-request", "tm:step/notice-sent"])
def test_auto_and_verify_steps_never_take_signoffs(step):
    plan = plan_for(LIB)
    subject = ALICE if step == "tm:step/notice-sent" else PROGRAMME
    doc = signoff_doc(step=step, subject_uri=subject)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))), open_steps={(step, subject)})
    assert not signoff_events(r)
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["step does not take sign-offs"]


def test_unknown_step_rejected():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(step="tm:step/mystery")))))
    assert rejected_checks(r)[0]["payload"]["reasons"] == ["unknown step or no subject"]


# --- robustness -----------------------------------------------------------------------------

GOOD_B64 = json.dumps(signoff_doc())
TAGGED = "[tm-signoff 0123456789abcdef]"


@pytest.mark.parametrize(
    "message",
    [
        "notadict",
        None,
        42,
        [],
        {"subject": TAGGED, "sender": None, "attachments": [{"name": "a.json", "content": GOOD_B64}]},
        {"subject": TAGGED, "sender": 7, "attachments": [{"name": "a.json", "content": GOOD_B64}]},
        {"subject": TAGGED, "sender": "pat.it@example.com", "attachments": "oops"},
        {"subject": TAGGED, "sender": "pat.it@example.com", "attachments": ["x", None, 3]},
        {"subject": TAGGED, "sender": "pat.it@example.com", "attachments": [{"name": None, "content": GOOD_B64}]},
        {"subject": TAGGED, "sender": "pat.it@example.com", "attachments": [{"name": 5, "content": GOOD_B64}]},
        {"subject": TAGGED, "sender": "pat.it@example.com", "attachments": [{"name": "a.json", "content": None}]},
        {"subject": TAGGED, "sender": "pat.it@example.com", "attachments": [{"name": "a.json", "content": 12}]},
        {"subject": TAGGED, "sender": "pat.it@example.com", "attachments": [{"name": "a.json", "content": "[1, 2]"}]},
    ],
)
def test_malformed_message_or_attachment_is_a_rejection_not_a_crash(message):
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, message, mail_with(signoff_doc(id="aaaaaaaaaaaaaaaa")))))
    assert rejected_checks(r), message
    assert len(signoff_events(r)) == 1  # the good message after it is still processed
    assert all(events.check_event(e) == [] for e in r.events)


@pytest.mark.parametrize(
    "kw",
    [
        {"id": 123},
        {"id": ["x"]},
        {"id": {"a": 1}},
        {"subject_uri": ["x"]},
        {"step": ["x"]},
        {"step": 5},
        {"signed_at": "2026-99-99T99:99"},
        {"signed_at": 20261026},
        {"signer": "Jane Doe <jane.doe@example.com>"},
        {"step": "Jane Doe evidence note"},
        {"subject_uri": "tm:nope"},
        {"subject_uri": "not-a-uri"},
    ],
)
def test_bad_fields_reject_cleanly_and_leak_nothing(kw):
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(**kw)))))
    assert not signoff_events(r)
    (chk,) = rejected_checks(r)
    assert events.check_event(chk) == []
    assert chk["subject_uri"] == PROGRAMME
    assert "jane" not in json.dumps(r.events).lower() and "not-a-uri" not in json.dumps(r.events)


# --- no personal data or free text in the log -----------------------------------------------


def test_check_event_step_and_signoff_id_are_pattern_guarded():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(id="Jane Doe", step="tm:step/Jane Doe")))))
    (chk,) = rejected_checks(r)
    assert chk["payload"]["step"] is None and chk["payload"]["signoff_id"] is None
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(step=IT_DONE, input_sha256="b" * 64)))))
    (chk,) = rejected_checks(r)
    assert chk["payload"]["step"] == IT_DONE and chk["payload"]["signoff_id"] == "0123456789abcdef"


def test_driver_error_text_is_not_stored():
    plan = plan_for(LIB)
    lib = op_of(plan, "site.library")
    r = apply(plan, receipt_for(plan, empty_results(plan, **{"site.library": res(lib, "error", error="user jane@example.com denied")})))
    assert "jane" not in json.dumps(r.events)


# --- determinism and idempotency ------------------------------------------------------------


def test_event_ids_are_deterministic_and_reapplying_yields_nothing():
    plan = plan_for(LIB, NOTICE)
    lib = op_of(plan, "site.library")
    sent = op_of(plan, "mail.sent")
    results = with_mail(plan, mail_with(signoff_doc()), mail_with("{bad"))
    for x in results:
        if x["op_id"] == lib["op_id"]:
            x.update(data={"exists": True})
        if x["op_id"] == sent["op_id"]:
            x.update(status="ok", data={"messages": [sent_msg()]})
    rc = receipt_for(plan, results)
    a, b = apply(plan, rc), apply(plan, rc)
    assert a.events and [e["id"] for e in a.events] == [e["id"] for e in b.events]
    assert len({e["id"] for e in a.events}) == len(a.events)
    assert all(len(e["id"]) == 32 for e in a.events)
    again = apply(plan, rc, existing_ids={e["id"] for e in a.events}, seen_ids={"0123456789abcdef"})
    assert again.events == [] and again.private == []
    # a different plan (other created day) gives different ids for the same facts
    later = plan_for(LIB, NOTICE, created="2026-10-26T00:00:00")  # distinct created stamp
    c = apply(later, receipt_for(later, [dict(x) for x in empty_results(later)]))
    assert not {e["id"] for e in c.events} & {e["id"] for e in a.events}


def test_partial_existing_ids_only_drop_those_events():
    plan = plan_for(LIB)
    rc = receipt_for(plan, with_mail(plan, mail_with(signoff_doc()), mail_with("{bad")))
    full = apply(plan, rc)
    assert len(full.events) == 3  # library not_found, signoff, rejection
    drop = next(e["id"] for e in full.events if e["kind"] == "signoff")
    rest = apply(plan, rc, existing_ids={drop})
    assert len(rest.events) == 2 and rest.private == []


# --- library channel ------------------------------------------------------------------------


def test_library_channel_is_disabled():
    plan = plan_for(LIB)
    fg = bridge._op("file.get", {"library": "TeacherModel", "folder": "inbox"}, None, None)
    plan = {**plan, "ops": sorted(plan["ops"] + [fg], key=lambda o: o["op_id"])}
    assert validate(plan, "plan.schema.json") == []
    files = {"files": [{"name": "s.json", "created_by": "pat.it@example.com", "content": json.dumps(signoff_doc())}]}
    results = empty_results(plan, **{"file.get": res(fg, data=files)})
    r = apply(plan, receipt_for(plan, results))
    assert not signoff_events(r) and r.private == []
    (chk,) = rejected_checks(r)
    assert chk["payload"]["reasons"] == [bridge.LIBRARY_CHANNEL_DISABLED]
    assert "createdBy unavailable" in r.rejected[0]
    assert events.check_event(chk) == []


# --- build_plan -----------------------------------------------------------------------------


def test_build_plan_idempotent():
    a = plan_for(LIB, NOTICE)
    b = plan_for(NOTICE, LIB, LIB)
    assert bridge.plan_sha256(a) == bridge.plan_sha256(b)  # same due list, same created
    later = plan_for(LIB, NOTICE, created="2026-11-30")
    assert bridge.plan_sha256(later) != bridge.plan_sha256(a)  # other created: other hash
    assert [o["op_id"] for o in later["ops"]] == [o["op_id"] for o in a["ops"]]
    assert [o["op_id"] for o in a["ops"]] == sorted(o["op_id"] for o in a["ops"])
    assert len({o["op_id"] for o in a["ops"]}) == len(a["ops"])
    assert validate(a, "plan.schema.json") == []


def test_build_plan_ops_content():
    plan = plan_for(LIB, NOTICE)
    assert op_of(plan, "site.library")["args"] == {"library": "TeacherModel", "name": "TeacherModel"}
    sent = op_of(plan, "mail.sent")
    assert sent["args"] == {"to": ALICE_MAIL, "tag": "[tm-notice 1]", "since": "2026-10-20"} and sent["subject"] == ALICE
    assert op_of(plan, "mail.tagged")["args"] == {
        "tag": "tm-signoff", "since": "2026-10-20", "mailbox": "signoffs@example.com"}
    assert "file.get" not in {o["op"] for o in plan["ops"]}  # no standing library read


@pytest.mark.parametrize("library, name", [
    ("teachermodel-pilot", "teachermodel pilot"),  # probe 2026-10-27: the hyphenated name finds nothing
    ("sites/Training/Teacher_Model", "Teacher Model"),
    ("TeacherModel/", "TeacherModel"),
])
def test_the_library_search_name_is_the_last_segment_without_punctuation(library, name):
    assert bridge.library_search_name(library) == name


def test_op_id_depends_on_args():
    assert bridge.op_id("site.library", {"library": "A"}) != bridge.op_id("site.library", {"library": "B"})
    assert len(bridge.op_id("site.library", {"library": "A"})) == 16


def test_unknown_verify_step_raises():
    with pytest.raises(ValueError, match="tm:step/mystery"):
        plan_for(due("tm:step/mystery"))


def test_missing_recipient_is_a_problem_not_a_crash():
    plan, problems = bridge.build_plan(
        [due("tm:step/notice-sent", "tm:instructor/nobody"), NOTICE, LIB],
        settings=SETTINGS, recipients=RECIPIENTS, created="2026-10-26",
    )
    assert problems == ["no recipient address for tm:instructor/nobody"]
    assert [o["subject"] for o in plan["ops"] if o["op"] == "mail.sent"] == [ALICE]  # the others are planned
    assert op_of(plan, "site.library")


def test_non_verify_dues_ignored():
    plan = plan_for(due("tm:step/it-done", type_="human"))
    assert {o["op"] for o in plan["ops"]} == {"mail.tagged"}


# --- end to end with the real workflow definitions ------------------------------------------


def test_end_to_end_notice_sent_closes_notice_step():
    at = "2026-10-05T09:00:00+00:00"

    def ev(kind, subject, payload):
        return events.make_event(kind, subject, bridge.SYSTEM_ACTOR, payload, at=at)

    log = [ev("registration", ALICE, {"type": "professional", "level": "shadow", "jurisdiction": "IE"})]
    for sid in ("it-request", "ropa", "notice-text", "roster-import"):
        log.append(ev("step", PROGRAMME, {"step": f"tm:step/{sid}"}))
    for sid in ("it-done", "dpia-screening", "retention-periods", "notice-text-approved"):
        log.append(ev("signoff", PROGRAMME, {"step": f"tm:step/{sid}", "decision": "approve"}))
    log.append(ev("check", PROGRAMME, {"step": "tm:step/library-exists", "result": "ok"}))
    log.append(ev("step", ALICE, {"step": "tm:step/notice-drafts"}))

    def queue():
        return next_steps(WF, log, subjects(log, notice_version="1"), TODAY)

    assert ("tm:step/notice-sent", ALICE) in {(d.step, d.subject) for d in queue()}

    plan, problems = bridge.build_plan(queue(), settings=SETTINGS, recipients=RECIPIENTS, created="2026-10-26")
    assert problems == [] and op_of(plan, "mail.sent")["subject"] == ALICE
    sent = op_of(plan, "mail.sent")
    results = empty_results(plan, **{"mail.sent": res(sent, data={"messages": [sent_msg(sender="mallory@example.com"), sent_msg()]})})
    r = apply(plan, receipt_for(plan, results), open_steps={(d.step, d.subject) for d in queue() if d.type == "human"})
    assert [e["kind"] for e in r.events if e["kind"] == "notice"] == ["notice"]
    assert all(events.check_event(e) == [] for e in r.events)

    log += r.events
    assert ("tm:step/notice-sent", ALICE) not in {(d.step, d.subject) for d in queue()}
    # a receipt whose message was not sent by the owner leaves the step open
    log2 = [e for e in log if e["kind"] != "notice"]
    bad = empty_results(plan, **{"mail.sent": res(sent, data={"messages": [sent_msg(sender="mallory@example.com")]})})
    r2 = apply(plan, receipt_for(plan, bad))
    assert ("tm:step/notice-sent", ALICE) in {(d.step, d.subject) for d in next_steps(WF, log2 + r2.events, subjects(log2, notice_version="1"), TODAY)}


# --- review fixes: sender format, shared mailbox, attachments, run_at, rejection growth -----------

EXCHANGE_DN = "/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP (FYDIBOHF23SPDLT)/CN=RECIPIENTS/CN=0123abcd-pat"


def test_build_plan_needs_the_mailbox_setting():
    bad = {k: v for k, v in SETTINGS.items() if k != "mailbox"}
    with pytest.raises(KeyError):
        bridge.build_plan([LIB], settings=bad, recipients=RECIPIENTS, created="2026-10-26")


@pytest.mark.parametrize("sender", [EXCHANGE_DN, "", "no-at-sign", "a b@example.com", "a@b@example.com", "a/b@example.com",
                                    "pat.it@ example.com"])
def test_tagged_sender_must_be_an_smtp_address(sender):
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(), sender=sender))))
    assert not signoff_events(r) and r.private == []
    (chk,) = rejected_checks(r)
    assert chk["payload"]["reasons"] == ["sender is not an SMTP address"]
    assert events.check_event(chk) == []
    assert "EXCHANGELABS" not in json.dumps(r.events)


def test_notice_sender_must_be_an_smtp_address():
    # an Exchange DN never equals the owner address, but the rejection says why instead of "not_found"
    plan, sent, rc = notice_receipt(sent_msg(sender=EXCHANGE_DN))
    r = apply(plan, rc)
    assert not [e for e in r.events if e["kind"] == "notice"]
    assert [c["payload"]["reasons"] for c in rejected_checks(r)] == [["sender is not an SMTP address"]]
    # the good message next to it still counts
    plan, sent, rc = notice_receipt(sent_msg(sender=EXCHANGE_DN), sent_msg())
    assert [e for e in apply(plan, rc).events if e["kind"] == "notice"]


def test_plan_carries_the_mailbox_and_the_bare_search_tag():
    args = op_of(plan_for(LIB), "mail.tagged")["args"]
    assert args["mailbox"] == "signoffs@example.com" and args["tag"] == "tm-signoff"


def test_shared_mailbox_messages_without_the_subject_tag_are_ignored():
    plan = plan_for(LIB)
    other = mail_with(signoff_doc(id="aaaaaaaaaaaaaaaa"), subject="Weekly newsletter", sender=EXCHANGE_DN)
    nosubject = {"sender": "pat.it@example.com", "attachments": [{"name": "x.json", "content": "{bad"}]}
    r = apply(plan, receipt_for(plan, with_mail(plan, other, nosubject, mail_with(signoff_doc()))))
    assert len(signoff_events(r)) == 1 and not rejected_checks(r)
    assert signoff_events(r)[0]["payload"]["signoff_id"] == "0123456789abcdef"


def test_subject_tag_is_the_bracketed_form():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc(), subject="tm-signoff without bracket"))))
    assert not signoff_events(r) and not rejected_checks(r)


def b64_mail(doc, **kw):
    import base64

    raw = doc if isinstance(doc, bytes) else (doc if isinstance(doc, str) else json.dumps(doc)).encode("utf-8")
    m = mail_with("x", **kw)
    m["attachments"] = [{"name": "signoff.json", "content_base64": base64.b64encode(raw).decode("ascii")}]
    return m


def test_attachment_content_base64_is_decoded():
    plan = plan_for(LIB)
    doc = signoff_doc(fields={"note": "café"})
    r = apply(plan, receipt_for(plan, with_mail(plan, b64_mail(doc))))
    (so,) = signoff_events(r)
    assert r.private == [("signoffs/0123456789abcdef.json", doc)]
    assert so["payload"]["fields_sha256"] == signoff.fields_sha256(doc)


def test_attachment_utf8_text_content_still_works():
    plan = plan_for(LIB)
    assert len(signoff_events(apply(plan, receipt_for(plan, with_mail(plan, mail_with(signoff_doc())))))) == 1


@pytest.mark.parametrize("bad", ["not base64 !!!", "YWJj\nZGVm", "abc", 12, None])
def test_attachment_bad_base64_is_rejected(bad):
    plan = plan_for(LIB)
    m = mail_with("x")
    m["attachments"] = [{"name": "signoff.json", "content_base64": bad}]
    r = apply(plan, receipt_for(plan, with_mail(plan, m)))
    assert not signoff_events(r)
    assert len(rejected_checks(r)) == 1


def test_attachment_base64_that_is_not_utf8_is_rejected():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, with_mail(plan, b64_mail(b"\xff\xfe\x00{"))))
    assert not signoff_events(r) and len(rejected_checks(r)) == 1


@pytest.mark.parametrize("run_at", ["2026-10-26T07:00:00", "2026-10-26 07:00:00", "2026-10-26"])
def test_naive_run_at_is_an_error_not_utc(run_at):
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, empty_results(plan), run_at=run_at))
    assert r.events == [] and r.rejected == ["run_at must carry a UTC offset"]
    for ok in ("2026-10-26T07:00:00Z", "2026-10-26T09:00:00+02:00"):
        assert apply(plan, receipt_for(plan, empty_results(plan), run_at=ok)).events


DAY2 = dict(now="2026-10-27T08:00:00+00:00")


def day2_receipt(plan, results):
    return receipt_for(plan, results, run_at="2026-10-27T07:00:00+00:00")


def test_same_bad_message_on_two_days_logs_one_rejection():
    day1 = plan_for(LIB, created="2026-10-26")
    day2 = plan_for(LIB, created="2026-10-27")
    bad = mail_with(signoff_doc(input_sha256="b" * 64))
    r1 = apply(day1, receipt_for(day1, with_mail(day1, bad)))
    assert len(rejected_checks(r1)) == 1
    existing = {e["id"] for e in r1.events}
    r2 = apply(day2, day2_receipt(day2, with_mail(day2, bad)), existing_ids=existing, **DAY2)
    assert rejected_checks(r2) == [] and r2.rejected  # still reported, not logged again
    # a different reason for the same sign-off is new information
    r3 = apply(day2, day2_receipt(day2, with_mail(day2, bad)), existing_ids=existing, open_steps=set(), **DAY2)
    assert len(rejected_checks(r3)) == 1


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_same_unidentifiable_attachment_on_two_days_logs_one_rejection(content):
    day1 = plan_for(LIB, created="2026-10-26")
    day2 = plan_for(LIB, created="2026-10-27")
    r1 = apply(day1, receipt_for(day1, with_mail(day1, mail_with(content))))
    assert len(rejected_checks(r1)) == 1
    existing = {e["id"] for e in r1.events}
    r2 = apply(day2, day2_receipt(day2, with_mail(day2, mail_with(content))), existing_ids=existing, **DAY2)
    assert rejected_checks(r2) == []
    other = apply(day2, day2_receipt(day2, with_mail(day2, mail_with(content + " "))), existing_ids=existing, **DAY2)
    assert len(rejected_checks(other)) == 1  # different content, different rejection


def test_same_malformed_message_on_two_days_logs_one_rejection():
    day1 = plan_for(LIB, created="2026-10-26")
    day2 = plan_for(LIB, created="2026-10-27")
    bad = {"subject": "[tm-signoff x]", "sender": None, "attachments": []}
    r1 = apply(day1, receipt_for(day1, with_mail(day1, bad)))
    r2 = apply(day2, day2_receipt(day2, with_mail(day2, bad)), existing_ids={e["id"] for e in r1.events}, **DAY2)
    assert len(rejected_checks(r1)) == 1 and rejected_checks(r2) == []


def test_mailbox_read_time_is_reported_only_for_an_ok_tagged_read():
    plan = plan_for(LIB)
    r = apply(plan, receipt_for(plan, empty_results(plan)))
    assert r.mailbox_read_at is not None and r.mailbox_read_at.isoformat() == "2026-10-26T08:00:00+00:00"
    errored = empty_results(plan)
    for x in errored:
        if x["op_id"] == op_of(plan, "mail.tagged")["op_id"]:
            x["status"] = "error"
    assert apply(plan, receipt_for(plan, errored)).mailbox_read_at is None
    assert apply(plan, receipt_for(plan, empty_results(plan), plan_sha="0" * 64)).mailbox_read_at is None


def test_duplicate_signoffs_are_reported_for_the_caller():
    plan = plan_for(LIB)
    doc = signoff_doc()
    r = apply(plan, receipt_for(plan, with_mail(plan, mail_with(doc))), seen_ids={doc["id"]})
    assert r.duplicates == [doc] and not r.private and not signoff_events(r)


def test_content_rules_apply_at_ingest():
    plan = plan_for(LIB)
    dpo = {"person": "tm:person/dpo-1", "name": "Dana Example", "email": "dana.dpo@example.com", "roles": ["dpo"]}
    ids = signoff.identities(PEOPLE + [dpo], ROSTER)
    step = "tm:step/dpia-screening"
    kw = dict(identities=ids, open_steps={(step, PROGRAMME)})

    def go(decision):
        d = signoff_doc(step=step, signer="tm:person/dpo-1", fields={"dpo-decision": decision})
        return apply(plan, receipt_for(plan, with_mail(plan, mail_with(d, sender="dana.dpo@example.com"))), **kw)

    ok = go("dpia-not-required")
    assert len(signoff_events(ok)) == 1
    for decision in ("dpia-required", "needs-more-information"):
        r = go(decision)
        assert not signoff_events(r) and r.private == []
        assert rejected_checks(r)[0]["payload"]["reasons"] == ["DPIA required or undecided"]


# --- notice variants: the op tag and the notice event carry the variant (privacy overlay) ------------------------


def plan_with_variants(variants, *dues):
    return bridge.build_plan(list(dues), settings=SETTINGS, recipients={**RECIPIENTS, BOB: "bob@example.com"},
                             created="2026-10-26", variants=variants)


def test_the_notice_sent_op_tag_names_each_instructors_variant():
    bob_notice = due("tm:step/notice-sent", BOB)
    plan, problems = plan_with_variants({ALICE: "2026-11", BOB: "2026-11-us-ca"}, NOTICE, bob_notice)
    assert problems == []
    tags = {o["subject"]: o["args"]["tag"] for o in plan["ops"] if o["op"] == "mail.sent"}
    assert tags == {ALICE: "[tm-notice 2026-11]", BOB: "[tm-notice 2026-11-us-ca]"}
    assert validate(plan, "plan.schema.json") == []


def test_an_instructor_with_no_variant_is_a_problem_when_variants_are_given():
    plan, problems = plan_with_variants({ALICE: "2026-11"}, NOTICE, due("tm:step/notice-sent", BOB))
    assert problems == [f"no notice variant for {BOB}"]
    assert [o["subject"] for o in plan["ops"] if o["op"] == "mail.sent"] == [ALICE]


def variant_receipt(variant, *messages):
    plan, _ = plan_with_variants({ALICE: variant}, NOTICE)
    sent = op_of(plan, "mail.sent")
    return plan, sent, receipt_for(plan, empty_results(plan, **{"mail.sent": res(sent, data={"messages": list(messages)})}))


def test_the_notice_event_carries_the_variant_of_the_tag():
    for variant in ("2026-11", "2026-11-us-ca"):
        msg = sent_msg(subject=f"Privacy notice: instructor development [tm-notice {variant}]")
        plan, sent, rc = variant_receipt(variant, msg)
        (n,) = [e for e in apply(plan, rc).events if e["kind"] == "notice"]
        assert n["payload"]["notice_variant"] == variant and n["payload"]["notice_version"] == "1", variant
        assert events.check_event(n) == []


def test_a_mail_with_the_base_tag_does_not_close_the_variant_and_the_reverse():
    base = sent_msg(subject="Privacy notice [tm-notice 2026-11]")
    ca = sent_msg(subject="Privacy notice [tm-notice 2026-11-us-ca]")
    plan, _, rc = variant_receipt("2026-11-us-ca", base)
    assert not [e for e in apply(plan, rc).events if e["kind"] == "notice"]
    plan, _, rc = variant_receipt("2026-11", ca)
    assert not [e for e in apply(plan, rc).events if e["kind"] == "notice"]


def test_a_tag_that_is_not_a_notice_tag_gives_a_notice_without_a_variant():
    plan = bridge.build_plan([NOTICE], settings={**SETTINGS, "notice_tag": "weird"}, recipients=RECIPIENTS,
                             created="2026-10-26")[0]
    sent = op_of(plan, "mail.sent")
    rc = receipt_for(plan, empty_results(plan, **{"mail.sent": res(sent, data={"messages": [sent_msg(subject="weird")]})}))
    (n,) = [e for e in apply(plan, rc).events if e["kind"] == "notice"]
    assert "notice_variant" not in n["payload"]  # nothing to match the instructor's expected variant: stays open
