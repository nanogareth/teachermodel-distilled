from pathlib import Path

import pytest
import yaml

from teachermodel.config import ENV_VAR, ROLES, ConfigError, assert_outside_repo, people, private_dir

REPO = Path(__file__).resolve().parents[1]


def _write_people(base: Path, rows: list[dict]) -> Path:
    (base / "identities").mkdir(parents=True)
    doc = {"schema": "tm:contract/people@1", "people": rows}
    (base / "identities" / "people.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    return base


def _row(n: int, **over) -> dict:
    row = {"person": f"tm:person/p{n}", "name": f"Person {n}", "email": f"p{n}@example.test", "roles": ["coach"]}
    row.update(over)
    return row


def test_tmp_path_is_outside_the_repo(tmp_path):
    # Premise of the tests below: the pytest temp dir is not inside this repo.
    assert REPO not in tmp_path.resolve().parents
    assert_outside_repo(tmp_path)


def test_env_var_resolves(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    assert private_dir() == tmp_path.resolve()


def test_explicit_wins_over_env(monkeypatch, tmp_path):
    other = tmp_path / "other"
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "from-env"))
    assert private_dir(other) == other.resolve()


def test_unset_fails_naming_0006(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    with pytest.raises(ConfigError, match="0006"):
        private_dir()


def test_blank_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "  ")
    with pytest.raises(ConfigError, match="0006"):
        private_dir()


def test_inside_repo_refused(monkeypatch):
    for path in (REPO, REPO / ".private", REPO / "no" / "such" / "dir"):
        with pytest.raises(ConfigError, match="working tree"):
            assert_outside_repo(path)
    monkeypatch.setenv(ENV_VAR, str(REPO / ".private"))
    with pytest.raises(ConfigError, match="working tree"):
        private_dir()
    with pytest.raises(ConfigError, match="working tree"):
        private_dir(REPO)


def test_git_file_marks_a_worktree(tmp_path):
    # Worktrees and submodules have a .git FILE, not a directory.
    (tmp_path / ".git").write_text("gitdir: elsewhere", encoding="utf-8")
    with pytest.raises(ConfigError, match="working tree"):
        assert_outside_repo(tmp_path / "private")


def test_people_loads(tmp_path):
    _write_people(tmp_path, [_row(1, roles=["it", "dpo"]), _row(2)])
    rows = people(tmp_path)
    assert [r["person"] for r in rows] == ["tm:person/p1", "tm:person/p2"]
    assert rows[0]["roles"] == ["it", "dpo"]


def test_roles_cover_spec_and_setup_signers():
    assert len(ROLES) == len(set(ROLES)) == 12
    assert {"it", "dpo", "coordinator", "clearer", "partner-lead", "programme-owner"} <= set(ROLES)


def test_people_unknown_role_rejected(tmp_path):
    _write_people(tmp_path, [_row(1, roles=["coach", "wizard"])])
    with pytest.raises(ConfigError, match="unknown role 'wizard'"):
        people(tmp_path)


def test_people_duplicate_email_rejected_case_insensitively(tmp_path):
    _write_people(tmp_path, [_row(1, email="Same@Example.test"), _row(2, email="same@example.TEST")])
    with pytest.raises(ConfigError, match="duplicate email"):
        people(tmp_path)


def test_people_duplicate_person_rejected(tmp_path):
    _write_people(tmp_path, [_row(1), _row(1, email="other@example.test")])
    with pytest.raises(ConfigError, match="duplicate person id"):
        people(tmp_path)


def test_people_bad_person_id_rejected(tmp_path):
    _write_people(tmp_path, [_row(1, person="tm:instructor/p1")])
    with pytest.raises(ConfigError, match="person"):
        people(tmp_path)


def test_people_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="people.yaml"):
        people(tmp_path)


def test_roles_match_workflows_schema_enum():
    from teachermodel.standards import load_schema

    enum = load_schema("workflows.schema.json")["$defs"]["role"]["enum"]
    assert sorted(enum) == sorted(ROLES)


def test_empty_explicit_path_refused():
    with pytest.raises(ConfigError, match="empty"):
        private_dir("")


def test_appdata_path_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    target = tmp_path / "Local" / "teachermodel"
    target.mkdir(parents=True)
    with pytest.raises(ConfigError, match="LOCALAPPDATA"):
        private_dir(target)


def test_legal_role_exists():
    assert "legal" in ROLES  # verifies the privacy profiles (privacy-jurisdictions design, section 2)


def test_people_keep_the_optional_instructor_mapping(tmp_path):
    _write_people(tmp_path, [_row(1, roles=["clearer"], instructor="tm:instructor/k7m2q"), _row(2)])
    rows = people(tmp_path)
    assert rows[0]["instructor"] == "tm:instructor/k7m2q" and "instructor" not in rows[1]


def test_people_instructor_mapping_must_be_an_instructor_uri(tmp_path):
    _write_people(tmp_path, [_row(1, instructor="tm:person/k7m2q")])
    with pytest.raises(ConfigError, match="instructor"):
        people(tmp_path)


def test_people_two_persons_cannot_map_to_one_instructor(tmp_path):
    _write_people(tmp_path, [_row(1, instructor="tm:instructor/k7m2q"), _row(2, instructor="tm:instructor/k7m2q")])
    with pytest.raises(ConfigError, match="mapped by another person"):
        people(tmp_path)


# --- people@1 `coaches` (increment 3, decision 0014): the instructors a coach person coaches --------------


def test_people_keep_the_optional_coaches_list(tmp_path):
    coaches = ["tm:instructor/k7m2q", "tm:instructor/c5w1t"]
    _write_people(tmp_path, [_row(1, instructor="tm:instructor/coach-a", coaches=coaches), _row(2)])
    rows = people(tmp_path)
    assert rows[0]["coaches"] == coaches and "coaches" not in rows[1]


def test_people_coaches_may_be_empty_for_a_coach_with_no_instructors_yet(tmp_path):
    _write_people(tmp_path, [_row(1, coaches=[])])
    assert people(tmp_path)[0]["coaches"] == []


@pytest.mark.parametrize("coaches", [
    ["tm:person/k7m2q"], ["k7m2q"], "tm:instructor/k7m2q", ["tm:instructor/k7m2q", "tm:instructor/k7m2q"], [None],
])
def test_people_coaches_must_be_a_list_of_distinct_instructor_uris(tmp_path, coaches):
    _write_people(tmp_path, [_row(1, coaches=coaches)])
    with pytest.raises(ConfigError, match="coaches"):
        people(tmp_path)


def test_people_coaches_only_on_a_row_with_the_coach_role(tmp_path):
    _write_people(tmp_path, [_row(1, roles=["clearer"], coaches=["tm:instructor/k7m2q"])])
    with pytest.raises(ConfigError, match="coaches.*coach role|coach role.*coaches"):
        people(tmp_path)
    (tmp_path / "identities" / "people.yaml").unlink()
    (tmp_path / "identities").rmdir()
    _write_people(tmp_path, [_row(1, roles=["clearer", "coach"], coaches=["tm:instructor/k7m2q"])])
    assert people(tmp_path)[0]["coaches"] == ["tm:instructor/k7m2q"]
