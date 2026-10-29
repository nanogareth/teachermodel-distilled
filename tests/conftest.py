from datetime import date

import pytest

from teachermodel.standards import domain_ids, load_standards


@pytest.fixture(scope="session")
def rules():
    return load_standards()["rules"]


@pytest.fixture(scope="session")
def domains():
    return domain_ids()


@pytest.fixture
def calibrations():
    # Observers A, B and coach C passed calibration on 1 Sep 2026; D's pass has lapsed.
    return {
        "tm:instructor/obs-a": [date(2026, 9, 1)],
        "tm:instructor/obs-b": [date(2026, 9, 1)],
        "tm:instructor/coach-c": [date(2026, 9, 1)],
        "tm:instructor/obs-d": [date(2025, 9, 1)],
    }


@pytest.fixture(autouse=True)
def _appdata_outside_tmp(monkeypatch):
    # pytest's tmp_path sits under %LOCALAPPDATA%\Temp; point the 0006 AppData guard elsewhere so
    # tests can use tmp_path as a private dir. test_config sets these itself to test the guard.
    monkeypatch.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    monkeypatch.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")


# --- fictional private store (CLI and app tests) ------------------------------------------------

import shutil as _shutil  # noqa: E402

import yaml as _yaml  # noqa: E402

from teachermodel.standards import ROOT as _ROOT  # noqa: E402

EXAMPLE_ROSTER_PATH = _ROOT / "standards" / "templates" / "roster.example.yaml"
FICTIONAL_SETTINGS = {
    "schema": "tm:contract/settings@1",
    "library": "TeacherModel Private",
    "mailbox": "signoffs@example.com",
    "it_email": "it.requests@example.com",
    "dpo_email": "dpo@example.com",
    "notice_version": "2026-11",
}
# One fictional person per role the workflows need; two coordinators for the one-page-per-signer rule.
FICTIONAL_PEOPLE = [
    {"person": "tm:person/it-1", "name": "Pat Itperson", "email": "pat.it@example.com", "roles": ["it"]},
    {"person": "tm:person/dpo-1", "name": "Dana Dataofficer", "email": "dana.dpo@example.com", "roles": ["dpo"]},
    {"person": "tm:person/legal-1", "name": "Lena Legalcounsel", "email": "legal.lena@example.com",
     "roles": ["legal"]},
    {"person": "tm:person/owner-1", "name": "Olive Owner", "email": "olive.owner@example.com",
     "roles": ["programme-owner"]},
    {"person": "tm:person/hot-1", "name": "Hal Headtraining", "email": "hal.head@example.com",
     "roles": ["head-of-training"]},
    {"person": "tm:person/eng-manager-1", "name": "Maxine Manager", "email": "maxine.mgr@example.com",
     "roles": ["manager"]},
    {"person": "tm:person/partner-lead-1", "name": "Lee Partnerlead", "email": "lee.pl@example.com",
     "roles": ["partner-lead"]},
    {"person": "tm:person/coord-1", "name": "Cora Coordinator", "email": "cora.coord@example.com",
     "roles": ["coordinator"]},
    {"person": "tm:person/coord-2", "name": "Kit Coordinator", "email": "kit.coord@example.com",
     "roles": ["coordinator"]},
]


def make_fictional_store(base):
    """`base`/private: settings and people (no events, no roster import yet). What the `fictional_store` fixture makes."""
    private = base / "private"
    (private / "identities").mkdir(parents=True)
    (private / "settings.yaml").write_text(_yaml.safe_dump(FICTIONAL_SETTINGS), encoding="utf-8")
    (private / "identities" / "people.yaml").write_text(
        _yaml.safe_dump({"schema": "tm:contract/people@1", "people": FICTIONAL_PEOPLE}), encoding="utf-8")
    return private


@pytest.fixture
def fictional_store(tmp_path):
    """A private store with settings and people (no events, no roster import yet). Returns its path."""
    return make_fictional_store(tmp_path)


# --- worlds built once per session (speed): several tests start from the same expensive state ---------------


import world_cache as _world_cache  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _world_factory(tmp_path_factory):
    _world_cache.FACTORY[:] = [tmp_path_factory]
    yield
    _world_cache.WORLDS.clear()


@pytest.fixture
def cached_world(tmp_path):
    """`cached_world(key, build)`: world_cache.copy_world into this test's tmp_path."""
    return lambda key, build: _world_cache.copy_world(key, build, tmp_path)


@pytest.fixture
def example_roster(tmp_path):
    """A copy of the fictional example roster outside the store."""
    dest = tmp_path / "roster-in.yaml"
    _shutil.copy(EXAMPLE_ROSTER_PATH, dest)
    return dest


@pytest.fixture
def fictional_names():
    """Every name and email in the fictional people list and the example roster."""
    doc = _yaml.safe_load(EXAMPLE_ROSTER_PATH.read_text(encoding="utf-8"))
    out = [p["name"] for p in FICTIONAL_PEOPLE] + [p["email"] for p in FICTIONAL_PEOPLE]
    for row in doc["instructors"]:
        out += [row["identity"]["name"], row["identity"]["email"]]
    return out


# --- a repo-data root whose privacy files are the fictional fixtures (J3) ---------------------------

from privacy_helpers import make_privacy_root as _make_privacy_root  # noqa: E402


@pytest.fixture
def privacy_root(tmp_path):
    return _make_privacy_root(tmp_path)


# --- flow registries: a test that registers an auto step or a sign-off hook must not leak it ----------

@pytest.fixture
def registries():
    """Snapshot teachermodel.flows' AUTO_STEPS and SIGNOFF_HOOKS, hand them to the test, restore them afterwards."""
    from teachermodel import flows

    auto, hooks = dict(flows.AUTO_STEPS), {k: list(v) for k, v in flows.SIGNOFF_HOOKS.items()}
    checks = {k: list(v) for k, v in flows.CONTENT_CHECKS.items()}
    yield flows
    flows.AUTO_STEPS.clear()
    flows.AUTO_STEPS.update(auto)
    flows.SIGNOFF_HOOKS.clear()
    flows.SIGNOFF_HOOKS.update(hooks)
    flows.CONTENT_CHECKS.clear()
    flows.CONTENT_CHECKS.update(checks)
