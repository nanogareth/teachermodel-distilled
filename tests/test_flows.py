import pytest

from teachermodel import app, flows
from teachermodel.standards import load_standards


def test_registry_is_what_app_uses():
    assert app.PAGE_SPECS is flows.PAGE_SPECS


def test_every_human_step_in_the_merged_workflows_has_a_builder():
    wf = load_standards()["workflows"]["workflows"]
    human = {st["id"] for w in wf for st in w["steps"] if st["type"] == "human"}
    assert human and human == set(flows.PAGE_SPECS)


def test_a_step_registers_one_builder_only():
    with pytest.raises(ValueError, match="already registered"):
        flows.register("tm:step/it-done")(lambda st, subject: [])



def test_resources_root_env_override(monkeypatch, tmp_path):
    from teachermodel import resources

    default = resources.root()
    assert (default / "standards").is_dir() and (default / "contracts").is_dir()
    monkeypatch.setenv("TEACHERMODEL_ROOT", str(tmp_path))
    assert resources.root() == tmp_path.resolve()


# --- coaches_of (increment 3, decision 0014) ----------------------------------------------------------------

K7, C5, R8, COACH_A, COACH_B = (f"tm:instructor/{s}" for s in ("k7m2q", "c5w1t", "r8n4h", "coach-a", "coach-b"))


def _state(people, registrations=None):
    from pathlib import Path

    from teachermodel.flows.common import State

    return State(private=Path("."), root=Path("."), events=[], standards={}, workflows={}, step_defs={}, subjects={},
                 registrations=registrations or {}, people=people, roster=None, identities={}, settings={})


def _person(n, roles, instructor=None, coaches=None):
    row = {"person": f"tm:person/p{n}", "name": f"P{n}", "email": f"p{n}@example.test", "roles": roles}
    if instructor:
        row["instructor"] = instructor
    if coaches is not None:
        row["coaches"] = coaches
    return row


def test_coaches_of_is_the_mapped_instructor_of_each_coach_who_lists_the_instructor():
    from teachermodel.flows.common import coaches_of

    st = _state([
        _person(1, ["coach"], COACH_A, [K7, C5]),
        _person(2, ["coach"], COACH_B, [C5]),
    ])
    assert coaches_of(st, K7) == {COACH_A}
    assert coaches_of(st, C5) == {COACH_A, COACH_B}
    assert coaches_of(st, R8) == set()  # nobody lists r8n4h


def test_coaches_of_ignores_a_coach_with_no_instructor_mapping():
    # Such a coach has no instructor URI to appear as an observer or clearer, so the limits on coaches cannot apply to them.
    from teachermodel.flows.common import coaches_of

    st = _state([_person(1, ["coach"], None, [K7]), _person(2, ["coach"], COACH_B, [K7])])
    assert coaches_of(st, K7) == {COACH_B}


def test_coaches_of_needs_the_coach_role_and_a_coaches_list():
    from teachermodel.flows.common import coaches_of

    st = _state([
        _person(1, ["clearer"], COACH_A, [K7]),  # lists the instructor but does not hold the role
        _person(2, ["coach"], COACH_B),  # holds the role, lists nobody: coaches nobody (not everybody)
    ])
    assert coaches_of(st, K7) == set()


def test_an_instructor_is_not_their_own_coach():
    from teachermodel.flows.common import coaches_of

    st = _state([_person(1, ["coach"], K7, [K7, C5])])
    assert coaches_of(st, K7) == set() and coaches_of(st, C5) == {K7}


def test_coaches_of_is_a_set_of_instructor_uris():
    from teachermodel.flows.common import coaches_of

    got = coaches_of(_state([_person(1, ["coach"], COACH_A, [K7])]), K7)
    assert isinstance(got, set) and all(u.startswith("tm:instructor/") for u in got)
