"""`teachermodel audition` (audition.py, decision 0025): a candidate's audition on the clearance rubric, kept apart from the
instructor record. Pure evidence rules at their edges, then the whole flow on a one-week simulated store (generated data)."""

from datetime import date

import pytest
import yaml

from teachermodel import app, audition, cli, simulate
from teachermodel.standards import ROOT, load_standards

UNIT = "sl:unit/example-agent-loop@1"
DAY = date(2026, 10, 23)
STD = load_standards()
ORDER = [d["id"] for d in STD["framework"]["domains"]]
RULES = STD["rules"]


def forms(a, b):
    return {"tm:instructor/o1": dict(zip(ORDER, a)), "tm:instructor/o2": dict(zip(ORDER, b))}


def test_a_domain_average_at_the_bar_meets_it_and_below_does_not():
    doc = audition.evidence(forms([2, 1, 3, 3, 3], [2, 2, 3, 3, 3]), ORDER, RULES)
    by = {x["domain"]: x for x in doc["domains"]}
    assert by[ORDER[0]]["average"] == 2 and by[ORDER[0]]["meets_clearance_bar"]
    assert by[ORDER[1]]["average"] == 1.5 and not by[ORDER[1]]["meets_clearance_bar"]


def test_the_overall_mean_at_the_bar_meets_it():
    assert audition.evidence(forms([3] * 5, [3] * 5), ORDER, RULES)["overall_meets_clearance_bar"]
    assert not audition.evidence(forms([3, 3, 3, 3, 2], [3] * 5), ORDER, RULES)["overall_meets_clearance_bar"]


def test_observers_two_points_apart_are_flagged_and_one_apart_are_not():
    doc = audition.evidence(forms([1, 2, 3, 4, 2], [3, 3, 3, 3, 2]), ORDER, RULES)
    assert doc["domains_to_discuss"] == [ORDER[0]]
    assert doc["agreement_within_one"] == 0.8


def test_the_evidence_never_recommends():
    doc = audition.evidence(forms([4] * 5, [4] * 5), ORDER, RULES)
    assert not {"recommendation", "decision", "hire", "outcome"} & set(doc)


def test_the_starting_plan_takes_the_two_lowest_domains_below_three():
    doc = audition.evidence(forms([2, 3, 1, 2, 4], [2, 3, 2, 3, 4]), ORDER, RULES)
    assert audition.starting_plan(doc, ORDER) == [(ORDER[2], 1.5), (ORDER[0], 2.0)]
    assert audition.starting_plan(audition.evidence(forms([3] * 5, [3] * 5), ORDER, RULES), ORDER) == []


def test_a_real_store_is_refused_until_retention_covers_auditions(tmp_path):
    assert audition.gate({"simulated": True}) is None
    assert "audition-records" in audition.gate({}, ROOT)
    (tmp_path / "standards").mkdir()
    (tmp_path / "standards" / "retention.yaml").write_text(
        "entries:\n  - category: audition-records\n    purpose: hiring\n", encoding="utf-8")
    assert audition.gate({}, tmp_path) is None


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("audition") / "store"
    try:
        simulate.simulate(s, weeks=1, end=DAY)
        yield s
    finally:
        mp.undo()


def filled(scores, note="saw it"):
    return {d: {"score": v, "note": f"{note} ({d})"} for d, v in zip(ORDER, scores)}


def test_an_audition_end_to_end(store, monkeypatch):
    log = (store / app.EVENT_LOG).read_bytes()
    st = app.load_state(store)
    # A one-week store has no calibrated clearer yet (the end-to-end run uses a longer one), so two registered instructors
    # stand in for the pool; the pool rule itself is common.observer_pool's, tested with the observation flow.
    first, second, outsider = sorted(st.registrations)[:3]
    monkeypatch.setattr(audition, "observer_pool", lambda _st, on: [first, second] if on == DAY else [])

    a = audition.open_audition(store, UNIT, "remote", "Steps 3-4: the stop condition", "Sim Candidate", DAY,
                               audition="a-test01")
    folder = store / audition.DIR / a
    pack = (folder / "pack.md").read_text(encoding="utf-8")
    assert "Steps 3-4: the stop condition" in pack and "### technical-depth" in pack and "1 not yet" in pack
    assert "Sim Candidate" not in (folder / "audition.yaml").read_text(encoding="utf-8") + pack
    assert yaml.safe_load((store / audition.IDENTITIES).read_text(encoding="utf-8"))[a] == {"candidate": "Sim Candidate"}

    with pytest.raises(audition.AuditionError, match="two different observers"):
        audition.assign(store, a, [first, first], DAY)
    with pytest.raises(audition.AuditionError, match="observer pool"):
        audition.assign(store, a, [first, outsider], DAY)
    audition.assign(store, a, [first, second], DAY)

    with pytest.raises(audition.AuditionError, match="1 to 4"):
        audition.score(store, a, first, filled([3, 3, 5, 3, 3]))
    with pytest.raises(audition.AuditionError, match="exactly the domains"):
        audition.score(store, a, first, {ORDER[0]: {"score": 3}})
    with pytest.raises(audition.AuditionError, match="not an observer"):
        audition.score(store, a, outsider, filled([3] * 5))
    audition.score(store, a, first, filled([3, 2, 1, 3, 4], "first saw"))
    with pytest.raises(audition.AuditionError, match="recorded once"):
        audition.score(store, a, first, filled([4] * 5))

    shown = audition.status(store, a)
    assert shown["scored"] == [first] and shown["waiting_for"] == [second] and "3" not in str(shown["scored"])
    with pytest.raises(audition.AuditionError, match="1 of 2 forms"):
        audition.result(store, a)
    with pytest.raises(audition.AuditionError, match="result"):
        audition.decide(store, a, "hired", "Strong technical depth and clear lab running.", "tm:person/head", DAY)

    audition.score(store, a, second, filled([3, 3, 3, 3, 4], "second saw"))
    doc = audition.result(store, a)
    assert [x["average"] for x in doc["domains"]] == [3, 2.5, 2, 3, 4]
    assert doc["domains_to_discuss"] == [ORDER[2]]
    page = (folder / "result.md").read_text(encoding="utf-8")
    assert "evidence, not a decision" in page and "first saw (lab-facilitation)" in page

    with pytest.raises(audition.AuditionError, match="reasons"):
        audition.decide(store, a, "hired", "good", "tm:person/head", DAY)
    with pytest.raises(audition.AuditionError, match="not decided as hired"):
        audition.carry(store, a, first)
    audition.decide(store, a, "hired", "Clear lab running; coach the questioning first.", "tm:person/head", DAY)
    with pytest.raises(audition.AuditionError, match="recorded once"):
        audition.decide(store, a, "not-hired", "Changed our minds after the debrief.", "tm:person/head", DAY)

    with pytest.raises(audition.AuditionError, match="not a registered instructor"):
        audition.carry(store, a, "tm:instructor/not-yet-on-the-roster")
    plan = audition.carry(store, a, outsider).read_text(encoding="utf-8")
    assert "## conceptual-questioning (audition average 2.0)" in plan and "## prior-knowledge (audition average 2.5)" in plan
    assert "second saw (prior-knowledge)" in plan
    assert yaml.safe_load((store / audition.IDENTITIES).read_text(encoding="utf-8"))[a]["instructor"] == outsider

    assert (store / app.EVENT_LOG).read_bytes() == log  # nothing entered the event log


def test_the_cli_opens_and_reports(store, capsys):
    assert cli.main(["audition", "new", "--private-dir", str(store), "--unit", UNIT, "--mode", "in-person",
                     "--slice", "Step 1", "--candidate", "Sim Other", "--on", "2026-10-23"]) == 0
    made = capsys.readouterr().out.split("opened ")[1].split(";")[0]
    assert cli.main(["audition", "status", made, "--private-dir", str(store)]) == 0
    assert '"waiting_for": []' in capsys.readouterr().out
    assert cli.main(["audition", "result", made, "--private-dir", str(store)]) == 1
    assert "0 of 2 forms" in capsys.readouterr().err
    assert cli.main(["audition", "new", "--private-dir", str(store), "--unit", UNIT]) == 1
    assert "--mode, --slice, --candidate" in capsys.readouterr().err


def test_the_real_observer_pool_is_asked(store, capsys):
    """No stand-in: on the one-week store no clearer is calibrated yet, so the real pool refuses every observer."""
    a = audition.open_audition(store, UNIT, "hybrid", "Step 2", "Sim Third", DAY, audition="a-test03")
    first, second = sorted(app.load_state(store).registrations)[:2]
    assert cli.main(["audition", "assign", a, "--private-dir", str(store), "--observer", first, "--observer", second,
                     "--on", DAY.isoformat()]) == 1
    assert "not in the observer pool on 2026-10-23" in capsys.readouterr().err


def decided(store, audition_id, observers, on=DAY):
    a = audition.open_audition(store, UNIT, "remote", "Step 5", "Sim Hire", on, audition=audition_id)
    audition.assign(store, a, observers, on)
    for o in observers:
        audition.score(store, a, o, filled([3, 2, 3, 3, 4]))
    audition.result(store, a)
    audition.decide(store, a, "hired", "Clear lab running; coach the questioning first.", "tm:person/head", on)
    return a


def test_carry_refuses_a_second_audition_for_the_same_instructor(store, monkeypatch):
    regs = sorted(app.load_state(store).registrations)
    first, second, hire = regs[0], regs[1], regs[3]
    monkeypatch.setattr(audition, "observer_pool", lambda _st, on: [first, second])
    a, b = decided(store, "a-carry1", [first, second]), decided(store, "a-carry2", [first, second])
    plan = audition.carry(store, a, hire)
    kept = plan.read_bytes()
    with pytest.raises(audition.AuditionError, match=f"already carried.*{a}"):
        audition.carry(store, b, hire)
    with pytest.raises(audition.AuditionError, match="already carried"):
        audition.carry(store, a, regs[4])  # one audition starts one instructor's plan
    assert plan.read_bytes() == kept  # the first plan is never overwritten
    assert "instructor" not in yaml.safe_load((store / audition.IDENTITIES).read_text(encoding="utf-8"))[b]


def test_an_observer_can_be_replaced_before_they_score_and_not_after(store, monkeypatch):
    regs = sorted(app.load_state(store).registrations)
    first, second, third, outsider = regs[0], regs[1], regs[2], regs[5]
    monkeypatch.setattr(audition, "observer_pool", lambda _st, on: [first, second, third])
    a = audition.open_audition(store, UNIT, "remote", "Step 6", "Sim Swap", DAY, audition="a-swap01")
    with pytest.raises(audition.AuditionError, match="no observers yet"):
        audition.replace(store, a, second, third, "Called away to a customer incident.", DAY)
    audition.assign(store, a, [first, second], DAY)
    with pytest.raises(audition.AuditionError, match="reason"):
        audition.replace(store, a, second, third, "ill", DAY)
    with pytest.raises(audition.AuditionError, match="observer pool"):
        audition.replace(store, a, second, outsider, "Called away to a customer incident.", DAY)
    with pytest.raises(audition.AuditionError, match="already an observer"):
        audition.replace(store, a, second, first, "Called away to a customer incident.", DAY)
    with pytest.raises(audition.AuditionError, match="not an observer"):
        audition.replace(store, a, third, second, "Called away to a customer incident.", DAY)
    audition.replace(store, a, second, third, "Called away to a customer incident.", DAY)
    record = yaml.safe_load((store / audition.DIR / a / "audition.yaml").read_text(encoding="utf-8"))
    assert record["observers"] == sorted([first, third])
    assert record["replaced"] == [{"leaving": second, "joining": third, "reason": "Called away to a customer incident.",
                                   "on": DAY.isoformat()}]
    with pytest.raises(audition.AuditionError, match="not an observer"):
        audition.score(store, a, second, filled([3] * 5))
    audition.score(store, a, first, filled([3] * 5))
    with pytest.raises(audition.AuditionError, match="has scored"):
        audition.replace(store, a, first, second, "Second thoughts after scoring it.", DAY)


def test_the_cli_replaces_an_observer(store, monkeypatch, capsys):
    regs = sorted(app.load_state(store).registrations)
    monkeypatch.setattr(audition, "observer_pool", lambda _st, on: regs[:3])
    a = audition.open_audition(store, UNIT, "remote", "Step 7", "Sim Cli", DAY, audition="a-swap02")
    audition.assign(store, a, regs[:2], DAY)
    assert cli.main(["audition", "replace", a, "--private-dir", str(store), "--leaving", regs[1], "--joining", regs[2],
                     "--reasons", "On leave the week of the audition.", "--on", DAY.isoformat()]) == 0
    assert f"{regs[1]} replaced by {regs[2]}" in capsys.readouterr().out
    assert cli.main(["audition", "replace", a, "--private-dir", str(store), "--leaving", regs[2]]) == 1
    assert "--leaving, --joining and --reasons" in capsys.readouterr().err
