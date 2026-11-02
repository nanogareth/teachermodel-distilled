"""Programme requests (decision 0034): the form's checks, the stages as events, and what the requester may read.
Generated data only: a one-week simulated store with a clearance added."""

import json
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from teachermodel import app, bridge, cli, events, requests, simulate, surfaces

NOW = datetime(2026, 10, 8, 7, 0, tzinfo=timezone.utc)
A, B = "tm:instructor/a1c4f", "tm:instructor/d7h2k"
MAIL = "generated.requester@example.com"


def form(**changes):
    doc = {"schema": requests.FORM, "unit": simulate.UNIT, "mode": "remote", "from": "2026-11-02", "to": "2026-11-03",
           "expected_learners": 20, "programme": "Generated programme"}
    doc.update(changes)
    return {k: v for k, v in doc.items() if v is not None}


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("requests") / "store"
    simulate.simulate(s, weeks=1, end=date(2026, 10, 7))
    events.append(s / app.EVENT_LOG, events.make_event(
        "clearance", A, "tm:system/teachermodel",
        {"clearance": "tm:clearance/0123456789abcdef", "candidate": "tm:candidate/a1c4f--example-agent-loop-1--remote",
         "instructor": A, "unit": simulate.UNIT, "modes": ["remote", "hybrid"], "outcome": "cleared", "conditions": [],
         "recheck": None, "clearers": ["tm:person/clearer-a", "tm:person/clearer-b"], "observations": ["obs-00000001"],
         "issued": "2026-01-01", "expires": "2027-01-01", "framework_version": "1.1.0"}, at="2026-01-01T09:00:00+00:00"))
    mp.undo()
    return s


@pytest.fixture
def store(base, tmp_path, monkeypatch):
    import shutil

    monkeypatch.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    monkeypatch.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    target = tmp_path / "s"
    shutil.copytree(base, target)
    return target


# --- the checks -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("changes, word", [
    ({"from": "2026-10-07"}, "has passed"),
    ({"to": "2026-11-01"}, "before the first day"),
    ({"mode": "in-person"}, "region: required"),
    ({"mode": "hybrid"}, "region: required"),
    ({"unit": "sl:unit/no-such-unit@1"}, "not a published unit"),
    ({"expected_learners": 0}, "expected_learners"),
    ({"schema": "x"}, "not a programme request"),
    ({"from": "2026-13-40"}, "real dates"),
    ({"instructor": A}, "not a valid value"),
])
def test_a_request_that_cannot_stand_says_why(changes, word):
    assert any(word in p for p in requests.problems(form(**changes), NOW.date()))


def test_the_first_day_may_be_today_and_remote_needs_no_region():
    assert requests.problems(form(**{"from": "2026-10-08", "to": "2026-10-08"}), NOW.date()) == []
    assert requests.problems(form(mode="in-person", region="IE"), NOW.date()) == []


def test_reply_by_counts_two_working_days_across_a_weekend():
    assert requests.add_working_days(date(2026, 11, 2), 2) == date(2026, 11, 4)  # Monday to Wednesday
    assert requests.add_working_days(date(2026, 11, 5), 2) == date(2026, 11, 9)  # Thursday to Monday
    assert requests.add_working_days(date(2026, 11, 7), 2) == date(2026, 11, 10)  # Saturday to Tuesday


# --- the stages -----------------------------------------------------------------------------------------------------


def log(store):
    return list(events.read(store / app.EVENT_LOG))


def test_a_request_keeps_the_person_out_of_the_log(store):
    made = requests.new(store, form(), MAIL, NOW)
    assert made.created and re.fullmatch(r"req-[0-9a-f]{10}", made.request)
    text = (store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert MAIL not in text and "Generated programme" not in text
    assert requests.private_document(store, made.request)["requester"] == MAIL
    row = requests.state(log(store))[made.request]
    assert row["stage"] == "received" and row["reply_by"] == "2026-10-12"
    for e in log(store):
        assert not events.check_event(e)


def test_the_same_request_sent_twice_is_one_request(store):
    first = requests.new(store, form(), MAIL, NOW)
    again = requests.new(store, form(), MAIL.upper(), NOW + timedelta(days=1))
    assert again.request == first.request and not again.created
    assert sum(e["kind"] == "request" for e in log(store)) == 1


def test_a_refused_request_leaves_nothing(store):
    before = (store / app.EVENT_LOG).read_bytes()
    with pytest.raises(requests.RequestError, match="has passed"):
        requests.new(store, form(**{"from": "2026-01-01"}), MAIL, NOW)
    assert (store / app.EVENT_LOG).read_bytes() == before and not (store / requests.DIR).exists()


def test_a_real_store_needs_a_retention_entry_first():
    assert requests.gate({"simulated": True}) is None
    assert "programme-request-records" in requests.gate({})


def test_propose_then_confirm_appends_and_rewrites_nothing(store):
    rid = requests.new(store, form(), MAIL, NOW).request
    before = (store / app.EVENT_LOG).read_bytes()
    assert requests.propose(store, rid, A, NOW) == "ok"
    assert requests.confirm(store, rid, NOW) == "ok"
    assert (store / app.EVENT_LOG).read_bytes().startswith(before)
    row = requests.state(log(store))[rid]
    assert row["stage"] == "confirmed" and row["instructor"] == A
    assert row["unit"] == simulate.UNIT, "a later event keeps what was asked"


def test_someone_blocked_cannot_be_proposed_and_the_stage_does_not_move(store):
    rid = requests.new(store, form(), MAIL, NOW).request
    with pytest.raises(requests.RequestError, match="may not teach"):
        requests.propose(store, rid, B, NOW)
    with pytest.raises(requests.RequestError, match="not a registered"):
        requests.propose(store, rid, "tm:instructor/nobody", NOW)
    assert requests.state(log(store))[rid]["stage"] == "received"


def test_confirm_checks_every_day_again(store, monkeypatch):
    rid = requests.new(store, form(), MAIL, NOW).request
    requests.propose(store, rid, A, NOW)
    monkeypatch.setattr(requests, "worst_verdict", lambda *_: {"verdict": "block", "reasons": ["bench decision"], "expires": None})
    with pytest.raises(requests.RequestError, match="may no longer teach this: bench decision"):
        requests.confirm(store, rid, NOW)
    assert requests.state(log(store))[rid]["stage"] == "proposed"


def test_a_clearance_ending_mid_programme_blocks_the_proposal_on_the_day_after_it(store):
    rid = requests.new(store, form(**{"from": "2027-01-01", "to": "2027-01-05"}), MAIL, NOW).request
    with pytest.raises(requests.RequestError, match="may not teach"):
        requests.propose(store, rid, A, NOW)


@pytest.mark.parametrize("action, then, word", [
    (lambda s, r: requests.confirm(s, r, NOW), "received", "propose an instructor first"),
    (lambda s, r: requests.decline(s, r, "not-a-reason", NOW), "received", "reason must be"),
])
def test_a_stage_out_of_order_is_refused(store, action, then, word):
    rid = requests.new(store, form(), MAIL, NOW).request
    with pytest.raises(requests.RequestError, match=word):
        action(store, rid)
    assert requests.state(log(store))[rid]["stage"] == then


def test_a_declined_request_takes_no_more_stages(store):
    rid = requests.new(store, form(), MAIL, NOW).request
    requests.decline(store, rid, "no-one-free", NOW)
    with pytest.raises(requests.RequestError, match="nothing to propose"):
        requests.propose(store, rid, A, NOW)
    with pytest.raises(requests.RequestError, match="already"):
        requests.withdraw(store, rid, NOW + timedelta(seconds=1))


def test_withdrawing_after_a_proposal_drops_the_person(store):
    rid = requests.new(store, form(), MAIL, NOW).request
    requests.propose(store, rid, A, NOW)
    requests.withdraw(store, rid, NOW + timedelta(seconds=1))
    assert "instructor" not in requests.state(log(store))[rid]


# --- what each person reads -----------------------------------------------------------------------------------------


def status(store, rid, now=NOW):
    ctx = surfaces.context(store, now)
    try:
        return surfaces.request_status(ctx, app.load_state(store), rid), surfaces.coordinator_board(ctx), surfaces.this_week(ctx)
    finally:
        ctx.con.close()


def seen(model):
    return surfaces.project(model, "request-status", "requester", viewer=MAIL)


def test_a_requester_opens_only_their_own_request(store):
    rid = requests.new(store, form(), MAIL, NOW).request
    model = status(store, rid)[0]
    with pytest.raises(surfaces.AudienceError):
        surfaces.project(model, "request-status", "requester", viewer="someone.else@example.com")
    with pytest.raises(surfaces.AudienceError):
        surfaces.project(model, "request-status", "instructor", viewer=A)


def test_a_finished_request_leaves_the_board_after_its_last_day(store):
    rid = requests.new(store, form(), MAIL, NOW).request
    requests.decline(store, rid, "too-soon", NOW)
    assert status(store, rid)[1]["requests"]
    assert not status(store, rid, datetime(2026, 11, 4, 7, 0, tzinfo=timezone.utc))[1]["requests"]


# --- by mail --------------------------------------------------------------------------------------------------------


def test_a_request_by_mail_is_received_with_its_sender_and_a_bad_one_keeps_nothing(store):
    lines = requests.receive(store, [(form(), MAIL), (form(**{"from": "2026-01-01"}), "other@example.com")], NOW)
    assert lines[0].endswith(": received") and lines[1].startswith("rejected: a programme request:")
    assert "other@example.com" not in lines[1]
    assert not any("other@example.com" in p.read_text(encoding="utf-8") for p in (store / requests.DIR).iterdir())


def test_the_bridge_sets_a_request_aside_before_any_sign_off_check():
    out = bridge.Applied()
    bridge._signoff("op", json.dumps(form()), MAIL, {}, {}, {}, set(), {},
                    (None, None, None, None, None, None, None, None), {}, set(), None, None, out)
    assert out.requests == [(form(), MAIL)] and not out.rejected and not out.events


def test_the_commands_answer_and_refuse(store, tmp_path, capsys):
    path = tmp_path / "form.json"
    path.write_text(json.dumps(form(**{"from": "2099-01-05", "to": "2099-01-06"})), encoding="utf-8")
    base = ["--private-dir", str(store)]
    code = cli.main(["request", "new", str(path), "--requester", MAIL, *base])
    out = capsys.readouterr().out
    assert code == 0 and "received" in out
    rid = out.split(":")[0]
    assert cli.main(["request", "status", *base]) == 0 and rid in capsys.readouterr().out
    assert cli.main(["request", "confirm", rid, *base]) == 1
    assert "propose an instructor first" in capsys.readouterr().err


