"""surfaces.py: the read models behind the role surfaces, and the audience policy every one is projected through
(standards/audience.yaml, decision 0027). The privacy test renders every surface for every role. One-week simulated
store with a schedule, clearances, an outcome, an audition and a course record added. Generated data only."""

import hashlib
import json
from datetime import date, datetime, timezone

import pytest
import yaml

from teachermodel import app, course, events, simulate, surfaces

UNIT = "sl:unit/example-agent-loop@1"
NOW = datetime(2026, 10, 30, 7, 0, tzinfo=timezone.utc)
A, D = "tm:instructor/a1c4f", "tm:instructor/d7h2k"


def clearance(uri, modes, expires):
    slug = uri.split("/")[-1]
    return events.make_event(
        "clearance", uri, "tm:system/teachermodel",
        {"clearance": "tm:clearance/" + hashlib.sha256(slug.encode()).hexdigest()[:16],
         "candidate": f"tm:candidate/{slug}--example-agent-loop-1--in-person", "instructor": uri, "unit": UNIT,
         "modes": modes, "outcome": "cleared", "conditions": [], "recheck": None,
         "clearers": ["tm:person/clearer-a", "tm:person/clearer-b"], "observations": ["obs-00000001"],
         "issued": "2026-01-01", "expires": expires, "framework_version": "1.1.0"}, at="2026-10-01T09:00:00+00:00")


SESSIONS = [
    {"ref": "onboarding-c4", "programme": "platform-onboarding-c4", "unit": UNIT, "mode": "in-person",
     "from": "2026-11-09", "to": "2026-11-13", "region": "IE", "lead": A, "expected_learners": 24,
     "status": "confirmed"},
    {"ref": "cohort12-agg-lab", "programme": "cohort-12", "unit": UNIT, "lab": "aggregates-only-export",
     "mode": "in-person", "from": "2026-11-12", "to": "2026-11-12", "region": "IE", "lead": D, "observer": A,
     "expected_learners": 18, "status": "confirmed"},
    {"ref": "agent-loop-g1", "programme": "cohort-11", "unit": UNIT, "mode": "in-person", "from": "2026-10-06",
     "to": "2026-10-06", "region": "IE", "lead": D, "expected_learners": 20, "status": "confirmed"},
    {"ref": "agent-loop-g2", "programme": "cohort-11", "unit": UNIT, "mode": "in-person", "from": "2026-10-27",
     "to": "2026-10-27", "region": "IE", "lead": A, "expected_learners": 16, "status": "confirmed"},
]


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("surfaces") / "store"
    try:
        simulate.simulate(s, weeks=1, end=date(2026, 10, 23))
        log = s / app.EVENT_LOG
        events.append(log, clearance(A, ["in-person"], "2026-11-10"))  # expires mid-programme
        events.append(log, clearance(D, ["in-person"], "2027-10-01"))
        events.append(log, events.make_event(
            "outcome", D, "tm:system/teachermodel",
            {"delivery_ref": "agent-loop-g1", "instructor": D, "unit": UNIT, "mode": "in-person",
             "delivered_on": "2026-10-06", "learners_assessed": 18, "score": 83.3, "baseline": 69.8,
             "source": "proving-ground"}, at="2026-10-28T08:00:00+00:00"))
        (s / "inputs").mkdir(exist_ok=True)
        (s / "inputs" / "schedule.yaml").write_text(yaml.safe_dump(
            {"schema": "tm:contract/schedule@1", "exported_at": "2026-10-28T07:00:00Z", "sessions": SESSIONS},
            sort_keys=False), encoding="utf-8")
        folder = s / "auditions" / "a-211a3a"
        folder.mkdir(parents=True)
        (folder / "audition.yaml").write_text(yaml.safe_dump(
            {"id": "a-211a3a", "unit": UNIT, "mode": "remote", "opened": "2026-10-23", "observers": [A, D]}),
            encoding="utf-8")
        (folder / "result.yaml").write_text(yaml.safe_dump(
            {"id": "a-211a3a", "overall_mean": 2.6, "overall_meets_clearance_bar": False,
             "domains_to_discuss": ["conceptual-questioning"]}), encoding="utf-8")
        course.record(s, A, "micro-teach", "evidence/ttt/a1c4f-micro-teach.pdf", date(2026, 10, 8),
                      app.load_state(s).registrations)
        yield s
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def built(store):
    ctx = surfaces.context(store, NOW)
    return ctx, {"this-week": surfaces.this_week(ctx), "coordinator-board": surfaces.coordinator_board(ctx),
                 "my-record": surfaces.my_record(ctx, A)}


def test_this_week_holds_the_heads_decisions_and_risks(built):
    _, m = built
    week = m["this-week"]
    assert [a["audition"] for a in week["decisions"]["auditions"]] == ["a-211a3a"]
    assert week["decisions"]["auditions"][0]["domains_to_discuss"] == ["conceptual-questioning"]
    risks = {(r["kind"], r["session"]) for r in week["risks"]}
    assert ("clearance-expires", "onboarding-c4") in risks
    assert ("lab-unchecked", "cohort12-agg-lab") in risks
    assert ("clearance-expires", "cohort12-agg-lab") not in risks
    assert {s["source"] for s in week["sources"]} >= {"release-check"}


def test_the_coordinator_board_counts_without_scores(built):
    _, m = built
    board = m["coordinator-board"]
    rows = {d["session"]: d for d in board["deliveries"]}
    assert (rows["agent-loop-g1"]["expected"], rows["agent-loop-g1"]["received"]) == (20, 18)
    assert rows["agent-loop-g2"]["received"] is None
    assert "onboarding-c4" not in rows  # not delivered yet
    assert [a["stage"] for a in board["auditions"]] == ["awaiting decision"]


def test_my_record_is_the_instructors_own(built):
    _, m = built
    mine = m["my-record"]
    assert mine["instructor"] == A
    assert {(s["session"], s["role"]) for s in mine["sessions_ahead"]} == {("onboarding-c4", "lead"),
                                                                           ("cohort12-agg-lab", "observer")}
    assert mine["clearances"][0]["expires"] == "2026-11-10"
    assert mine["course"][0]["recorded"] == "2026-10-08"


# --- the privacy test: every surface, every role ---------------------------------------------------------------------

def keys(value, path=""):
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{path}.{k}" if path else k, k
            yield from keys(v, f"{path}.{k}" if path else k)
    elif isinstance(value, list):
        for item in value:
            yield from keys(item, path)


def strings(value, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from strings(v, k)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item, key)
    elif isinstance(value, str):
        yield key, value


def test_every_surface_for_every_role_shows_only_what_the_policy_allows(store, built):
    ctx, models = built
    policy = surfaces.policy()
    names = [p["name"] for p in yaml.safe_load((store / "identities" / "people.yaml").read_text(encoding="utf-8"))
             ["people"] if p.get("name")]
    assert names
    for role, allowed in policy["roles"].items():
        for surface, model in models.items():
            if surface not in allowed["surfaces"]:
                with pytest.raises(surfaces.AudienceError):
                    surfaces.project(model, surface, role, viewer=A)
                continue
            seen = surfaces.project(model, surface, role, viewer=A)
            text = json.dumps(seen)
            assert not [n for n in names if n in text], f"{role} sees a name on {surface}"
            never = allowed.get("never") or []
            leaked = [p for p, k in keys(seen) if any(w in k for w in never)]
            assert not leaked, f"{role} sees {leaked} on {surface}"
            if allowed.get("own_only"):
                others = [(k, v) for k, v in strings(seen) if v.startswith("tm:instructor/") and v != A
                          and k not in policy["named_roles"]]
                assert not others, f"{role} sees another instructor's id: {others}"
    coordinator = surfaces.project(models["coordinator-board"], "coordinator-board", "coordinator")
    assert "score" not in json.dumps(coordinator) and coordinator["deliveries"]


def test_a_whitelist_mistake_cannot_leak_a_score(tmp_path):
    (tmp_path / "standards").mkdir()
    (tmp_path / "standards" / "audience.yaml").write_text(yaml.safe_dump({"roles": {"coordinator": {
        "surfaces": {"coordinator-board": ["deliveries", "course.instructor"]}, "never": ["score"]}}}), encoding="utf-8")
    model = {"deliveries": [{"session": "x", "expected": 20}], "course": [{"instructor": "tm:instructor/a", "n": 1}]}
    seen = surfaces.project(model, "coordinator-board", "coordinator", root=tmp_path)
    assert seen == {"deliveries": [{"session": "x", "expected": 20}], "course": [{"instructor": "tm:instructor/a"}]}
    model["deliveries"][0]["score"] = 83.3  # a field added to the read model later, inside a whitelisted subtree
    with pytest.raises(surfaces.AudienceError, match="score"):
        surfaces.project(model, "coordinator-board", "coordinator", root=tmp_path)


def test_an_instructor_cannot_open_another_instructors_record(built):
    _, m = built
    with pytest.raises(surfaces.AudienceError, match="own record"):
        surfaces.project(m["my-record"], "my-record", "instructor", viewer=D)


# --- the feeds (decision 0028) ---------------------------------------------------------------------------------------

def feed_store(store, tmp_path, lab_status):
    import shutil

    s = tmp_path / "fed"
    shutil.copytree(store, s)
    (s / "inputs" / "release-status.json").write_text(json.dumps(
        {"schema": "tm:contract/release-status@1", "source": "proving-ground", "run_at": "2026-10-26T07:40:00+00:00",
         "labs": [{"lab": "aggregates-only-export", "unit": None, "status": lab_status, "checks": 1,
                   "failed": int(lab_status == "failed")}],
         "shared": {"status": "passed", "checks": 9, "failed": 0}}), encoding="utf-8")
    (s / "inputs" / "results-received.json").write_text(json.dumps(
        {"schema": "tm:contract/results-received@1", "source": "proving-ground",
         "exported_at": "2026-10-29T09:00:00+00:00",
         "deliveries": [{"delivery_ref": "agent-loop-g2", "received": 14, "unreadable": 1}]}), encoding="utf-8")
    return surfaces.context(s, NOW)


def test_a_lab_that_passed_this_weeks_check_is_no_risk_and_a_failing_one_is(store, tmp_path):
    passed = surfaces.this_week(feed_store(store, tmp_path / "p", "passed"))
    assert not [r for r in passed["risks"] if r["session"] == "cohort12-agg-lab" and r["kind"].startswith("lab")]
    failed = surfaces.this_week(feed_store(store, tmp_path / "f", "failed"))
    assert ("lab-failing", "cohort12-agg-lab") in {(r["kind"], r["session"]) for r in failed["risks"]}


def test_the_coordinator_sees_results_received_and_unreadable_as_counts(store, tmp_path):
    board = surfaces.coordinator_board(feed_store(store, tmp_path, "passed"))
    rows = {d["session"]: d for d in board["deliveries"]}
    assert (rows["agent-loop-g2"]["received"], rows["agent-loop-g2"]["unreadable"]) == (14, 1)
    assert (rows["agent-loop-g1"]["received"], rows["agent-loop-g1"]["unreadable"]) == (18, None)
    seen = surfaces.project(board, "coordinator-board", "coordinator")
    assert {d["session"]: d["unreadable"] for d in seen["deliveries"]}["agent-loop-g2"] == 1
