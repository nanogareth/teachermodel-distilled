"""Deterministic rules over the record (spec v0.2, Rules and thresholds).

No model sits in this path. Every function is pure: inputs in, verdict out. Thresholds come from
standards/rules.yaml so that changing a rule is a reviewed commit.
"""

from __future__ import annotations

import calendar
import hashlib
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean
from typing import Any, Iterable

Rules = dict[str, Any]


@dataclass(frozen=True)
class Observation:
    id: str
    instructor: str
    unit: str
    observer: str
    at: date
    length: str  # "full" | "short"
    lead: bool
    scores: dict[str, int]
    mode: str | None = None
    rubric_version: str | None = None  # the framework version of the rubric; None = not known (not checked)


@dataclass(frozen=True)
class DryRun:
    instructor: str
    unit: str
    mode: str
    passed: bool
    at: date


@dataclass(frozen=True)
class Scope:
    """Whom and where a clearance covers (W11, clearance@1 `scope`). A part left None is not limited."""

    partner: str | None = None  # a partner organisation (tm:org/...)
    regions: tuple[str, ...] | None = None  # region codes (IE, US-CA)


@dataclass(frozen=True)
class Clearance:
    id: str
    instructor: str
    unit: str
    modes: tuple[str, ...]
    outcome: str  # cleared | cleared_with_conditions | not_yet | expired | revoked
    issued: date
    expires: date
    recheck: date | None = None
    framework_version: str | None = None  # the framework it was judged against; None = not known (not checked)
    scope: Scope | None = None  # None = unscoped: covers any partner and region


@dataclass(frozen=True)
class Outcome:
    delivery: str
    instructor: str
    at: date
    learners_assessed: int
    score: float
    baseline: float
    feedback: float | None = None
    feedback_median: float | None = None


@dataclass(frozen=True)
class Override:
    """A staffing override (spec Rules): the head of training's decision that one instructor may deliver one unit
    in one mode on one date although the staffing check blocks. `approved` is False for a rejected request.

    An override is bound to the block it overrode (integration review finding 5, decision 0015): `block` holds the reasons
    the check gave when the head decided, and `decided` the day of the decision. It lifts a block only while the check gives
    those reasons exactly, and only when it was decided on or after the instructor's latest bench decision. An override
    with no recorded block lifts nothing (fail closed). `partner` and `region` are part of the occasion (decision 0018): it
    lifts only a request that names the same ones, so an override asked with no partner lifts nothing for a partner's
    delivery."""

    id: str
    instructor: str
    unit: str
    mode: str
    on: date
    approved: bool
    block: tuple[str, ...] | None = None
    decided: date | None = None
    partner: str | None = None  # the occasion's partner and region (decision 0018); None when the request named none
    region: str | None = None


@dataclass
class Verdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def major(version: str) -> str:
    """The major part of a dotted version ("0.2.0" -> "0"). A new major version of the framework expires clearances and
    retires the observations scored against the old rubric (spec v0.2, Clearance expiry; Domain model, Framework)."""
    return str(version).split(".", 1)[0]


def _other_major(version: str | None, rules: Rules) -> bool:
    """True when `version` is known and its major differs from the current framework's (rules.framework_version), unless
    that major is one the rules declare compatible (`framework_compatible_majors`, decision 0023: a promotion that kept the
    content, so what was judged against it stays in force)."""
    current = rules.get("framework_version")
    if version is None or current is None or major(version) == major(current):
        return False
    return major(version) not in set(rules.get("framework_compatible_majors") or ())


def is_calibrated(observer: str, on: date, calibrations: dict[str, list[date]], rules: Rules,
                  lapses: list[date] | None = None) -> bool:
    """An observer is calibrated on a date if a pass precedes it within the renewal period.

    `lapses` are the observer's audit referrals (W6, records.lapses). A referral on D is prospective (decision 0015): from
    D on, only a pass dated after D counts, so the observer is not calibrated from D until their next pass; dates before D
    are judged as if there were no referral. A pass on D itself does not restore the calibration."""
    months = rules["calibration"]["renewal_months"]
    latest = max((d for d in lapses or () if d <= on), default=None)
    return any(p <= on < add_months(p, months) and (latest is None or p > latest)
               for p in calibrations.get(observer, []))


def calibration_pass(scores: dict[str, int], reference: dict[str, int], rules: Rules) -> Verdict:
    items = sorted(reference)
    missing = [i for i in items if i not in scores]
    if missing:
        return Verdict(False, [f"unscored items: {missing}"])
    within = sum(abs(scores[i] - reference[i]) <= 1 for i in items) / len(items)
    exact = sum(scores[i] == reference[i] for i in items) / len(items)
    c = rules["calibration"]
    reasons = []
    if within < c["within_one_point_share"]:
        reasons.append(f"within-one agreement {within:.0%} < {c['within_one_point_share']:.0%}")
    if exact < c["exact_agreement_share"]:
        reasons.append(f"exact agreement {exact:.0%} < {c['exact_agreement_share']:.0%}")
    return Verdict(not reasons, reasons, {"within_one": within, "exact": exact})


def inter_observer_agreement(scores: dict[str, dict[str, int]]) -> dict[str, dict[str, float]]:
    """W5 step 2, agreement against each other: per observer, the share of item scores within one point of, and equal to,
    each other observer's score on the same item, pooled over the other observers. Reported only: calibration_pass
    (against the reference) alone decides pass or fail. Empty with fewer than two observers."""
    out: dict[str, dict[str, float]] = {}
    for who, mine in sorted(scores.items()):
        within = exact = n = 0
        for other, theirs in sorted(scores.items()):
            if other == who:
                continue
            for item in sorted(set(mine) & set(theirs)):
                n += 1
                within += abs(mine[item] - theirs[item]) <= 1
                exact += mine[item] == theirs[item]
        if n:
            out[who] = {"within_one_share": within / n, "exact_share": exact / n}
    return out


def calibration_bias(scored: Iterable[tuple[dict[str, int], dict[str, int]]]) -> dict[str, float]:
    """Per item, the observer's own score minus the reference, averaged over the (scores, reference) pairs that have the
    item. Above 0 scores high, below 0 low. Reported only (decision 0032): calibration_pass alone decides pass or fail."""
    differences: dict[str, list[int]] = {}
    for scores, reference in scored:
        for item in sorted(set(scores) & set(reference)):
            differences.setdefault(item, []).append(scores[item] - reference[item])
    return {item: sum(d) / len(d) for item, d in sorted(differences.items())}


def effective_observers(observers: set[str], coaches: set[str], rules: Rules) -> int:
    """Distinct observers, with the instructor's coaches counting as at most max_coach_observers."""
    cap = rules["clearance"]["max_coach_observers"]
    return len(observers - coaches) + min(len(observers & coaches), cap)


def clearance_check(
    instructor: str,
    unit: str,
    mode: str,
    observations: Iterable[Observation],
    dry_runs: Iterable[DryRun],
    calibrations: dict[str, list[date]],
    coaches: set[str],
    domains: list[str],
    rules: Rules,
    since: date | None = None,
    lapses: dict[str, list[date]] | None = None,
) -> Verdict:
    """W4 evidence check. Two clearers still make the decision; this only says if they may.

    An observation counts when it is the instructor's on the unit, by an observer other than the instructor who was
    calibrated on the observation date (`is_calibrated`, with the observer's audit referrals from `lapses`, observer ->
    dates, which are prospective), scored against a rubric of the current framework major (rules.framework_version; one of
    unknown rubric version is not checked) and, when `since` is given (a renewal: the day the clearance being
    renewed was issued), dated after `since`, so that a renewal rests on new evidence.

    `detail` holds the domain averages, the observers, the ids of the observations that counted and the dates of the
    passed dry runs for the unit and mode."""
    c = rules["clearance"]
    obs = [
        o
        for o in observations
        if o.instructor == instructor
        and o.unit == unit
        and o.observer != instructor
        and is_calibrated(o.observer, o.at, calibrations, rules, (lapses or {}).get(o.observer))
        and not _other_major(o.rubric_version, rules)
        and (since is None or o.at > since)
    ]
    reasons: list[str] = []
    if len(obs) < c["min_observations"]:
        reasons.append(f"{len(obs)} calibrated observations; need {c['min_observations']}")
    observers = {o.observer for o in obs}
    effective = effective_observers(observers, coaches, rules)
    if effective < c["min_distinct_observers"]:
        reasons.append(
            f"{effective} distinct calibrated observers (coach counted at most "
            f"{c['max_coach_observers']}); need {c['min_distinct_observers']}"
        )
    if c.get("require_full_lead_observation") and not any(o.length == "full" and o.lead for o in obs):
        reasons.append("no full observation of a lead delivery")
    averages: dict[str, float] = {}
    for d in domains:
        vals = [o.scores[d] for o in obs if d in o.scores]
        if not vals:
            reasons.append(f"domain {d} not scored")
            continue
        averages[d] = mean(vals)
        if averages[d] < c["min_domain_average"]:
            reasons.append(f"domain {d} averages {averages[d]:.2f} < {c['min_domain_average']}")
    if averages and len(averages) == len(domains):
        overall = mean(averages.values())
        if overall < c["min_overall_mean"]:
            reasons.append(f"overall mean {overall:.2f} < {c['min_overall_mean']}")
    runs = sorted(r.at.isoformat() for r in dry_runs
                  if r.instructor == instructor and r.unit == unit and r.mode == mode and r.passed)
    if not runs:
        reasons.append(f"no passed dry-run for {unit} in {mode} mode")
    return Verdict(not reasons, reasons,
                   {"averages": averages, "observers": sorted(observers), "observations": sorted(o.id for o in obs),
                    "dry_runs": runs})


def expiry_date(issued: date, rules: Rules) -> date:
    return add_months(issued, rules["clearance"]["expiry_months"])


def _rank(quarter: str, obs_id: str) -> str:
    return hashlib.sha256(f"{quarter}:{obs_id}".encode()).hexdigest()


def audit_sample(observations: Iterable[Observation], quarter: str, rules: Rules) -> list[str]:
    """W6: deterministic per-observer sample for double-scoring (same inputs, same sample)."""
    a = rules["audit"]
    by_observer: dict[str, list[Observation]] = {}
    for o in observations:
        by_observer.setdefault(o.observer, []).append(o)
    picked: list[str] = []
    for obs in by_observer.values():
        n = min(len(obs), max(a["min_per_observer"], math.ceil(a["sample_rate"] * len(obs))))
        picked += [o.id for o in sorted(obs, key=lambda o: _rank(quarter, o.id))[:n]]
    return sorted(picked)


def quality_triggers(
    instructor: str,
    outcomes: Iterable[Outcome],
    observations: Iterable[Observation],
    today: date,
    rules: Rules,
) -> list[str]:
    """W8. Triggers intensify coaching; none of them alone may cause a bench decision.

    A delivery with fewer than `quality.min_learners_for_metric` learners assessed is read by no outcome metric, the
    feedback trigger included (decision 0015)."""
    q, f = rules["quality"], rules["feedback"]
    mine = sorted((o for o in outcomes if o.instructor == instructor), key=lambda o: o.at)
    triggers: list[str] = []

    measured = [o for o in mine if o.learners_assessed >= q["min_learners_for_metric"]]
    run = measured[-q["consecutive_deliveries"]:]
    if len(run) == q["consecutive_deliveries"] and all(o.baseline - o.score >= q["score_drop_points"] for o in run):
        triggers.append(f"performance-task score {q['score_drop_points']}+ below baseline on {len(run)} deliveries")

    rated = [o for o in measured if o.feedback is not None and o.feedback_median is not None]
    frun = rated[-f["consecutive_below_median"]:]
    if len(frun) == f["consecutive_below_median"] and all(o.feedback < o.feedback_median for o in frun):
        triggers.append(f"feedback below median on {len(frun)} deliveries")

    since = today - timedelta(days=q["confirmation_window_days"])
    need = 2 if q["domain_one_needs_second_observer"] else 1
    ones: dict[str, set[str]] = {}
    for o in observations:
        if o.instructor == instructor and since <= o.at <= today:
            for d, s in o.scores.items():
                if s == 1:
                    ones.setdefault(d, set()).add(o.observer)
    for d, who in sorted(ones.items()):
        if len(who) >= need:
            triggers.append(f"domain {d} scored 1 by {len(who)} observers")
    return triggers


def coaching_overdue(last_closed: date | None, triggered: bool, today: date, rules: Rules) -> bool:
    c = rules["coaching"]
    days = c["triggered_cycle_days"] if triggered else c["standard_cycle_days"]
    return last_closed is None or (today - last_closed).days > days


def bench_ready(
    instructor: str,
    observations: Iterable[Observation],
    has_evidence_pack: bool,
    today: date,
    rules: Rules,
) -> Verdict:
    b = rules["bench"]
    since = today - timedelta(days=b["current_window_days"])
    observers = {o.observer for o in observations if o.instructor == instructor and since <= o.at <= today}
    reasons = []
    if len(observers) < b["min_distinct_observers"]:
        reasons.append(f"{len(observers)} current observers; need {b['min_distinct_observers']}")
    if b.get("require_evidence_pack") and not has_evidence_pack:
        reasons.append("no evidence pack")
    return Verdict(not reasons, reasons)


def scope_covers(scope: Scope | None, partner: str | None, region: str | None) -> bool:
    """W11: an unscoped clearance covers any request. A scoped one covers a request only when the request names the
    partner the scope limits it to and a region among the scope's regions; a part the scope leaves out is not checked, and
    a request that does not name a part the scope limits is not covered (the scope is not guessed at)."""
    if scope is None:
        return True
    if scope.partner is not None and partner != scope.partner:
        return False
    return scope.regions is None or region in scope.regions


def _scope_text(scope: Scope) -> str:
    parts = []
    if scope.partner is not None:
        parts.append(f"partner {scope.partner}")
    if scope.regions is not None:
        parts.append("regions " + ", ".join(scope.regions))
    return " and ".join(parts)


def clearance_valid(c: Clearance, on: date, rules: Rules) -> bool:
    """A clearance in force on `on`, whatever its scope (integration review finding 8): cleared, or cleared with conditions
    whose recheck has not passed; `on` in [issued, expires); judged against the current framework major (a new major
    version expires it). The staffing check adds the unit, the mode, the scope and the bench decisions; the readers that ask
    "does this instructor hold a clearance" (a clearer within their modules, a level proposal, a W12 author, the gap list's
    pool) need this alone, so that a partner's scoped clearance is not mistaken for none."""
    return _in_force(c, on) and not _other_major(c.framework_version, rules)


def _in_force(c: Clearance, on: date) -> bool:
    """Cleared, or cleared with conditions whose recheck has not passed, and `on` in [issued, expires)."""
    if c.outcome not in ("cleared", "cleared_with_conditions") or not (c.issued <= on < c.expires):
        return False
    return c.outcome != "cleared_with_conditions" or (c.recheck is not None and on <= c.recheck)


BENCH_BLOCKS = {
    "exit": "bench decision: exit",
    "return-to-co-teaching": "bench decision: returned to co-teaching",
}  # the bench decisions that stop staffing until the instructor is cleared again (decision 0015)


def staffing_check(
    clearances: Iterable[Clearance], instructor: str, unit: str, mode: str, on: date, rules: Rules,
    partner: str | None = None, region: str | None = None, bench: tuple[str, date] | None = None,
    overrides: Iterable[Override] = (), bench_decided: date | None = None,
) -> dict[str, Any]:
    """Staffing-check contract response (contracts/staffing-check.schema.json#/$defs/response).

    A clearance is valid on `on` when it covers the unit and mode, is cleared (or cleared with conditions and its recheck
    has not passed), `on` falls in [issued, expires), it was judged against the current framework major (a new major
    version expires it; spec v0.2, Clearance expiry) and its scope covers the request (`scope_covers`: `partner` and `region`
    are the request's optional partner organisation and delivery region; W11). Without one: block, and the reasons name any
    clearance a framework change retired and any scoped clearance that does not cover the request.

    `bench` is the instructor's latest blocking bench decision as (decision, day decided): the latest exit or return to
    co-teaching (`BENCH_BLOCKS`) decided on or before `on`, whatever followed it (`records.bench_blocks.latest_blocking`; a
    later renew or convert does not lift it, integration review finding 2). It stops staffing: only a clearance issued after
    the day of the decision counts, and the reasons say "bench decision: exit" or "bench decision: returned to co-teaching".
    Any other decision, or one decided after `on`, changes nothing.

    `overrides` are the staffing overrides on record. An approved one for exactly this instructor, unit, mode, date, partner
    and region (decision 0018) turns
    a block into ok (never a warn into anything) while the block's reasons are exactly those it was decided on
    (`Override.block`) and it was decided on or after `bench_decided`, the day of the instructor's latest bench decision of
    any kind on or before `on` (finding 5). The reasons then start with "override <id>" and keep what it overrode, each as
    "overridden: <reason>". A rejected one, one bound to other reasons, one decided before that bench decision, or one for
    another instructor, unit, mode or date, changes nothing.

    These are the detailed reasons, for the training function. What delivery scheduling receives is reduced to a fixed
    vocabulary by `staffing.outbound` (decision 0005, finding 12).

    Warn when every valid
    clearance expires, or reaches its conditional recheck, within staffing.warn_expiry_days (the clearance named is then the
    one that lasts longest); otherwise ok."""
    valid, retired, out_of_scope = [], [], []
    for c in clearances:
        if c.instructor != instructor or c.unit != unit or mode not in c.modes:
            continue
        if not _in_force(c, on):
            continue
        if _other_major(c.framework_version, rules):
            retired.append(c)
            continue
        if not scope_covers(c.scope, partner, region):
            out_of_scope.append(c)
            continue
        valid.append(c)
    benched = BENCH_BLOCKS.get(bench[0]) if bench is not None and bench[1] <= on else None
    stale = [c for c in valid if benched and c.issued <= bench[1]]
    valid = [c for c in valid if c not in stale]
    if not valid:
        reasons = [benched] if benched else []
        if not stale:
            reasons.append(f"no valid clearance for {unit} in {mode} mode on {on}")
        reasons += [f"clearance {c.id} was judged against framework {c.framework_version}; the current framework is "
                    f"{rules['framework_version']} (a new major version expires it)" for c in retired]
        reasons += [f"clearance {c.id} is limited to {_scope_text(c.scope)}; the request names "
                    f"{'partner ' + partner if partner else 'no partner'} and "
                    f"{'region ' + region if region else 'no region'} (scope)" for c in out_of_scope]
        granted = sorted(o.id for o in overrides
                         if o.approved and (o.instructor, o.unit, o.mode, o.on, o.partner, o.region)
                         == (instructor, unit, mode, on, partner, region)
                         and o.block is not None and list(o.block) == reasons
                         and (bench_decided is None or (o.decided is not None and o.decided >= bench_decided)))
        if granted:
            return {"verdict": "ok", "reasons": [f"override {granted[0]}", *[f"overridden: {r}" for r in reasons]]}
        return {"verdict": "block", "reasons": reasons}
    window = rules["staffing"]["warn_expiry_days"]

    def warnings(c: Clearance) -> list[str]:
        out = []
        if (c.expires - on).days <= window:
            out.append(f"clearance expires in {(c.expires - on).days} days")
        if c.outcome == "cleared_with_conditions" and c.recheck is not None and (c.recheck - on).days <= window:
            out.append(f"conditional clearance recheck due in {(c.recheck - on).days} days")
        return out

    clean = [c for c in valid if not warnings(c)]
    if clean:
        return {"verdict": "ok", "reasons": [], "clearance": max(clean, key=lambda c: c.expires).id}
    best = max(valid, key=lambda c: c.expires)
    return {"verdict": "warn", "reasons": warnings(best), "clearance": best.id}
