from datetime import date

from teachermodel.rules import (  # noqa: I001
    _other_major,
    Clearance, DryRun, Observation, Outcome, audit_sample, bench_ready, calibration_pass,
    clearance_check, coaching_overdue, quality_triggers, staffing_check,
)

ENG, MOD = "tm:instructor/eng-1", "sl:unit/example-agent-loop@1"
A, B, C, D = (f"tm:instructor/{x}" for x in ("obs-a", "obs-b", "coach-c", "obs-d"))


def scores(domains, value=3, **override):
    s = {d: value for d in domains}
    s.update({k.replace("_", "-"): v for k, v in override.items()})
    return s


def obs(i, observer, domains, at=date(2026, 10, 1), length="full", lead=True, **override):
    return Observation(f"o{i}", ENG, MOD, observer, at, length, lead, scores(domains, **override))


DRY = [DryRun(ENG, MOD, "remote", True, date(2026, 9, 20))]


def check(observations, calibrations, rules, domains, coaches=frozenset({C}), dry=DRY):
    return clearance_check(ENG, MOD, "remote", observations, dry, calibrations, set(coaches), domains, rules)


def test_one_observer_twice_is_not_enough(rules, domains, calibrations):
    v = check([obs(1, A, domains), obs(2, A, domains)], calibrations, rules, domains)
    assert not v.ok and any("distinct" in r for r in v.reasons)


def test_two_observers_with_short_observation_clears(rules, domains, calibrations):
    v = check([obs(1, A, domains), obs(2, B, domains, length="short", lead=False)], calibrations, rules, domains)
    assert v.ok, v.reasons


def test_coach_counts_as_one_observer_at_most(rules, domains, calibrations):
    coaches = {A, C}
    v = check([obs(1, A, domains), obs(2, C, domains)], calibrations, rules, domains, coaches=coaches)
    assert not v.ok
    v = check([obs(1, B, domains), obs(2, C, domains)], calibrations, rules, domains, coaches=coaches)
    assert v.ok, v.reasons


def test_lapsed_calibration_does_not_count(rules, domains, calibrations):
    v = check([obs(1, A, domains), obs(2, D, domains)], calibrations, rules, domains)
    assert not v.ok


def test_needs_full_lead_observation(rules, domains, calibrations):
    v = check([obs(1, A, domains, length="short"), obs(2, B, domains, lead=False)], calibrations, rules, domains)
    assert not v.ok and any("full observation" in r for r in v.reasons)


def test_domain_average_and_overall_mean(rules, domains, calibrations):
    low = check([obs(1, A, domains, prior_knowledge=1), obs(2, B, domains, prior_knowledge=2)],
                calibrations, rules, domains)
    assert not low.ok and any("prior-knowledge" in r for r in low.reasons)
    mean_low = check([obs(1, A, domains, value=2), obs(2, B, domains, value=3)], calibrations, rules, domains)
    assert not mean_low.ok and any("overall mean" in r for r in mean_low.reasons)


def test_needs_passed_dry_run_for_mode(rules, domains, calibrations):
    v = check([obs(1, A, domains), obs(2, B, domains)], calibrations, rules, domains,
              dry=[DryRun(ENG, MOD, "in-person", True, date(2026, 9, 20))])
    assert not v.ok and any("dry-run" in r for r in v.reasons)


def test_calibration_thresholds(rules):
    ref = {f"i{n}": 3 for n in range(10)}
    good = dict(ref, i0=4, i1=2, i2=4)            # 100% within one, 70% exact
    assert calibration_pass(good, ref, rules).ok
    loose = dict(ref, i0=1)                       # 90% within one, 90% exact
    assert calibration_pass(loose, ref, rules).ok
    bad = dict(ref, i0=1, i1=1)                   # 80% within one
    assert not calibration_pass(bad, ref, rules).ok


def test_audit_sample_is_deterministic_with_minimum(rules, domains):
    many = [obs(n, A, domains) for n in range(30)] + [obs(100 + n, B, domains) for n in range(3)]
    first = audit_sample(many, "2026Q4", rules)
    assert first == audit_sample(many, "2026Q4", rules)
    picked_a = [i for i in first if int(i[1:]) < 100]
    picked_b = [i for i in first if int(i[1:]) >= 100]
    assert len(picked_a) == 3 and len(picked_b) == 2
    assert first != audit_sample(many, "2027Q1", rules)


def test_domain_one_needs_second_observer(rules, domains):
    today = date(2026, 10, 20)
    single = [obs(1, A, domains, prior_knowledge=1)]
    assert quality_triggers(ENG, [], single, today, rules) == []
    double = single + [obs(2, B, domains, prior_knowledge=1)]
    assert any("prior-knowledge" in t for t in quality_triggers(ENG, [], double, today, rules))


def test_score_trigger_ignores_small_deliveries(rules):
    def out(i, n, score):
        return Outcome(f"d{i}", ENG, date(2026, 9, i), n, score, 75.0)
    drops = [out(1, 20, 60), out(2, 20, 62)]
    assert quality_triggers(ENG, drops, [], date(2026, 10, 1), rules)
    small = [out(1, 20, 60), out(2, 8, 50)]
    assert quality_triggers(ENG, small, [], date(2026, 10, 1), rules) == []


def test_feedback_trigger_ignores_deliveries_below_the_minimum_learner_count(rules):
    # decision 0015: a metric below the minimum learner count never triggers, feedback included
    minimum = rules["quality"]["min_learners_for_metric"]

    def out(i, n):
        return Outcome(f"d{i}", ENG, date(2026, 9, i), n, 75.0, 75.0, feedback=1.0, feedback_median=4.2)
    assert quality_triggers(ENG, [out(1, minimum), out(2, minimum)], [], date(2026, 10, 1), rules) == [
        "feedback below median on 2 deliveries"]
    assert quality_triggers(ENG, [out(1, minimum), out(2, minimum - 1)], [], date(2026, 10, 1), rules) == []
    assert quality_triggers(ENG, [out(1, minimum - 1), out(2, minimum - 1)], [], date(2026, 10, 1), rules) == []


def test_coaching_cadence(rules):
    today = date(2026, 10, 23)
    assert coaching_overdue(None, False, today, rules)
    assert not coaching_overdue(date(2026, 8, 1), False, today, rules)
    assert coaching_overdue(date(2026, 8, 1), True, today, rules)


def test_bench_needs_two_current_observers_and_pack(rules, domains):
    today = date(2026, 10, 23)
    one = [obs(1, A, domains)]
    assert not bench_ready(ENG, one, True, today, rules).ok
    two = one + [obs(2, B, domains)]
    assert bench_ready(ENG, two, True, today, rules).ok
    assert not bench_ready(ENG, two, False, today, rules).ok


def test_staffing_check(rules):
    clr = Clearance("tm:clearance/c1", ENG, MOD, ("remote",), "cleared", date(2026, 1, 15), date(2027, 1, 15))
    assert staffing_check([], ENG, MOD, "remote", date(2026, 10, 23), rules)["verdict"] == "block"
    assert staffing_check([clr], ENG, MOD, "in-person", date(2026, 10, 23), rules)["verdict"] == "block"
    assert staffing_check([clr], ENG, MOD, "remote", date(2026, 10, 23), rules)["verdict"] == "ok"
    assert staffing_check([clr], ENG, MOD, "remote", date(2027, 1, 1), rules)["verdict"] == "warn"
    cond = Clearance("tm:clearance/c2", ENG, MOD, ("remote",), "cleared_with_conditions",
                     date(2026, 9, 1), date(2027, 9, 1), recheck=date(2026, 10, 1))
    assert staffing_check([cond], ENG, MOD, "remote", date(2026, 10, 23), rules)["verdict"] == "block"


# --- integration-review fixes: framework major versions, renewal evidence, recheck warning, agreement --------------


def test_a_clearance_judged_against_another_framework_major_blocks(rules):
    assert rules["framework_version"] == "1.1.0"
    old = Clearance("tm:clearance/c3", ENG, MOD, ("remote",), "cleared", date(2026, 1, 15), date(2027, 1, 15),
                    framework_version="2.4.0")
    res = staffing_check([old], ENG, MOD, "remote", date(2026, 10, 23), rules)
    assert res["verdict"] == "block" and any("framework" in r and "2.4.0" in r for r in res["reasons"])
    minor = Clearance("tm:clearance/c4", ENG, MOD, ("remote",), "cleared", date(2026, 1, 15), date(2027, 1, 15),
                      framework_version="0.9.1")  # the same major (0): still valid
    assert staffing_check([minor], ENG, MOD, "remote", date(2026, 10, 23), rules)["verdict"] == "ok"


def test_staffing_warns_ahead_of_a_conditional_recheck(rules):
    cond = Clearance("tm:clearance/c5", ENG, MOD, ("remote",), "cleared_with_conditions",
                     date(2026, 9, 1), date(2027, 9, 1), recheck=date(2026, 12, 1))
    assert staffing_check([cond], ENG, MOD, "remote", date(2026, 10, 31), rules)["verdict"] == "ok"  # 31 days
    warn = staffing_check([cond], ENG, MOD, "remote", date(2026, 11, 1), rules)  # 30 days: the warn window
    assert warn["verdict"] == "warn" and warn["reasons"] == ["conditional clearance recheck due in 30 days"]
    assert warn["clearance"] == "tm:clearance/c5"
    plain = Clearance("tm:clearance/c6", ENG, MOD, ("remote",), "cleared", date(2026, 9, 1), date(2027, 6, 1))
    assert staffing_check([cond, plain], ENG, MOD, "remote", date(2026, 11, 1), rules) == {
        "verdict": "ok", "reasons": [], "clearance": "tm:clearance/c6"}  # a clearance with nothing pending wins


def test_observations_scored_against_another_rubric_major_do_not_count(rules, domains, calibrations):
    new = [obs(1, A, domains), obs(2, B, domains)]
    assert check(new, calibrations, rules, domains).ok
    old = [Observation("o1", ENG, MOD, A, date(2026, 10, 1), "full", True, scores(domains), rubric_version="2.0.0"),
           obs(2, B, domains)]
    v = check(old, calibrations, rules, domains)
    assert not v.ok and v.detail["observations"] == ["o2"]


def test_a_renewal_counts_only_observations_after_the_date_it_is_given(rules, domains, calibrations):
    two = [obs(1, A, domains, at=date(2026, 9, 10)), obs(2, B, domains, at=date(2026, 10, 1))]
    v = clearance_check(ENG, MOD, "remote", two, DRY, calibrations, set(), domains, rules, since=date(2026, 9, 10))
    assert not v.ok and v.detail["observations"] == ["o2"]  # on the day itself is not after it
    assert clearance_check(ENG, MOD, "remote", two, DRY, calibrations, set(), domains, rules,
                           since=date(2026, 9, 9)).ok


def test_the_verdict_names_the_dry_runs_that_counted(rules, domains, calibrations):
    v = check([obs(1, A, domains), obs(2, B, domains)], calibrations, rules, domains)
    assert v.detail["dry_runs"] == ["2026-09-20"]


def test_inter_observer_agreement_is_each_observer_against_the_others():
    from teachermodel.rules import inter_observer_agreement

    a = {"i0": 3, "i1": 3, "i2": 3, "i3": 3, "i4": 3}
    b = {"i0": 3, "i1": 3, "i2": 4, "i3": 1, "i4": 3}   # with a: within one 4/5, exact 3/5
    c = {"i0": 3, "i1": 3, "i2": 3, "i3": 3, "i4": 3}   # with a: 5/5 and 5/5; with b: 4/5 and 3/5
    got = inter_observer_agreement({"a": a, "b": b, "c": c})
    assert got["a"] == {"within_one_share": 0.9, "exact_share": 0.8}
    assert got["b"] == {"within_one_share": 0.8, "exact_share": 0.6}
    assert inter_observer_agreement({"a": a}) == {}


def test_observations_in_any_mode_count_but_the_dry_run_must_match(rules, domains, calibrations):
    # Decision 0013: in-person observations count toward a remote clearance; the dry run must be remote.
    seen = [Observation(f"o{i}", ENG, MOD, who, date(2026, 10, 1), "full", True, scores(domains), mode="in-person")
            for i, who in ((1, A), (2, B))]
    assert check(seen, calibrations, rules, domains).ok
    in_person_dry = [DryRun(ENG, MOD, "in-person", True, date(2026, 9, 20))]
    v = check(seen, calibrations, rules, domains, dry=in_person_dry)
    assert not v.ok and any("dry-run" in r for r in v.reasons)


# --- a scope-free validity (integration review finding 8) ---------------------------------------------------------------


def test_clearance_valid_ignores_the_scope_and_keeps_every_other_condition(rules):
    from teachermodel.rules import Scope, clearance_valid

    scoped = Clearance("tm:clearance/c7", ENG, MOD, ("remote",), "cleared", date(2026, 1, 15), date(2027, 1, 15),
                       scope=Scope(partner="tm:org/example-partner", regions=("DE",)))
    assert clearance_valid(scoped, date(2026, 10, 23), rules)
    assert staffing_check([scoped], ENG, MOD, "remote", date(2026, 10, 23), rules)["verdict"] == "block"  # no partner named
    assert clearance_valid(scoped, date(2026, 1, 15), rules) and not clearance_valid(scoped, date(2026, 1, 14), rules)
    assert not clearance_valid(scoped, date(2027, 1, 15), rules)  # the expiry day is not covered
    cond = Clearance("tm:clearance/c8", ENG, MOD, ("remote",), "cleared_with_conditions", date(2026, 9, 1),
                     date(2027, 9, 1), recheck=date(2026, 12, 1))
    assert clearance_valid(cond, date(2026, 12, 1), rules) and not clearance_valid(cond, date(2026, 12, 2), rules)
    for outcome in ("not_yet", "expired", "revoked"):
        assert not clearance_valid(Clearance("tm:clearance/c9", ENG, MOD, ("remote",), outcome, date(2026, 1, 15),
                                             date(2027, 1, 15)), date(2026, 10, 23), rules)
    retired = Clearance("tm:clearance/c10", ENG, MOD, ("remote",), "cleared", date(2026, 1, 15), date(2027, 1, 15),
                        framework_version="2.0.0")
    assert not clearance_valid(retired, date(2026, 10, 23), rules)


# --- decision 0023: a promotion that kept the content keeps what was judged against it ---------------------------------


def test_a_compatible_major_stays_in_force_and_only_while_the_rules_declare_it(rules):
    """Edge: 1.1.0 declares major 0 compatible. A 0.x clearance stays in force; without the declaration it would expire;
    a different major (2.x) still expires whatever the declaration lists."""
    assert rules["framework_version"] == "1.1.0" and rules["framework_compatible_majors"] == ["0"]
    assert not _other_major("0.2.0", rules)
    assert _other_major("0.2.0", {**rules, "framework_compatible_majors": []})
    assert _other_major("0.2.0", {k: v for k, v in rules.items() if k != "framework_compatible_majors"})
    assert _other_major("2.0.0", rules)
    assert not _other_major("1.0.4", rules)  # the same major
