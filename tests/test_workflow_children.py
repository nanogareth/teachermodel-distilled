"""Child subjects (event@3 `subject`, decision 0011): candidate, assignment, exercise.

The engine lists them from `subject` events and resolves a need asked by a child against its parent:
a need on an instructor-subject step -> `attrs.instructor`, a need on a candidate-subject step from an
assignment -> `attrs.candidate`, a need on a programme-subject step -> the programme. An unknown parent
means the need is unmet. `applies_to` reads the child's attrs, with type/level/jurisdiction taken from the
instructor's registration. All people here are fictional.
"""

from datetime import date

import pytest

from teachermodel.events import make_event
from teachermodel.workflow import PROGRAMME, needs_met, next_steps, unmet_needs
from teachermodel.workflow import subjects as engine_subjects

TODAY = date(2026, 10, 24)
ACTOR = "tm:person/owner"
ALICE = "tm:instructor/alice"
PAUL = "tm:instructor/paul"
GHOST = "tm:instructor/ghost"  # never registered
UNIT = "sl:unit/example-agent-loop@1"
CAND_A = "tm:candidate/alice--example-agent-loop-1--remote"
CAND_P = "tm:candidate/paul--example-agent-loop-1--remote"
ASSIGN_A = "tm:assignment/0123456789abcdef"
EXERCISE = "tm:exercise/fedcba9876543210"


def subjects(events):
    return engine_subjects(events, ("IE",))


def ev(kind, subject, payload, day="2026-10-01"):
    return make_event(kind, subject, ACTOR, payload, at=f"{day}T09:00:00+00:00")


def reg(uri, type_, level="lead-observed", jurisdiction="IE"):
    return ev("registration", uri, {"type": type_, "level": level, "jurisdiction": jurisdiction})


def child(uri, kind, attrs, by="tm:step/test-open"):
    return ev("subject", uri, {"subject_kind": kind, "attrs": attrs, "opened_by": by}, "2026-10-02")


def cand(uri, instructor, mode="remote"):
    return child(uri, "candidate", {"instructor": instructor, "unit": UNIT, "mode": mode})


def assignment(uri, candidate, instructor):
    return child(uri, "assignment", {"candidate": candidate, "instructor": instructor, "unit": UNIT, "mode": "remote",
                                     "observer": "tm:instructor/obs", "length": "full", "lead": True,
                                     "delivery_ref": "d-1"})


def done(step, subject, day="2026-10-03"):
    return ev("signoff", subject, {"step": step, "decision": "approve"}, day)


def step(sid, subject, **kw):
    base = {
        "id": f"tm:step/{sid}", "name": sid, "type": "human", "role": "coordinator", "subject": subject, "needs": [],
        "done_when": {"kind": "signoff", "match": {"step": f"tm:step/{sid}"}}, "page": "approve", "basis": "test",
    }
    base.update(kw)
    return base


def doc(*steps):
    return {"workflows": [{"id": "tm:workflow/t", "name": "t", "basis": "test", "steps": list(steps)}]}


def ids(dues):
    return [(d.step, d.subject) for d in dues]


# --- subjects ---------------------------------------------------------------------------------


def test_child_subjects_are_listed_with_kind_and_attrs():
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE), assignment(ASSIGN_A, CAND_A, ALICE),
           child(EXERCISE, "exercise", {"unit": UNIT, "rubric_version": "0.2.0", "recording_ref": "r-1",
                                        "observers": ["tm:instructor/obs"], "reference_key": "k-1"})]
    s = subjects(log)
    assert s[CAND_A] == {"kind": "candidate", "instructor": ALICE, "unit": UNIT, "mode": "remote"}
    assert s[ASSIGN_A]["kind"] == "assignment" and s[ASSIGN_A]["candidate"] == CAND_A
    assert s[EXERCISE]["kind"] == "exercise" and s[EXERCISE]["observers"] == ["tm:instructor/obs"]
    assert s[ALICE]["kind"] == "instructor" and s[PROGRAMME] == {"kind": "programme"}


def test_a_subject_event_does_not_register_an_instructor_or_change_one():
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE)]
    assert subjects(log)[ALICE] == subjects(log[:1])[ALICE]


@pytest.mark.parametrize("payload", [
    {"subject_kind": "instructor", "attrs": {"type": "partner"}, "opened_by": "tm:step/x"},  # not a child kind
    {"subject_kind": "programme", "attrs": {}, "opened_by": "tm:step/x"},
    {"subject_kind": "candidate", "opened_by": "tm:step/x"},  # no attrs
    {"subject_kind": "candidate", "attrs": ["x"], "opened_by": "tm:step/x"},  # attrs not an object
    {"attrs": {}, "opened_by": "tm:step/x"},  # no kind
])
def test_malformed_or_non_child_subject_events_are_ignored(payload):
    log = [ev("subject", CAND_A, payload)]
    assert CAND_A not in subjects(log)


def test_the_first_event_for_a_child_uri_wins():
    first = cand(CAND_A, ALICE, "remote")
    second = cand(CAND_A, ALICE, "hybrid")
    assert subjects([reg(ALICE, "sme-engineer"), first, second])[CAND_A]["mode"] == "remote"


def test_child_attrs_cannot_override_the_kind():
    log = [child(CAND_A, "candidate", {"kind": "instructor", "instructor": ALICE})]
    assert subjects(log)[CAND_A]["kind"] == "candidate"


# --- need resolution ----------------------------------------------------------------------------


def test_a_child_need_on_an_instructor_step_resolves_to_attrs_instructor():
    wf = doc(step("train", "instructor"), step("observe", "candidate", needs=["tm:step/train"]))
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE)]
    s = subjects(log)
    assert ids(next_steps(wf, log, s, TODAY)) == [("tm:step/train", ALICE)]  # the candidate step waits
    assert not needs_met(wf, log, s, "tm:step/observe", CAND_A)
    assert unmet_needs(wf, log, s, "tm:step/observe", CAND_A) == ["tm:step/train"]
    log.append(done("tm:step/train", ALICE))
    s = subjects(log)
    assert ids(next_steps(wf, log, s, TODAY)) == [("tm:step/observe", CAND_A)]
    assert needs_met(wf, log, s, "tm:step/observe", CAND_A)
    assert unmet_needs(wf, log, s, "tm:step/observe", CAND_A) == []


def test_a_need_done_for_another_instructor_does_not_count_for_the_candidate():
    wf = doc(step("train", "instructor"), step("observe", "candidate", needs=["tm:step/train"]))
    log = [reg(ALICE, "sme-engineer"), reg(PAUL, "partner"), cand(CAND_A, ALICE), done("tm:step/train", PAUL)]
    got = ids(next_steps(wf, log, subjects(log), TODAY))
    assert ("tm:step/observe", CAND_A) not in got and ("tm:step/train", ALICE) in got


def test_an_assignment_need_on_a_candidate_step_resolves_to_attrs_candidate():
    wf = doc(step("clear", "candidate"), step("score", "assignment", needs=["tm:step/clear"]))
    log = [reg(ALICE, "sme-engineer"), reg(PAUL, "partner"), cand(CAND_A, ALICE), cand(CAND_P, PAUL),
           assignment(ASSIGN_A, CAND_A, ALICE)]
    s = subjects(log)
    assert ("tm:step/score", ASSIGN_A) not in ids(next_steps(wf, log, s, TODAY))
    log.append(done("tm:step/clear", CAND_P))  # another candidate's step does not count
    assert ("tm:step/score", ASSIGN_A) not in ids(next_steps(wf, log, subjects(log), TODAY))
    log.append(done("tm:step/clear", CAND_A))
    assert ("tm:step/score", ASSIGN_A) in ids(next_steps(wf, log, subjects(log), TODAY))


def test_an_assignment_need_on_an_instructor_step_resolves_to_attrs_instructor():
    wf = doc(step("train", "instructor"), step("score", "assignment", needs=["tm:step/train"]))
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE), assignment(ASSIGN_A, CAND_A, ALICE)]
    assert ("tm:step/score", ASSIGN_A) not in ids(next_steps(wf, log, subjects(log), TODAY))
    log.append(done("tm:step/train", ALICE))
    assert ("tm:step/score", ASSIGN_A) in ids(next_steps(wf, log, subjects(log), TODAY))


def test_a_child_need_on_a_programme_step_resolves_to_the_programme():
    wf = doc(step("import", "programme"), step("observe", "candidate", needs=["tm:step/import"]))
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE)]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/import", PROGRAMME)]
    log.append(done("tm:step/import", PROGRAMME))
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/observe", CAND_A)]


def test_a_need_on_a_step_of_the_same_child_kind_resolves_to_itself():
    wf = doc(step("a", "candidate"), step("b", "candidate", needs=["tm:step/a"]))
    log = [reg(ALICE, "sme-engineer"), reg(PAUL, "partner"), cand(CAND_A, ALICE), cand(CAND_P, PAUL),
           done("tm:step/a", CAND_A)]
    got = ids(next_steps(wf, log, subjects(log), TODAY))
    assert ("tm:step/b", CAND_A) in got and ("tm:step/b", CAND_P) not in got and ("tm:step/a", CAND_P) in got


def test_an_unknown_parent_leaves_the_need_unmet():
    wf = doc(step("train", "instructor"), step("observe", "candidate", needs=["tm:step/train"]))
    # The instructor was never registered, yet a sign-off for them exists: the candidate must still wait.
    log = [cand(CAND_A, GHOST), done("tm:step/train", GHOST)]
    s = subjects(log)
    assert ids(next_steps(wf, log, s, TODAY)) == []
    assert not needs_met(wf, log, s, "tm:step/observe", CAND_A)
    assert unmet_needs(wf, log, s, "tm:step/observe", CAND_A) == ["tm:step/train"]


def test_an_unknown_candidate_parent_leaves_the_assignment_need_unmet():
    wf = doc(step("clear", "candidate"), step("score", "assignment", needs=["tm:step/clear"]))
    log = [reg(ALICE, "sme-engineer"), assignment(ASSIGN_A, "tm:candidate/never-opened", ALICE),
           done("tm:step/clear", "tm:candidate/never-opened")]
    assert ("tm:step/score", ASSIGN_A) not in ids(next_steps(wf, log, subjects(log), TODAY))


def test_a_child_without_the_parent_attribute_leaves_the_need_unmet():
    wf = doc(step("train", "instructor"), step("observe", "exercise", needs=["tm:step/train"]))
    log = [reg(ALICE, "sme-engineer"), child(EXERCISE, "exercise", {"unit": UNIT}), done("tm:step/train", ALICE)]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == []
    wf = doc(step("clear", "candidate"), step("score", "assignment", needs=["tm:step/clear"]))
    log = [child(ASSIGN_A, "assignment", {"unit": UNIT}), done("tm:step/clear", CAND_A)]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == []


def test_a_non_string_parent_attribute_leaves_the_need_unmet():
    wf = doc(step("train", "instructor"), step("observe", "candidate", needs=["tm:step/train"]))
    log = [reg(ALICE, "sme-engineer"), child(CAND_A, "candidate", {"instructor": [ALICE]}), done("tm:step/train", ALICE)]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == []


# --- applies_to through attrs -----------------------------------------------------------------------------


def test_applies_to_on_a_child_step_reads_the_instructors_registration():
    wf = doc(step("sme-only", "candidate", applies_to={"type": ["sme-engineer"]}),
             step("ca-only", "candidate", applies_to={"jurisdiction": ["US-CA"]}),
             step("lead", "candidate", applies_to={"level": ["lead-observed"]}))
    log = [reg(ALICE, "sme-engineer"), reg(PAUL, "partner", "cleared", "US-CA"), cand(CAND_A, ALICE), cand(CAND_P, PAUL)]
    got = set(ids(next_steps(wf, log, subjects(log), TODAY)))
    assert got == {("tm:step/sme-only", CAND_A), ("tm:step/ca-only", CAND_P), ("tm:step/lead", CAND_A)}


def test_applies_to_on_a_child_whose_instructor_is_unknown_does_not_apply():
    wf = doc(step("sme-only", "candidate", applies_to={"type": ["sme-engineer"]}))
    log = [cand(CAND_A, GHOST)]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == []


def test_a_vacuous_need_for_the_instructors_type_is_skipped_for_the_child():
    wf = doc(step("mgr", "instructor", applies_to={"type": ["sme-engineer"]}),
             step("observe", "candidate", needs=["tm:step/mgr"]))
    log = [reg(PAUL, "partner"), cand(CAND_P, PAUL)]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == [("tm:step/observe", CAND_P)]
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE)]
    assert ("tm:step/observe", CAND_A) not in ids(next_steps(wf, log, subjects(log), TODAY))


def test_a_child_attribute_of_the_same_name_does_not_override_the_registration():
    wf = doc(step("sme-only", "candidate", applies_to={"type": ["sme-engineer"]}))
    log = [reg(PAUL, "partner"), child(CAND_P, "candidate", {"instructor": PAUL, "unit": UNIT, "mode": "remote",
                                                            "type": "sme-engineer"})]
    assert ids(next_steps(wf, log, subjects(log), TODAY)) == []


# --- the workflows schema ---------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["programme", "instructor", "candidate", "assignment", "exercise"])
def test_the_workflows_schema_accepts_child_subject_kinds(kind):
    from teachermodel.standards import validate

    wf = {"schema_version": 1, "id": "tm:standards/t", "status": "draft", "workflows": [{
        "id": "tm:workflow/t", "name": "t", "basis": "test", "event_kinds": ["signoff"],
        "steps": [step("a", kind)]}]}
    assert validate(wf, "workflows.schema.json") == []


def test_the_workflows_schema_still_rejects_an_unknown_subject_kind():
    from teachermodel.standards import validate

    wf = {"schema_version": 1, "id": "tm:standards/t", "status": "draft", "workflows": [{
        "id": "tm:workflow/t", "name": "t", "basis": "test", "event_kinds": ["signoff"],
        "steps": [step("a", "wizard")]}]}
    assert validate(wf, "workflows.schema.json")


# --- when a step opened (integration review finding 1) ----------------------------------------------------


def test_a_child_subject_step_opened_the_day_of_its_subject_event():
    from teachermodel.workflow import opened_on

    wf = doc(step("work", "candidate"))
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE)]  # opened 2026-10-02
    assert opened_on(wf, log, subjects(log), "tm:step/work", CAND_A) == date(2026, 10, 2)
    assert opened_on(wf, log, subjects(log), "tm:step/work", "tm:candidate/ghost--u-1--remote") is None  # no such subject
    assert opened_on(wf, log, subjects(log), "tm:step/nope", CAND_A) is None  # no such step


def test_another_subjects_step_opened_the_day_its_needs_were_met():
    from teachermodel.workflow import opened_on

    wf = doc(step("first", "instructor"), step("second", "instructor", needs=["tm:step/first"]),
             step("third", "instructor", needs=["tm:step/first", "tm:step/second"]))
    log = [reg(ALICE, "sme-engineer"), done("tm:step/first", ALICE, "2026-10-05")]
    s = subjects(log)
    assert opened_on(wf, log, s, "tm:step/second", ALICE) == date(2026, 10, 5)
    assert opened_on(wf, log, s, "tm:step/first", ALICE) is None  # nothing to wait for: no day is known
    assert opened_on(wf, log, s, "tm:step/third", ALICE) is None  # a need is not met: it has not opened
    log += [done("tm:step/second", ALICE, "2026-10-09")]
    assert opened_on(wf, log, s, "tm:step/third", ALICE) == date(2026, 10, 9)  # when the last need was met


# --- the event index ---------------------------------------------------------------------------------------


def test_the_index_answers_by_kind_and_subject_in_log_order():
    from teachermodel.workflow import EventIndex

    a, b, c = done("tm:step/x", ALICE, "2026-10-03"), done("tm:step/y", ALICE, "2026-10-04"), done("tm:step/x", PAUL)
    log = [a, b, c]
    idx = EventIndex(log)
    assert idx.of("signoff", ALICE) == [a, b] and idx.of("signoff", PAUL) == [c] and idx.of("check", ALICE) == []
    assert idx.for_subject(ALICE) == [a, b] and idx.for_subject("tm:instructor/none") == []
    assert idx.ids == {a["id"], b["id"], c["id"]}
    d = done("tm:step/z", ALICE)
    idx.add(d)
    assert log[-1] is d and idx.of("signoff", ALICE)[-1] is d and d["id"] in idx.ids  # the list it was built from grows too


def test_the_engine_gives_the_same_answers_with_a_prebuilt_index():
    from teachermodel.workflow import EventIndex

    wf = doc(step("a", "instructor"), step("b", "instructor", needs=["tm:step/a"]),
             step("c", "candidate", needs=["tm:step/a"]))
    log = [reg(ALICE, "sme-engineer"), reg(PAUL, "partner"), cand(CAND_A, ALICE), done("tm:step/a", ALICE, "2026-10-05")]
    s = subjects(log)
    plain = next_steps(wf, log, s, TODAY)
    assert plain and plain == next_steps(wf, log, s, TODAY, index=EventIndex(list(log)))
    idx = EventIndex(list(log))
    assert needs_met(wf, log, s, "tm:step/b", ALICE) == needs_met(wf, log, s, "tm:step/b", ALICE, index=idx)
    assert unmet_needs(wf, log, s, "tm:step/b", PAUL) == unmet_needs(wf, log, s, "tm:step/b", PAUL, index=idx) == [
        "tm:step/a"]


# --- a closed child has no due steps (decision 0015, integration review finding 3) ------------------------------------


SYSTEM = "tm:system/teachermodel"


def closed_check(subject, actor=SYSTEM):
    return make_event("check", subject, actor, {"step": "tm:step/bench-decision", "result": "closed"},
                      at="2026-10-05T09:00:00+00:00")


def test_a_candidate_closed_by_a_system_check_and_its_assignments_have_no_due_steps():
    d = doc(step("approve-c", "candidate"), step("observe", "assignment", needs=["tm:step/approve-c"]))
    log = [reg(ALICE, "sme-engineer"), reg(PAUL, "sme-engineer"), cand(CAND_A, ALICE), cand(CAND_P, PAUL),
           assignment(ASSIGN_A, CAND_A, ALICE), done("tm:step/approve-c", CAND_A)]
    assert ids(next_steps(d, log, subjects(log), TODAY)) == [
        ("tm:step/approve-c", CAND_P), ("tm:step/observe", ASSIGN_A)]
    closed = [*log, closed_check(CAND_A)]
    assert ids(next_steps(d, closed, subjects(closed), TODAY)) == [("tm:step/approve-c", CAND_P)]
    assert not needs_met(d, closed, subjects(closed), "tm:step/observe", ASSIGN_A)
    assert needs_met(d, log, subjects(log), "tm:step/observe", ASSIGN_A)


def test_a_closed_check_from_anyone_but_the_system_closes_nothing():
    d = doc(step("approve-c", "candidate"))
    log = [reg(ALICE, "sme-engineer"), cand(CAND_A, ALICE), closed_check(CAND_A, actor=ACTOR)]
    assert ids(next_steps(d, log, subjects(log), TODAY)) == [("tm:step/approve-c", CAND_A)]
