"""An observer's calibration detail (decision 0032): own score minus the reference per domain, on My record for the
observer and the head only. Built from the two private documents, never stored; generated data only."""

import json
from datetime import date

import pytest

from teachermodel import devsign, rules, surfaces
from teachermodel.flows import calibration
from teachermodel.standards import domain_ids, load_standards

DOMAINS = domain_ids()
A, B = "tm:instructor/a1c4f", "tm:instructor/d7h2k"
TODAY = date(2026, 10, 30)


def test_bias_is_own_score_minus_the_reference_averaged():
    pairs = [({"a": 3, "b": 2}, {"a": 2, "b": 2}), ({"a": 2, "b": 1}, {"a": 2, "b": 3})]
    assert rules.calibration_bias(pairs) == {"a": 0.5, "b": -1.0}


def test_bias_counts_an_item_only_where_both_have_it():
    assert rules.calibration_bias([({"a": 4}, {"a": 1, "b": 2}), ({"a": 1, "b": 3}, {"b": 2})]) == {"a": 3.0, "b": 1.0}


def test_bias_of_nothing_is_empty():
    assert rules.calibration_bias([]) == {}


def exercise(private, log, n, observer, offset, *, passed=True, within=1.0, exact=0.6, at="2026-09-01T09:00:00+00:00"):
    """One exercise with a result for `observer`, who scores `offset` from a reference of 2 on every domain."""
    uri, sid, key = f"tm:exercise/{n:016x}", f"{n:032x}", f"calibration/{n:016x}.reference.json"
    (private / "calibration").mkdir(parents=True, exist_ok=True)
    (private / "signoffs").mkdir(parents=True, exist_ok=True)
    (private / key).write_text(json.dumps({"scores": {d: 2 for d in DOMAINS}}), encoding="utf-8")
    (private / "signoffs" / f"{sid}.json").write_text(json.dumps(
        {"fields": {d: {"score": 2 + offset, "note": "A private evidence note"} for d in DOMAINS}}), encoding="utf-8")
    log.append({"kind": "subject", "subject_uri": uri, "at": at,
                "payload": {"subject_kind": "exercise",
                            "attrs": {"reference_key": key, "recording_ref": "recordings/secret.mp4"}}})
    log.append({"kind": "calibration", "subject_uri": observer, "at": at,
                "payload": {"exercise": uri, "observer": observer, "signoff_id": sid, "passed": passed,
                            "within_one_share": within, "exact_share": exact}})
    return sid


def test_never_scored_gives_nothing(tmp_path):
    log = []
    exercise(tmp_path, log, 1, A, 1)
    assert calibration.observer_detail(tmp_path, log, B, DOMAINS, TODAY) is None


def test_detail_averages_exercises_and_keeps_only_this_observer(tmp_path):
    log = []
    exercise(tmp_path, log, 1, A, 1, at="2026-08-01T09:00:00+00:00")
    exercise(tmp_path, log, 2, A, 0, passed=False, within=0.8, exact=0.4, at="2026-09-01T09:00:00+00:00")
    exercise(tmp_path, log, 3, B, -1)
    found = calibration.observer_detail(tmp_path, log, A, DOMAINS, TODAY)
    assert found["bias"] == {d: 0.5 for d in sorted(DOMAINS)}
    assert found["counted"] == 2
    assert [e["passed"] for e in found["exercises"]] == [True, False]
    assert found["last_passed"] == "2026-08-01"
    assert found["renew_by"] == "2027-02-01"


def test_a_sign_off_or_reference_gone_leaves_the_agreement_and_counts_fewer(tmp_path):
    log = []
    gone = exercise(tmp_path, log, 1, A, 1, at="2026-08-01T09:00:00+00:00")
    exercise(tmp_path, log, 2, A, -1, at="2026-09-01T09:00:00+00:00")
    (tmp_path / "signoffs" / f"{gone}.json").unlink()
    found = calibration.observer_detail(tmp_path, log, A, DOMAINS, TODAY)
    assert found["counted"] == 1 and len(found["exercises"]) == 2
    assert found["bias"][DOMAINS[0]] == -1


def test_detail_covers_the_last_six_results_only(tmp_path):
    log = []
    for n in range(1, 8):
        exercise(tmp_path, log, n, A, 1 if n == 1 else 0, at=f"2026-0{n + 1}-01T09:00:00+00:00")
    found = calibration.observer_detail(tmp_path, log, A, DOMAINS, TODAY)
    assert len(found["exercises"]) == 6 and found["exercises"][0]["at"] == "2026-03-01"
    assert set(found["bias"].values()) == {0.0}, "the first exercise is out of the window"


@pytest.mark.parametrize("role, viewer, allowed", [
    ("instructor", A, True), ("instructor", B, False), ("head-of-training", None, True), ("coordinator", None, False)])
def test_only_the_observer_and_the_head_may_open_it(role, viewer, allowed):
    model = {"as_of": "x", "instructor": A, "calibration": {"bias": {"a": 1.0}}}
    if allowed:
        assert surfaces.project(model, "my-record", role, viewer)["calibration"]["bias"] == {"a": 1.0}
    else:
        with pytest.raises(surfaces.AudienceError):
            surfaces.project(model, "my-record", role, viewer)


def test_a_generated_observer_still_passes_with_a_lean_of_their_own():
    reference = {d: 2 for d in DOMAINS}
    rules_doc = load_standards()["rules"]
    seen = set()
    for n in range(40):
        for who in (A, B):
            scores = devsign.like_a_person(reference, f"tm:exercise/{n}", who)
            assert rules.calibration_pass(scores, reference, rules_doc).ok
            seen.add(tuple(scores.values()))
    assert len(seen) > 2
    assert devsign.like_a_person(None, "tm:exercise/1", A) is None
    assert devsign.like_a_person({d: 4 for d in DOMAINS}, "x", A) == devsign.like_a_person({d: 4 for d in DOMAINS}, "x", A)
    assert all(1 <= s <= 4 for s in devsign.like_a_person({d: 4 for d in DOMAINS}, "tm:exercise/2", A).values())
