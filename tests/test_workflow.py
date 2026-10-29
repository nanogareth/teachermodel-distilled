from datetime import date

from teachermodel.events import make_event
from teachermodel.standards import load_standards
from teachermodel.workflow import PROGRAMME, SYSTEM_ACTOR, Due, next_steps
from teachermodel.workflow import subjects as engine_subjects

TODAY = date(2026, 10, 24)
ACTOR = "tm:person/owner"
ALICE = "tm:instructor/alice"  # fictional
BOB = "tm:instructor/bob"  # fictional
PAUL = "tm:instructor/paul"  # fictional, partner


def subjects(events, base_codes=("IE",), notice_version=None):
    """The engine has no default base codes (the caller supplies the base profile's); these tests use Ireland's."""
    return engine_subjects(events, base_codes, notice_version)


def ev(kind, subject, payload, day="2026-10-01"):
    return make_event(kind, subject, ACTOR, payload, at=f"{day}T09:00:00+00:00")


def reg(uri, type_, day="2026-10-01", level="shadow"):
    return ev("registration", uri, {"type": type_, "level": level}, day)


def done(step, subject, day="2026-10-01", kind="signoff"):
    payload = {"step": step, "decision": "approve"} if kind == "signoff" else {"step": step}
    return ev(kind, subject, payload, day)


def step(sid, **kw):
    base = {
        "id": f"tm:step/{sid}",
        "name": sid,
        "type": "human",
        "role": "coordinator",
        "subject": "instructor",
        "needs": [],
        "done_when": {"kind": "signoff", "match": {"step": f"tm:step/{sid}"}},
        "page": "approve",
        "basis": "test",
    }
    base.update(kw)
    return base


def doc(*steps):
    return {"workflows": [{"id": "tm:workflow/t", "name": "t", "basis": "test", "steps": list(steps)}]}


def ids(dues):
    return [(d.step, d.subject) for d in dues]


# --- subjects -------------------------------------------------------------------------------


def test_subjects_programme_and_instructors():
    s = subjects([reg(ALICE, "sme-engineer"), reg(PAUL, "partner")])
    assert s == {
        PROGRAMME: {"kind": "programme"},
        ALICE: {"kind": "instructor", "type": "sme-engineer", "level": "shadow"},
        PAUL: {"kind": "instructor", "type": "partner", "level": "shadow"},
    }


def test_subjects_later_registration_overrides():
    s = subjects([reg(ALICE, "contractor", "2026-10-01"), reg(ALICE, "professional", "2026-10-02")])
    assert s[ALICE]["type"] == "professional"


def test_subjects_empty_log_is_programme_only():
    assert subjects([]) == {PROGRAMME: {"kind": "programme"}}


def test_subjects_skips_registration_without_str_type():
    bad = ev("registration", BOB, {"level": "shadow"})
    worse = ev("registration", PAUL, {"type": ["partner"], "level": "shadow"})
    assert subjects([bad, worse, reg(ALICE, "professional")]).keys() == {PROGRAMME, ALICE}


# --- gating ---------------------------------------------------------------------------------


def test_needs_gate():
    wf = doc(step("a"), step("b", needs=["tm:step/a"]))
    events = [reg(ALICE, "professional")]
    s = subjects(events)
    assert ids(next_steps(wf, events, s, TODAY)) == [("tm:step/a", ALICE)]
    events.append(done("tm:step/a", ALICE))
    assert ids(next_steps(wf, events, s, TODAY)) == [("tm:step/b", ALICE)]


def test_need_done_for_another_subject_does_not_count():
    wf = doc(step("a"), step("b", needs=["tm:step/a"]))
    events = [reg(ALICE, "professional"), reg(BOB, "professional"), done("tm:step/a", ALICE)]
    got = ids(next_steps(wf, events, subjects(events), TODAY))
    assert got == [("tm:step/a", BOB), ("tm:step/b", ALICE)]


def test_applies_to_filters_type():
    wf = doc(step("mgr", applies_to={"type": ["sme-engineer"]}, role="manager"))
    events = [reg(ALICE, "sme-engineer"), reg(PAUL, "partner")]
    assert ids(next_steps(wf, events, subjects(events), TODAY)) == [("tm:step/mgr", ALICE)]


def test_done_step_drops():
    wf = doc(step("a"))
    events = [reg(ALICE, "professional"), reg(BOB, "professional"), done("tm:step/a", ALICE)]
    assert ids(next_steps(wf, events, subjects(events), TODAY)) == [("tm:step/a", BOB)]


def test_done_when_match_must_equal_payload():
    wf = doc(
        step("chk", type="verify", page=None, done_when={"kind": "check", "match": {"step": "tm:step/chk", "result": "ok"}})
    )
    wf["workflows"][0]["steps"][0].pop("page")
    failed = ev("check", ALICE, {"step": "tm:step/chk", "result": "not_found"})
    events = [reg(ALICE, "professional"), failed]
    assert ids(next_steps(wf, events, subjects(events), TODAY)) == [("tm:step/chk", ALICE)]
    events.append(ev("check", ALICE, {"step": "tm:step/chk", "result": "ok"}))
    assert next_steps(wf, events, subjects(events), TODAY) == []


def test_empty_match_completes_on_kind_alone():
    wf = doc(step("sent", done_when={"kind": "notice", "match": {}}))
    events = [reg(ALICE, "professional"), ev("notice", ALICE, {"given_on": "2026-10-02"})]
    assert next_steps(wf, events, subjects(events), TODAY) == []


def test_programme_step_runs_once():
    wf = doc(step("p", subject="programme"))
    events = [reg(ALICE, "professional"), reg(BOB, "professional")]
    assert ids(next_steps(wf, events, subjects(events), TODAY)) == [("tm:step/p", PROGRAMME)]
    events.append(done("tm:step/p", PROGRAMME))
    assert next_steps(wf, events, subjects(events), TODAY) == []


def test_programme_need_blocks_instructor_steps():
    wf = doc(step("import", subject="programme"), step("onb", needs=["tm:step/import"]))
    events = [reg(ALICE, "professional")]
    got = ids(next_steps(wf, events, subjects(events), TODAY))
    assert got == [("tm:step/import", PROGRAMME)]  # no instructor step until the import is done
    events.append(done("tm:step/import", PROGRAMME))
    assert ids(next_steps(wf, events, subjects(events), TODAY)) == [("tm:step/onb", ALICE)]


def test_vacuous_need_for_other_type():
    # A professional reaches baseline without any commitment: the commitment steps do not apply.
    wf = doc(
        step("mgr", applies_to={"type": ["sme-engineer"]}),
        step("plead", applies_to={"type": ["partner"]}),
        step("base", needs=["tm:step/mgr", "tm:step/plead"]),
    )
    events = [reg(ALICE, "professional")]
    assert ids(next_steps(wf, events, subjects(events), TODAY)) == [("tm:step/base", ALICE)]


def test_partner_needs_partner_lead_commitment():
    wf = doc(
        step("mgr", applies_to={"type": ["sme-engineer"]}),
        step("plead", applies_to={"type": ["partner"]}),
        step("base", needs=["tm:step/mgr", "tm:step/plead"]),
    )
    events = [reg(PAUL, "partner"), reg(ALICE, "sme-engineer")]
    s = subjects(events)
    got = ids(next_steps(wf, events, s, TODAY))
    assert ("tm:step/base", PAUL) not in got and ("tm:step/base", ALICE) not in got
    assert ("tm:step/plead", PAUL) in got and ("tm:step/mgr", ALICE) in got
    events.append(done("tm:step/plead", PAUL))
    got = ids(next_steps(wf, events, s, TODAY))
    assert ("tm:step/base", PAUL) in got  # the manager commitment is vacuous for a partner
    assert ("tm:step/base", ALICE) not in got  # Alice still owes the manager commitment


# --- due dates ------------------------------------------------------------------------------


def due_of(dues, sid, subject):
    return next(d for d in dues if d.step == sid and d.subject == subject)


def test_overdue_edge():
    wf = doc(step("a", due={"days": 5, "basis": "operational default"}))
    events = [reg(ALICE, "professional", "2026-10-19")]  # earliest event 19 Oct + 5 = 24 Oct
    d = due_of(next_steps(wf, events, subjects(events), TODAY), "tm:step/a", ALICE)
    assert d.due == date(2026, 10, 24) and d.overdue is False  # due today is not overdue
    d = due_of(next_steps(wf, events, subjects(events), date(2026, 10, 25)), "tm:step/a", ALICE)
    assert d.overdue is True  # due yesterday is
    events = [reg(ALICE, "professional", "2026-10-18")]
    d = due_of(next_steps(wf, events, subjects(events), TODAY), "tm:step/a", ALICE)
    assert d.due == date(2026, 10, 23) and d.overdue is True


def test_due_from_latest_need_completion():
    wf = doc(
        step("a"),
        step("b"),
        step("c", needs=["tm:step/a", "tm:step/b"], due={"days": 10, "basis": "operational default"}),
    )
    events = [
        reg(ALICE, "professional", "2026-09-01"),
        done("tm:step/a", ALICE, "2026-10-02"),
        done("tm:step/b", ALICE, "2026-10-05"),
    ]
    d = due_of(next_steps(wf, events, subjects(events), TODAY), "tm:step/c", ALICE)
    assert d.due == date(2026, 10, 15)


def test_due_with_no_events_starts_today():
    wf = doc(step("p", subject="programme", due={"days": 5, "basis": "operational default"}))
    (d,) = next_steps(wf, [], subjects([]), TODAY)
    assert d.due == date(2026, 10, 29) and d.overdue is False


def test_due_rule_name_resolves_through_the_registry():
    from teachermodel import due as registry

    registry.due_rule("workflow_test_rule")(lambda step, uri, info, events, today: date(2030, 1, 1))
    try:
        wf = doc(step("a", due="workflow_test_rule"))
        events = [reg(ALICE, "professional")]
        (d,) = next_steps(wf, events, subjects(events), date(2030, 1, 2))
        assert d.due == date(2030, 1, 1) and d.overdue is True
    finally:
        registry._RULES.pop("workflow_test_rule", None)


def test_no_due_is_none_and_sorts_last():
    wf = doc(
        step("nodue"),
        step("dued", due={"days": 90, "basis": "operational default"}),
    )
    events = [reg(ALICE, "professional")]
    got = next_steps(wf, events, subjects(events), TODAY)
    assert [d.step for d in got] == ["tm:step/dued", "tm:step/nodue"]


def test_sort_ties_by_step_then_subject():
    wf = doc(step("b"), step("a"))
    events = [reg(BOB, "professional"), reg(ALICE, "professional")]
    got = ids(next_steps(wf, events, subjects(events), TODAY))
    assert got == [
        ("tm:step/a", ALICE),
        ("tm:step/a", BOB),
        ("tm:step/b", ALICE),
        ("tm:step/b", BOB),
    ]


def test_due_carries_step_fields():
    wf = doc(step("a", role="manager", page="approve"))
    events = [reg(ALICE, "professional")]
    (d,) = next_steps(wf, events, subjects(events), TODAY)
    assert isinstance(d, Due)
    assert (d.workflow, d.role, d.page, d.type) == ("tm:workflow/t", "manager", "approve", "human")


# --- real definitions -----------------------------------------------------------------------


def real_workflows():
    return load_standards()["workflows"]


def test_real_workflows_initial_queue():
    wf = real_workflows()
    got = next_steps(wf, [], subjects([]), TODAY)
    assert {d.step for d in got} == {"tm:step/it-request", "tm:step/ropa", "tm:step/base-profile-verified"}
    assert [d.step for d in got][0] == "tm:step/it-request"  # due in 5 days, ropa in 10, verification in 21
    assert all(d.subject == PROGRAMME for d in got)  # no instructor steps


def test_real_workflows_instructors_wait_for_setup():
    wf = real_workflows()
    events = [reg(ALICE, "professional")]
    got = next_steps(wf, events, subjects(events), TODAY)
    assert all(d.subject == PROGRAMME for d in got)


def test_real_workflows_professional_reaches_baseline_without_commitment():
    wf = real_workflows()
    setup = [
        "it-request", "it-done", "library-exists", "ropa", "dpia-screening", "retention-periods",
        "notice-text", "notice-text-approved", "roster-import",
    ]
    kinds = {"it-done": "signoff", "dpia-screening": "signoff", "retention-periods": "signoff",
             "notice-text-approved": "signoff", "library-exists": "check"}
    events = [reg_in(ALICE, "IE"), reg_in(PAUL, "IE", "partner")]  # the base jurisdiction: the base notice
    for sid in setup:
        k = kinds.get(sid, "step")
        payload = {"step": f"tm:step/{sid}"} | ({"result": "ok"} if k == "check" else {})
        if k == "signoff":
            payload["decision"] = "approve"
        events.append(ev(k, PROGRAMME, payload))
    for who in (ALICE, PAUL):
        events.append(ev("step", who, {"step": "tm:step/notice-drafts"}))
        events.append(ev("notice", who, {"step": "tm:step/notice-sent", "notice_variant": "2026-11",
                                         "given_on": "2026-10-10"}))
    subj = lambda: subjects(events, notice_version="2026-11")  # noqa: E731
    got = ids(next_steps(wf, events, subj(), TODAY))
    assert ("tm:step/baseline-self-assessment", ALICE) in got
    assert ("tm:step/baseline-self-assessment", PAUL) not in got  # partner awaits partner lead
    assert ("tm:step/commitment-partner-lead", PAUL) in got
    assert ("tm:step/commitment-manager", PAUL) not in got
    assert ("tm:step/commitment-manager", ALICE) not in got
    events.append(ev("signoff", PAUL, {"step": "tm:step/commitment-partner-lead", "decision": "approve"}))
    got = ids(next_steps(wf, events, subj(), TODAY))
    assert ("tm:step/baseline-self-assessment", PAUL) in got


def test_real_sme_engineer_needs_manager_commitment():
    wf = real_workflows()
    events = [reg_in(ALICE, "IE", "sme-engineer")]
    for sid, k in [("roster-import", "step"), ("notice-drafts", "step")]:
        events.append(ev(k, PROGRAMME if sid == "roster-import" else ALICE, {"step": f"tm:step/{sid}"}))
    events.append(ev("notice", ALICE, {"step": "tm:step/notice-sent", "notice_variant": "2026-11",
                                       "given_on": "2026-10-10"}))
    got = ids(next_steps(wf, events, subjects(events, notice_version="2026-11"), TODAY))
    assert ("tm:step/commitment-manager", ALICE) in got
    assert ("tm:step/baseline-self-assessment", ALICE) not in got


def test_level_filter_skips_cleared_instructor():
    from teachermodel.standards import load_standards

    wf = load_standards()["workflows"]
    def ev(kind, subject, payload, n):
        return make_event(kind, subject, "tm:system/teachermodel", payload, id=f"evtlvl{n:04d}", at="2026-10-01T09:00:00+00:00")
    log = [
        ev("registration", "tm:instructor/cl1", {"type": "professional", "level": "cleared"}, 1),
        ev("registration", "tm:instructor/sh1", {"type": "professional", "level": "shadow"}, 2),
    ]
    steps = {s.step for s in next_steps(wf, log, subjects(log), date(2026, 10, 2)) if s.subject == "tm:instructor/cl1"}
    assert "tm:step/lead-observed-level" not in steps
    assert subjects(log)["tm:instructor/sh1"]["level"] == "shadow"


# --- review fixes ---------------------------------------------------------------------------


def test_only_approve_or_record_signoffs_complete_a_step():
    wf = doc(step("a"))
    base = [reg(ALICE, "professional")]
    for decision in ("reject", "changes", None):
        payload = {"step": "tm:step/a"} | ({"decision": decision} if decision else {})
        log = base + [ev("signoff", ALICE, payload)]
        assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/a", ALICE)], decision
    for decision in ("approve", "record"):
        log = base + [ev("signoff", ALICE, {"step": "tm:step/a", "decision": decision})]
        assert next_steps(wf, log, subjects(log), TODAY) == [], decision


def test_non_approving_signoff_does_not_unblock_next_step():
    wf = doc(step("a"), step("b", needs=["tm:step/a"]))
    log = [reg(ALICE, "professional"), ev("signoff", ALICE, {"step": "tm:step/a", "decision": "reject"})]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/a", ALICE)]


def test_non_signoff_kinds_ignore_decision_rule():
    wf = doc(step("sent", done_when={"kind": "notice", "match": {}}))
    log = [reg(ALICE, "professional"), ev("notice", ALICE, {"given_on": "2026-10-02"})]
    assert next_steps(wf, log, subjects(log), TODAY) == []


def test_unknown_type_need_is_unmet_not_vacuous():
    wf = doc(
        step("mgr", applies_to={"type": ["sme-engineer"]}),
        step("base", needs=["tm:step/mgr"]),
    )
    log = [reg(ALICE, "martian"), reg(BOB, "professional")]
    got = ids(next_steps(wf, log, subjects(log), TODAY))
    assert ("tm:step/base", ALICE) not in got  # unknown type: the need is unmet
    assert ("tm:step/base", BOB) in got  # known type the need does not cover: vacuous


# --- bind: input (decision 0009; privacy-jurisdictions design section 2) ---------------------


def bound(sid, **kw):
    return step(sid, done_when={"kind": "signoff", "match": {"step": f"tm:step/{sid}"}, "bind": "input"}, **kw)


def approval(sid, subject, sha, decision="approve", day="2026-10-01"):
    return ev("signoff", subject, {"step": f"tm:step/{sid}", "decision": decision, "input_sha256": sha}, day)


def reader(current):
    """A current_input reader over a mutable dict {(step, subject): hash}; unknown pairs give None."""
    return lambda step_id, subject: current.get((step_id, subject))


def test_bind_input_reopens_on_change():
    wf = doc(bound("p", subject="programme"), step("after", subject="programme", needs=["tm:step/p"]))
    log = [approval("p", PROGRAMME, "a" * 64)]
    cur = {("tm:step/p", PROGRAMME): "a" * 64}
    got = ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur)))
    assert got == [("tm:step/after", PROGRAMME)]  # approved on the current input: done, the next step opens
    cur[("tm:step/p", PROGRAMME)] = "b" * 64  # the input changed after approval
    got = ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur)))
    assert got == [("tm:step/p", PROGRAMME)]  # reopened, and what needs it closes again
    log.append(approval("p", PROGRAMME, "b" * 64))
    got = ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur)))
    assert got == [("tm:step/after", PROGRAMME)]


def test_bind_input_newest_approving_signoff_decides():
    wf = doc(bound("p", subject="programme"))
    cur = {("tm:step/p", PROGRAMME): "b" * 64}
    old_then_new = [approval("p", PROGRAMME, "a" * 64), approval("p", PROGRAMME, "b" * 64)]
    assert next_steps(wf, old_then_new, subjects(old_then_new), TODAY, current_input=reader(cur)) == []
    new_then_old = [approval("p", PROGRAMME, "b" * 64), approval("p", PROGRAMME, "a" * 64)]
    got = ids(next_steps(wf, new_then_old, subjects(new_then_old), TODAY, current_input=reader(cur)))
    assert got == [("tm:step/p", PROGRAMME)]  # an older approval of the current input does not outrank a newer one
    rejected_last = [approval("p", PROGRAMME, "b" * 64), approval("p", PROGRAMME, "a" * 64, decision="reject")]
    assert next_steps(wf, rejected_last, subjects(rejected_last), TODAY, current_input=reader(cur)) == []


def test_bind_input_without_reader_never_done():
    wf = doc(bound("p", subject="programme"))
    log = [approval("p", PROGRAMME, "a" * 64)]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/p", PROGRAMME)]  # fail closed
    unknown = reader({})  # a reader that cannot say what the input is
    assert ids(next_steps(wf, log, subjects(log), TODAY, current_input=unknown)) == [("tm:step/p", PROGRAMME)]


def test_bind_input_signoff_without_input_hash_never_completes():
    wf = doc(bound("p", subject="programme"))
    log = [ev("signoff", PROGRAMME, {"step": "tm:step/p", "decision": "approve"})]
    cur = {("tm:step/p", PROGRAMME): "a" * 64}
    assert ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur))) == [("tm:step/p", PROGRAMME)]


def test_unbound_step_stays_done_when_input_changes():
    wf = doc(step("p", subject="programme"))
    log = [approval("p", PROGRAMME, "a" * 64)]
    cur = {("tm:step/p", PROGRAMME): "b" * 64}
    assert next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur)) == []
    assert next_steps(wf, log, subjects(log), TODAY) == []


# --- jurisdiction subjects and applies_to.jurisdiction ----------------------------------------


def reg_in(uri, jurisdiction, type_="professional", day="2026-10-01"):
    return ev("registration", uri, {"type": type_, "level": "shadow", "jurisdiction": jurisdiction}, day)


def test_jurisdiction_subject_only_for_overlay_codes():
    log = [reg_in(ALICE, "IE"), reg_in(BOB, "US-CA"), reg_in(PAUL, "DE", "partner")]
    s = subjects(log)
    assert s["tm:jurisdiction/us-ca"] == {"kind": "jurisdiction", "code": "US-CA"}
    assert s["tm:jurisdiction/de"] == {"kind": "jurisdiction", "code": "DE"}
    assert "tm:jurisdiction/ie" not in s  # the base code needs no overlay
    s = subjects(log, base_codes={"IE", "DE"})
    assert set(s) - {PROGRAMME, ALICE, BOB, PAUL} == {"tm:jurisdiction/us-ca"}
    assert subjects([reg_in(ALICE, "US-CA"), reg_in(BOB, "US-CA")]).keys() >= {"tm:jurisdiction/us-ca"}


def test_jurisdiction_subject_follows_the_latest_registration():
    moved = [reg_in(ALICE, "US-CA", day="2026-10-01"), reg_in(ALICE, "IE", day="2026-10-02")]
    assert "tm:jurisdiction/us-ca" not in subjects(moved)  # nobody works there any more
    assert "tm:jurisdiction/us-ca" in subjects([*moved, reg_in(BOB, "US-CA")])
    assert subjects([ev("registration", ALICE, {"type": "professional", "level": "shadow"})]).keys() == {PROGRAMME, ALICE}


def test_jurisdiction_steps_open_once_per_overlay_subject():
    wf = doc(step("prof", subject="jurisdiction", role="dpo"))
    log = [reg_in(ALICE, "IE"), reg_in(BOB, "US-CA"), reg_in(PAUL, "US-CA", "partner")]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/prof", "tm:jurisdiction/us-ca")]
    log.append(done("tm:step/prof", "tm:jurisdiction/us-ca"))
    assert next_steps(wf, log, subjects(log), TODAY) == []


def test_bind_input_on_a_jurisdiction_subject():
    wf = doc(bound("prof", subject="jurisdiction", role="legal"))
    uri = "tm:jurisdiction/us-ca"
    log = [reg_in(BOB, "US-CA"), approval("prof", uri, "a" * 64)]
    cur = {("tm:step/prof", uri): "a" * 64}
    assert next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur)) == []
    cur[("tm:step/prof", uri)] = "b" * 64
    assert ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur))) == [("tm:step/prof", uri)]


def test_applies_to_jurisdiction():
    wf = doc(step("ca", applies_to={"jurisdiction": ["US-CA"]}))
    log = [reg_in(ALICE, "IE"), reg_in(BOB, "US-CA"), reg_in(PAUL, "DE", "partner"),
           ev("registration", "tm:instructor/nowhere", {"type": "professional", "level": "shadow"})]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/ca", BOB)]
    wf = doc(step("two", applies_to={"jurisdiction": ["US-CA", "DE"]}))
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/two", BOB), ("tm:step/two", PAUL)]


def test_applies_to_jurisdiction_combines_with_type():
    wf = doc(step("ca", applies_to={"jurisdiction": ["US-CA"], "type": ["partner"]}))
    log = [reg_in(BOB, "US-CA"), reg_in(PAUL, "US-CA", "partner"), reg_in(ALICE, "IE", "partner")]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/ca", PAUL)]


def test_need_with_jurisdiction_filter_is_vacuous_elsewhere_and_unmet_when_unknown():
    wf = doc(step("ca", applies_to={"jurisdiction": ["US-CA"]}), step("base", needs=["tm:step/ca"]))
    log = [reg_in(ALICE, "IE"), reg_in(BOB, "US-CA"),
           ev("registration", PAUL, {"type": "professional", "level": "shadow"})]  # no jurisdiction recorded
    got = ids(next_steps(wf, log, subjects(log), TODAY))
    assert ("tm:step/base", ALICE) in got  # the Californian step does not apply to an Irish instructor
    assert ("tm:step/base", BOB) not in got  # it does apply, and is not done
    assert ("tm:step/base", PAUL) not in got  # unknown jurisdiction: the need is unmet, not vacuous


# --- needs_met: ready to run again, whether or not the step itself is done -------------------------------


def test_needs_met_ignores_the_steps_own_completion():
    from teachermodel.workflow import needs_met

    wf = doc(step("a", subject="programme"), step("b", subject="programme", needs=["tm:step/a"], type="auto"))
    wf["workflows"][0]["steps"][1].pop("page")
    log = []
    s = subjects(log)
    assert needs_met(wf, log, s, "tm:step/b", PROGRAMME) is False
    log.append(done("tm:step/a", PROGRAMME))
    assert needs_met(wf, log, s, "tm:step/b", PROGRAMME) is True
    log.append(done("tm:step/b", PROGRAMME, kind="step"))  # done now, but its needs are still in force
    assert needs_met(wf, log, s, "tm:step/b", PROGRAMME) is True
    assert needs_met(wf, log, s, "tm:step/ghost", PROGRAMME) is False
    assert needs_met(wf, log, s, "tm:step/b", "tm:instructor/nobody") is False


def test_needs_met_follows_a_bound_need():
    from teachermodel.workflow import needs_met

    bound = step("a", subject="programme", done_when={"kind": "signoff", "match": {"step": "tm:step/a"}, "bind": "input"})
    wf = doc(bound, step("b", subject="programme", needs=["tm:step/a"], type="auto"))
    wf["workflows"][0]["steps"][1].pop("page")
    approved = ev("signoff", PROGRAMME, {"step": "tm:step/a", "decision": "approve", "input_sha256": "a" * 64})
    s = subjects([])
    assert needs_met(wf, [approved], s, "tm:step/b", PROGRAMME, lambda step_id, uri: "a" * 64) is True
    assert needs_met(wf, [approved], s, "tm:step/b", PROGRAMME, lambda step_id, uri: "b" * 64) is False  # edited since
    assert needs_met(wf, [approved], s, "tm:step/b", PROGRAMME) is False  # no reader: fail closed


# --- needs on a jurisdiction-subject step (privacy overlay, J4) --------------------------------------------


def jstep(sid, **kw):
    kw.setdefault("role", "legal")
    return step(sid, subject="jurisdiction", **kw)


def test_instructor_need_on_a_jurisdiction_step_maps_to_the_instructors_jurisdiction():
    wf = doc(jstep("prof"), step("w1", needs=["tm:step/prof"]))
    log = [reg_in(ALICE, "IE"), reg_in(BOB, "US-CA"), reg_in(PAUL, "DE", "partner")]
    got = ids(next_steps(wf, log, subjects(log), TODAY))
    assert ("tm:step/w1", BOB) not in got and ("tm:step/w1", PAUL) not in got  # their overlay is not done
    assert ("tm:step/w1", ALICE) in got  # IE is a base code: the need is vacuous
    log.append(done("tm:step/prof", "tm:jurisdiction/de"))  # another jurisdiction's overlay does not count
    got = ids(next_steps(wf, log, subjects(log), TODAY))
    assert ("tm:step/w1", BOB) not in got and ("tm:step/w1", PAUL) in got
    log.append(done("tm:step/prof", "tm:jurisdiction/us-ca"))
    assert ("tm:step/w1", BOB) in ids(next_steps(wf, log, subjects(log), TODAY))


def test_instructor_with_no_recorded_jurisdiction_is_unmet_not_vacuous():
    wf = doc(jstep("prof"), step("w1", needs=["tm:step/prof"]))
    log = [ev("registration", ALICE, {"type": "professional", "level": "shadow"}), reg_in(BOB, "IE")]
    got = ids(next_steps(wf, log, subjects(log), TODAY))
    assert ("tm:step/w1", ALICE) not in got and ("tm:step/w1", BOB) in got


def test_jurisdiction_step_need_between_jurisdiction_steps_uses_the_same_subject():
    wf = doc(jstep("a"), jstep("b", needs=["tm:step/a"]))
    log = [reg_in(BOB, "US-CA"), reg_in(PAUL, "DE", "partner"), done("tm:step/a", "tm:jurisdiction/us-ca")]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [
        ("tm:step/a", "tm:jurisdiction/de"), ("tm:step/b", "tm:jurisdiction/us-ca")]


def test_programme_step_cannot_depend_on_a_jurisdiction_step():
    wf = doc(jstep("prof"), step("p", subject="programme", needs=["tm:step/prof"]))
    log = [reg_in(BOB, "US-CA"), done("tm:step/prof", "tm:jurisdiction/us-ca")]
    assert ("tm:step/p", PROGRAMME) not in ids(next_steps(wf, log, subjects(log), TODAY))


def test_a_base_code_given_in_lower_case_is_still_base_for_the_need():
    wf = doc(jstep("prof"), step("w1", needs=["tm:step/prof"]))
    log = [reg_in(ALICE, "IE")]
    assert ("tm:step/w1", ALICE) in ids(next_steps(wf, log, subjects(log, ["ie"]), TODAY))


# --- notice_variant on the instructor subject and the ${subject.notice_variant} match -------------------------


def test_subjects_carry_the_notice_variant_when_given_the_notice_version():
    log = [reg_in(ALICE, "IE"), reg_in(BOB, "US-CA"), reg_in(PAUL, "DE", "partner"),
           ev("registration", "tm:instructor/nowhere", {"type": "professional", "level": "shadow"})]
    s = subjects(log, notice_version="2026-11")
    assert s[ALICE]["notice_variant"] == "2026-11"
    assert s[BOB]["notice_variant"] == "2026-11-us-ca"
    assert s[PAUL]["notice_variant"] == "2026-11-de"
    assert "notice_variant" not in s["tm:instructor/nowhere"]  # no jurisdiction recorded: no variant to expect
    assert "notice_variant" not in subjects(log)[ALICE]  # without a version there is nothing to derive
    assert subjects(log, ["IE", "de"], "2026-11")[PAUL]["notice_variant"] == "2026-11"


def sent(sid="sent"):
    return step(sid, type="verify", done_when={
        "kind": "notice", "match": {"step": f"tm:step/{sid}", "notice_variant": "${subject.notice_variant}"}})


def notice_for(uri, variant, sid="sent"):
    return ev("notice", uri, {"step": f"tm:step/{sid}", "notice_variant": variant, "given_on": "2026-10-10"})


def test_done_when_match_resolves_the_subjects_notice_variant():
    wf = doc(sent())
    log = [reg_in(ALICE, "IE"), reg_in(BOB, "US-CA"), notice_for(ALICE, "2026-11"), notice_for(BOB, "2026-11")]
    got = ids(next_steps(wf, log, subjects(log, notice_version="2026-11"), TODAY))
    assert got == [("tm:step/sent", BOB)]  # BOB got the base notice, not the California variant
    log.append(notice_for(BOB, "2026-11-us-ca"))
    assert next_steps(wf, log, subjects(log, notice_version="2026-11"), TODAY) == []
    log.append(reg_in(ALICE, "US-CA", day="2026-10-05"))  # moved: the base notice no longer covers them
    assert ids(next_steps(wf, log, subjects(log, notice_version="2026-11"), TODAY)) == [("tm:step/sent", ALICE)]


def test_unresolvable_template_never_matches():
    wf = doc(sent())
    log = [reg_in(ALICE, "IE"), notice_for(ALICE, "2026-11")]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/sent", ALICE)]  # no version: fail closed
    nowhere = ev("registration", BOB, {"type": "professional", "level": "shadow"})
    log2 = [nowhere, notice_for(BOB, None)]
    assert ids(next_steps(wf, log2, subjects(log2, notice_version="2026-11"), TODAY)) == [("tm:step/sent", BOB)]


def test_only_the_template_form_is_resolved():
    wf = doc(step("a", done_when={"kind": "notice", "match": {"step": "tm:step/a", "note": "${subject.type}"}}))
    log = [reg_in(ALICE, "IE"), ev("notice", ALICE, {"step": "tm:step/a", "note": "professional"})]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/a", ALICE)]  # only notice_variant is a template


# --- skippable: a system step event completes a bound step that does not apply ----------------------------


def skippable(sid, **kw):
    return step(sid, done_when={"kind": "signoff", "match": {"step": f"tm:step/{sid}"}, "bind": "input", "skippable": True},
                **kw)


def skip(sid, subject, sha, actor=SYSTEM_ACTOR, **extra):
    """A skip event; only one the system wrote counts."""
    return make_event("step", subject, actor, {"step": f"tm:step/{sid}", "skipped": True, "input_sha256": sha, **extra},
                      at="2026-10-01T09:00:00+00:00")


def test_skippable_step_is_done_by_a_skip_event_while_its_inputs_are_unchanged():
    wf = doc(skippable("d", subject="programme"), step("after", subject="programme", needs=["tm:step/d"]))
    cur = {("tm:step/d", PROGRAMME): "a" * 64}
    log = [skip("d", PROGRAMME, "a" * 64)]
    assert ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur))) == [("tm:step/after", PROGRAMME)]
    cur[("tm:step/d", PROGRAMME)] = "b" * 64  # what the step would show changed: the skip no longer holds
    assert ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur))) == [("tm:step/d", PROGRAMME)]


def test_a_skip_event_from_another_actor_does_not_close_the_step():
    wf = doc(skippable("d", subject="programme"))
    cur = {("tm:step/d", PROGRAMME): "a" * 64}
    log = [skip("d", PROGRAMME, "a" * 64, actor="tm:person/owner")]
    assert ids(next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur))) == [("tm:step/d", PROGRAMME)]


def test_a_skip_event_needs_the_flag_the_hash_a_reader_and_the_skipped_marker():
    cur = {("tm:step/d", PROGRAMME): "a" * 64}
    plain = doc(bound("d", subject="programme"))
    log = [skip("d", PROGRAMME, "a" * 64)]
    assert ids(next_steps(plain, log, subjects(log), TODAY, current_input=reader(cur))) == [("tm:step/d", PROGRAMME)]
    wf = doc(skippable("d", subject="programme"))
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/d", PROGRAMME)]  # no reader
    plain_step_event = [ev("step", PROGRAMME, {"step": "tm:step/d", "input_sha256": "a" * 64})]  # not marked skipped
    assert ids(next_steps(wf, plain_step_event, subjects([]), TODAY, current_input=reader(cur))) == [
        ("tm:step/d", PROGRAMME)]
    other = [skip("x", PROGRAMME, "a" * 64)]
    assert ids(next_steps(wf, other, subjects([]), TODAY, current_input=reader(cur))) == [("tm:step/d", PROGRAMME)]
    elsewhere = [skip("d", "tm:jurisdiction/us-ca", "a" * 64)]
    assert ids(next_steps(wf, elsewhere, subjects([]), TODAY, current_input=reader(cur))) == [("tm:step/d", PROGRAMME)]


def test_skippable_step_still_completes_by_signoff():
    wf = doc(skippable("d", subject="programme"))
    cur = {("tm:step/d", PROGRAMME): "a" * 64}
    log = [approval("d", PROGRAMME, "a" * 64)]
    assert next_steps(wf, log, subjects(log), TODAY, current_input=reader(cur)) == []
