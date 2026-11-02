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
             "domains_to_discuss": ["conceptual-questioning"],
             "clearance_bar": {"domain_average": 2, "overall_mean": 3},
             "domains": [{"domain": d, "scores": {A: a, D: b}, "average": (a + b) / 2}
                         for d, a, b in (("technical-depth", 3, 3), ("conceptual-questioning", 1, 3))]}),
            encoding="utf-8")
        course.record(s, A, "micro-teach", "evidence/ttt/a1c4f-micro-teach.pdf", date(2026, 10, 8),
                      app.load_state(s).registrations)
        yield s
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def built(store):
    ctx = surfaces.context(store, NOW)
    models = {"this-week": surfaces.this_week(ctx), "coordinator-board": surfaces.coordinator_board(ctx),
              "my-record": surfaces.my_record(ctx, A)}
    ctx.con.close()  # the models are plain data; an open index would block the next rebuild on Windows
    return ctx, models


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


# --- the head's This week page (surface_pages.py) --------------------------------------------------------------------

def test_this_week_lists_the_sessions_ahead_and_what_it_waits_for(built):
    _, m = built
    week = m["this-week"]
    assert [a["session"] for a in week["ahead"]] == ["onboarding-c4", "cohort12-agg-lab"]
    assert {"kind": "results", "session": "agent-loop-g2", "programme": "cohort-11", "ended": "2026-10-27"} \
        in week["waiting"]
    assert week["release_check"]["state"] == "never"
    assert week["decisions"]["auditions"][0]["domains"][1]["scores"] == {A: 1, D: 3}


# --- the coordinator board and My record pages ---------------------------------------------------------------------------


# --- the override card: an open request is the head's decision ----------------------------------------

def week_at(s, now):
    ctx = surfaces.context(s, now)
    try:
        return surfaces.this_week(ctx)
    finally:
        ctx.con.close()  # an open index blocks the next rebuild on Windows


def test_an_override_for_a_day_gone_by_is_not_asked_any_more(store, tmp_path):
    import shutil

    from teachermodel.flows import override

    s = tmp_path / "gone"
    shutil.copytree(store, s)
    override.request_override(s, instructor=A, unit=UNIT, mode="in-person", date="2026-10-29",
                              now=datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc))
    assert week_at(s, NOW)["decisions"]["overrides"] == []


def _room(store, n, held, ended, lab="lab-a", demo=False):
    path = store / "inputs" / "rooms"
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{lab}-{n}.json").write_text(json.dumps(
        {"schema": "tm:contract/room-summary@1", "source": "generated", "room_id": f"{lab}-{n}", "lab": lab,
         "started_at": ended, "ended_at": ended, "minutes": 60, "devices": 12,
         "steps": [{"step": 2, "title": "Property 1", "reached": 9, "stuck_at_end": 0, "stuck_peak": 5,
                    "long_stuck_peak": 4, "held_minutes": held}],
         "marks": [{"minute": 20, "step": 2}] if demo else [], "refused": 0}), encoding="utf-8")


def test_stalls_count_rooms_that_a_step_held_within_six_months(tmp_path):
    _room(tmp_path, 1, 9, "2026-10-01T09:00:00+00:00", demo=True)
    _room(tmp_path, 2, 0, "2026-09-01T09:00:00+00:00")
    _room(tmp_path, 3, 30, "2026-04-29T09:00:00+00:00")  # 184 days before: outside
    _room(tmp_path, 4, 5, "2026-04-30T09:00:00+00:00", lab="lab-b")  # 183 days before: inside
    found = surfaces._stalls(surfaces.Context(tmp_path, NOW, NOW.date(), None, (), [], {}, tmp_path, {}, {}, []))
    assert (found["rooms"], found["labs"]) == (3, 2)
    assert [(s["lab"], s["rooms"], s["rooms_held"], s["longest_held"], s["demonstrated"]) for s in found["steps"]] == [
        ("lab-a", 2, 1, 9, 1), ("lab-b", 1, 1, 5, 0)]


def test_stalls_reach_only_the_head_and_name_no_one(store, built):
    policy = surfaces.policy()
    assert "stalls" in surfaces.project({"stalls": {}}, "this-week", "head-of-training")
    assert "this-week" not in policy["roles"]["coordinator"]["surfaces"]
    assert "this-week" not in policy["roles"]["instructor"]["surfaces"]
    schema = json.loads((surfaces.ROOT / "contracts" / "room-summary.schema.json").read_text(encoding="utf-8"))
    assert not {"session", "instructor", "lead", "device"} & set(schema["properties"])


