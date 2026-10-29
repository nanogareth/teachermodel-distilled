"""W6 observation audit (standards/workflows/audit.yaml, flows/audit.py, records/audits.py).

draw-sample (auto, programme, refresh) opens, on the first run after a quarter closed, one `sample` subject per observation that
`rules.audit_sample` picks for that quarter (tests/test_audit_quarter.py covers the timing), with a second observer chosen by hash rank from the calibrated clearers (never the first observer, the
instructor or the instructor's coaches) -> second-score (the second observer scores from the recording, blind to the
first) -> audit-result (auto, per sample) writes the `audit` event, and a `check` that refers the first observer back to
W5 when the agreement falls below the calibration thresholds. Fictional people only (the example roster).
"""

import dataclasses
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from clearer_helpers import calibrate, set_level
from ingest_helpers import email_of, ingest, signoff, signoff_events
from test_observation import C5, DOMAINS, INSTRUCTOR, K7, R8, T0, sign, store

from teachermodel import app, events, flows, records, rules
from teachermodel import pages as pagegen
from teachermodel.flows import audit
from teachermodel.standards import ROOT, check_standards, load_standards
from teachermodel.workflow import PROGRAMME

assert len(DOMAINS) == 5, "these tests are written for five framework domains (3 of 5 = the 0.6 exact edge)"

Q4 = "2026Q4"
NOW = datetime(2027, 1, 4, 8, 0, tzinfo=timezone.utc)  # the first run after 2026Q4 closed, inside every calibration renewal period
STEP_DRAW, STEP_SCORE, STEP_RESULT = "tm:step/draw-sample", "tm:step/second-score", "tm:step/audit-result"
ALL = [INSTRUCTOR, K7, C5, R8]
OBSERVERS = [K7, C5, R8]
STD = load_standards()


def log(private):
    return app.read_events(private)


def of_kind(private, kind):
    return [e for e in log(private) if e["kind"] == kind]


def samples(private):
    return sorted((e for e in of_kind(private, "subject") if e["payload"]["subject_kind"] == "sample"),
                  key=lambda e: e["subject_uri"])


def obs_event(n, observer, instructor, day, scores=3, **extra):
    payload = {"instructor": instructor, "unit": "sl:unit/example-agent-loop@1", "observer": observer, "length": "full",
               "lead": True, "mode": "remote", "rubric_version": "0.2.0",
               "scores": scores if isinstance(scores, dict) else {d: scores for d in DOMAINS}, **extra}
    return events.make_event("observation", instructor, observer, payload,
                             id=hashlib.sha256(f"audit-test-{n}".encode()).hexdigest()[:32], at=f"{day}T00:00:00+00:00")


def add(private, *evs):
    for e in evs:
        events.append(private / app.EVENT_LOG, e)


def many(private, q4=24, q3=6):
    """`q4` observations dated in 2026Q4 and `q3` in 2026Q3, spread over three observers and four instructors."""
    out = []
    for n in range(q4 + q3):
        observer = OBSERVERS[n % 3]
        instructor = [i for i in ALL if i != observer][(n // 3) % 3]
        day = date(2026, 10, 1) + timedelta(days=n % 25) if n < q4 else date(2026, 9, 1) + timedelta(days=n)
        out.append(obs_event(n, observer, instructor, day.isoformat()))
    add(private, *out)
    return out


def coach_row(private, coach, *coached):
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    slug = coach.split("/", 1)[1]
    doc["people"].append({"person": f"tm:person/coach-{slug}", "name": f"Coach {slug}", "email": f"coach.{slug}@example.com",
                          "roles": ["coach"], "instructor": coach, "coaches": list(coached)})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def run(private, now=NOW):
    return app.do_run(private, now=now)


def one_sample(private, scores=3, observer=K7, instructor=INSTRUCTOR, day="2026-10-20", now=NOW, **extra):
    """One observation, the run that draws it; returns (sample URI, its `subject` event)."""
    add(private, obs_event(1000, observer, instructor, day, scores, **extra))
    run(private, now)
    (found,) = samples(private)
    return found["subject_uri"], found


def second_fields(values=None):
    values = values or [3] * len(DOMAINS)
    return {d: {"score": s, "note": "fictional second-scoring note"} for d, s in zip(DOMAINS, values)}


def score_second(private, sample, values, at="2027-01-05T09:00:00+00:00"):
    second = next(s for s in samples(private) if s["subject_uri"] == sample)["payload"]["attrs"]["second_observer"]
    return sign(private, STEP_SCORE, sample, second, second_fields(values), at=at)


def audits_of(private):
    return of_kind(private, "audit")


# --- the workflow file --------------------------------------------------------------------------------------------


def wf():
    return {w["id"]: w for w in STD["workflows"]["workflows"]}["tm:workflow/audit"]


def test_the_workflow_file_defines_the_three_steps():
    steps = {s["id"]: s for s in wf()["steps"]}
    assert set(steps) == {STEP_DRAW, STEP_SCORE, STEP_RESULT}
    assert {sid: (s["type"], s["role"], s["subject"]) for sid, s in steps.items()} == {
        STEP_DRAW: ("auto", "head-of-training", "programme"),
        STEP_SCORE: ("human", "clearer", "sample"),
        STEP_RESULT: ("auto", "head-of-training", "sample"),
    }
    assert steps[STEP_SCORE]["page"] == "approve" and steps[STEP_RESULT]["needs"] == [STEP_SCORE]
    assert set(wf()["event_kinds"]) >= {"step", "signoff", "subject", "audit", "check"}
    # the window to second-score is an operational default, labelled as one (decision 0002)
    assert steps[STEP_SCORE]["due"] == {"days": 14, "basis": "operational default"}


def test_standards_validate_with_the_audit_file():
    assert check_standards(ROOT) == []


def test_every_step_has_its_runner_or_builder():
    assert flows.AUTO_STEPS[STEP_DRAW].per == "programme" and flows.AUTO_STEPS[STEP_DRAW].refresh
    assert flows.AUTO_STEPS[STEP_RESULT].per == "sample"
    assert STEP_SCORE in flows.PAGE_SPECS and STEP_SCORE in flows.CONTENT_CHECKS


@pytest.mark.parametrize("day,quarter", [
    (date(2026, 1, 1), "2026Q1"), (date(2026, 3, 31), "2026Q1"), (date(2026, 4, 1), "2026Q2"), (date(2026, 6, 30), "2026Q2"),
    (date(2026, 7, 1), "2026Q3"), (date(2026, 9, 30), "2026Q3"), (date(2026, 10, 1), "2026Q4"), (date(2026, 12, 31), "2026Q4")])
def test_the_quarter_id_is_the_calendar_quarter_in_the_subject_format(day, quarter):
    assert audit.quarter_id(day) == quarter


# --- choosing the second observer (pure) ---------------------------------------------------------------------------

POOL = [f"tm:instructor/o{n}" for n in range(8)]
SAMPLE = "tm:sample/2026Q4--0123456789abcdef"


def test_the_second_observer_is_hash_ranked_and_independent_of_the_pool_order():
    a = audit.choose_second_observer(SAMPLE, POOL[0], POOL[1], POOL, set())
    assert a == audit.choose_second_observer(SAMPLE, POOL[0], POOL[1], list(reversed(POOL)), set())
    ranked = sorted(set(POOL) - {POOL[0], POOL[1]}, key=lambda o: (audit.rank(SAMPLE, o), o))
    assert a == ranked[0]
    assert len({audit.choose_second_observer(f"tm:sample/2026Q4--{n:016x}", POOL[0], POOL[1], POOL, set())
                for n in range(40)}) > 1  # different samples rotate the pool


def test_the_second_observer_is_never_the_first_observer_the_instructor_or_a_coach_of_the_instructor():
    pool = POOL[:4]
    for n in range(30):
        sample = f"tm:sample/2026Q4--{n:016x}"
        got = audit.choose_second_observer(sample, pool[0], pool[1], pool, {pool[2]})
        assert got == pool[3]  # the only one left
    assert audit.choose_second_observer(SAMPLE, pool[0], pool[1], pool, {pool[2], pool[3]}) is None
    assert audit.choose_second_observer(SAMPLE, pool[0], pool[1], [], set()) is None
    assert audit.choose_second_observer(SAMPLE, pool[0], pool[0], [pool[0]], set()) is None


# --- draw-sample ---------------------------------------------------------------------------------------------------


def expected_sample(private, quarter=Q4):
    live = [o for o in records.observations(log(private)) if audit.quarter_id(o.at) == quarter]
    return set(rules.audit_sample(live, quarter, STD["rules"]))


def test_the_sample_is_what_rules_audit_sample_picks_for_the_quarter(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store)
    run(fictional_store)
    found = samples(fictional_store)
    want = expected_sample(fictional_store)
    assert len(want) == 6  # 24 observations in the quarter, three observers: the minimum of 2 each
    assert {e["payload"]["attrs"]["observation"] for e in found} == want
    q3 = {o.id for o in records.observations(log(fictional_store)) if audit.quarter_id(o.at) == "2026Q3"}
    assert q3 and not q3 & want  # the earlier quarter is not sampled
    assert {e["subject_uri"] for e in found} == {f"tm:sample/{Q4}--{i}" for i in want}


def test_observations_scored_from_a_recording_are_never_sampled(fictional_store, example_roster):
    # W6 audits live observations: one scored from a recording (W11's from_recording) is already a recording-based score
    store(fictional_store, example_roster)
    many(fictional_store)
    recorded = [obs_event(500 + n, OBSERVERS[n % 3], INSTRUCTOR if OBSERVERS[n % 3] != INSTRUCTOR else K7,
                          f"2026-10-{2 + n:02d}", from_recording=True) for n in range(9)]
    add(fictional_store, *recorded)
    run(fictional_store)
    drawn = {e["payload"]["attrs"]["observation"] for e in samples(fictional_store)}
    assert drawn and not drawn & {e["id"] for e in recorded}
    recorded_ids = {e["id"] for e in recorded}
    live = [o for o in records.observations(log(fictional_store))
            if audit.quarter_id(o.at) == Q4 and o.id not in recorded_ids]
    assert drawn == set(rules.audit_sample(live, Q4, STD["rules"]))


def test_a_sample_subject_has_the_fixed_shape_and_validates(fictional_store, example_roster):
    store(fictional_store, example_roster)
    many(fictional_store)
    run(fictional_store)
    by_id = {o.id: o for o in records.observations(log(fictional_store))}
    for e in samples(fictional_store):
        attrs = e["payload"]["attrs"]
        o = by_id[attrs["observation"]]
        assert set(attrs) == {"observation", "instructor", "observer", "quarter", "second_observer"}
        assert (attrs["instructor"], attrs["observer"], attrs["quarter"]) == (o.instructor, o.observer, Q4)
        assert e["payload"]["opened_by"] == STEP_DRAW and e["actor"] == "tm:system/teachermodel"
        assert events.check_event(e) == []
    assert events.verify(fictional_store / app.EVENT_LOG) == []


def test_second_observers_are_calibrated_clearers_other_than_the_first_observer_the_instructor_and_their_coaches(
        fictional_store, example_roster):
    store(fictional_store, example_roster)
    coach_row(fictional_store, R8, INSTRUCTOR)  # r8 coaches the instructor p3x9d
    set_level(fictional_store, INSTRUCTOR, "clearer")  # the instructor is a clearer too, and calibrated
    calibrate(fictional_store, INSTRUCTOR)
    many(fictional_store)
    run(fictional_store)
    found = samples(fictional_store)
    assert found
    pool = {INSTRUCTOR, K7, C5, R8}
    seen = set()
    for e in found:
        a = e["payload"]["attrs"]
        eligible = pool - {a["observer"], a["instructor"]} - ({R8} if a["instructor"] == INSTRUCTOR else set())
        assert a["second_observer"] in eligible, a
        assert a["second_observer"] == audit.choose_second_observer(e["subject_uri"], a["instructor"], a["observer"], pool,
                                                                      {R8} if a["instructor"] == INSTRUCTOR else set())
        seen.add(a["second_observer"])
    assert len(seen) > 1
    assert any(e["payload"]["attrs"]["instructor"] == INSTRUCTOR for e in found)  # the exclusions were exercised


def test_an_uncalibrated_clearer_is_not_a_second_observer(fictional_store, example_roster):
    store(fictional_store, example_roster, calibrated=("k7m2q", "c5w1t"))  # r8 is a clearer, never calibrated
    many(fictional_store)
    run(fictional_store)
    found = samples(fictional_store)
    assert found and all(e["payload"]["attrs"]["second_observer"] in (K7, C5) for e in found)


def test_nothing_is_drawn_without_observations_and_the_step_is_still_done(fictional_store, example_roster):
    store(fictional_store, example_roster)
    run(fictional_store)
    assert samples(fictional_store) == []
    steps = [e for e in of_kind(fictional_store, "step") if e["payload"].get("step") == STEP_DRAW]
    assert len(steps) == 1 and steps[0]["payload"]["opened"] == []
    assert STEP_DRAW not in {d.step for d in app.due_steps(app.load_state(fictional_store), NOW.date())}


def test_the_draw_is_deterministic(fictional_store, example_roster, tmp_path_factory):
    store(fictional_store, example_roster)
    many(fictional_store)
    run(fictional_store)
    other = tmp_path_factory.mktemp("again") / "private"
    store(other, example_roster)
    many(other)
    run(other)
    assert [(e["subject_uri"], e["payload"]["attrs"]) for e in samples(other)] == \
           [(e["subject_uri"], e["payload"]["attrs"]) for e in samples(fictional_store)]


def test_a_sample_with_no_eligible_second_observer_is_not_opened_and_the_reason_is_recorded(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("k7m2q",))  # one clearer: no second observer for their own observation
    add(fictional_store, obs_event(1, K7, INSTRUCTOR, "2026-10-05"))
    run(fictional_store)
    assert samples(fictional_store) == []
    (blocked,) = [e for e in of_kind(fictional_store, "check") if e["payload"].get("step") == STEP_DRAW]
    assert blocked["payload"]["result"] == "blocked" and blocked["subject_uri"] == PROGRAMME
    run(fictional_store)
    assert len([e for e in of_kind(fictional_store, "check") if e["payload"].get("step") == STEP_DRAW]) == 1
    # a second clearer appears, calibrated: the sample opens on the next run
    set_level(fictional_store, C5, "clearer")
    calibrate(fictional_store, C5)
    run(fictional_store, NOW + timedelta(days=1))
    (found,) = samples(fictional_store)
    assert found["payload"]["attrs"]["second_observer"] == C5


# --- the second-score page -----------------------------------------------------------------------------------------


def page_of(private, sample, st=None):
    st = st or app.load_state(private)
    (spec,) = app._page_specs(st, STEP_SCORE, sample)
    return spec


def test_the_page_is_the_second_observers_and_scores_every_domain(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, event = one_sample(fictional_store)
    attrs = event["payload"]["attrs"]
    spec = page_of(fictional_store, sample)
    assert spec["signer"] == attrs["second_observer"] and spec["role"] == "clearer" and spec["template"] == "approve"
    fields = {f["name"]: f for f in spec["fields"]}
    assert [n for n, f in fields.items() if f["kind"] == "evidence_score"] == DOMAINS
    assert all(fields[d]["required"] for d in DOMAINS)
    assert spec["inputs"]["sample"] == sample and spec["inputs"]["instructor"] == INSTRUCTOR
    page, _ = pagegen.render(**spec, channel={"kind": "mail", "to": "signoffs@example.com"})
    assert "Recording timestamp" in page
    assert [d.step for d in app.due_steps(app.load_state(fictional_store), NOW.date()) if d.subject == sample] == [STEP_SCORE]


def test_the_page_names_the_recording_when_the_assignment_has_one(fictional_store, example_roster):
    store(fictional_store, example_roster)
    assignment = "tm:assignment/0123456789abcdef"
    add(fictional_store, events.make_event(
        "subject", assignment, "tm:system/teachermodel",
        {"subject_kind": "assignment", "opened_by": "tm:step/assignments-approved",
         "attrs": {"candidate": "tm:candidate/p3x9d--example-agent-loop-1--remote", "instructor": INSTRUCTOR,
                   "unit": "sl:unit/example-agent-loop@1", "mode": "remote", "observer": K7, "length": "full", "lead": True,
                   "delivery_ref": "p3x9d-1", "recording_ref": "recordings/fictional-1.mp4"}},
        at="2026-10-05T09:00:00+00:00"))
    sample, _ = one_sample(fictional_store, assignment=assignment, delivery_ref="p3x9d-1")
    inputs = page_of(fictional_store, sample)["inputs"]
    assert inputs["recording_ref"] == "recordings/fictional-1.mp4" and inputs["delivery_ref"] == "p3x9d-1"


def test_the_page_and_its_inputs_never_carry_the_first_observers_scores(fictional_store, example_roster):
    store(fictional_store, example_roster)
    first = {d: s for d, s in zip(DOMAINS, [1, 2, 3, 4, 2])}
    sample, event = one_sample(fictional_store, scores=first, evidence_ref="evidence/ffffffffffffffff.json")
    st = app.load_state(fictional_store)
    spec = page_of(fictional_store, sample, st)
    flat = json.dumps(spec["inputs"])
    attrs = event["payload"]["attrs"]
    for secret in (attrs["observer"], "evidence/ffffffffffffffff.json", "evidence_ref", "scores", json.dumps(first)):
        assert secret not in flat, secret
    # what the page shows does not depend on what the first observer scored
    channel = {"kind": "mail", "to": "signoffs@example.com"}
    page, _ = pagegen.render(**spec, channel=channel)
    changed = [dict(e, payload=dict(e["payload"], scores={d: 4 for d in DOMAINS})) if e["kind"] == "observation" else e
               for e in st.events]
    other = dataclasses.replace(st, events=changed, cache={})
    spec2 = page_of(fictional_store, sample, other)
    assert spec2 == spec and pagegen.render(**spec2, channel=channel)[0] == page


# --- the sign-off: only the second observer ----------------------------------------------------------------------


def tick(private, at=NOW):
    app.do_tick(private, now=at)
    return at


def test_only_the_second_observer_can_sign_and_the_scores_must_be_complete(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, event = one_sample(fictional_store)
    second = event["payload"]["attrs"]["second_observer"]
    other = next(o for o in (K7, C5, R8) if o not in (second, event["payload"]["attrs"]["observer"]))
    tick(fictional_store)
    fields = second_fields()
    page = signoff(fictional_store, STEP_SCORE, sample, second, fields, now=NOW)[0]
    # another clearer signing with the page data of the second observer's page, from their own mailbox
    forged = {**page, "signer": other, "id": "a" * 16}
    rep = ingest(fictional_store, [(forged, email_of(fictional_store, other))], now=NOW)
    assert "1 rejected" in rep.summary and any("second observer" in line for line in rep.lines), rep.all_lines()
    # the first observer, signing their own audit
    first = event["payload"]["attrs"]["observer"]
    rep = ingest(fictional_store, [({**page, "signer": first, "id": "b" * 16}, email_of(fictional_store, first))],
                 now=NOW, name="r2")
    assert any("second observer" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_SCORE) == []
    # an incomplete scoring: a domain missing, a blank note
    short = {k: v for k, v in fields.items() if k != DOMAINS[0]}
    rep = ingest(fictional_store, [signoff(fictional_store, STEP_SCORE, sample, second, short, now=NOW)], now=NOW, name="r3")
    assert "1 rejected" in rep.summary and any(f"domain {DOMAINS[0]}" in line for line in rep.lines), rep.all_lines()
    blank = {**fields, DOMAINS[1]: {"score": 3, "note": "  "}}
    rep = ingest(fictional_store, [signoff(fictional_store, STEP_SCORE, sample, second, blank, now=NOW)], now=NOW, name="r4")
    assert "1 rejected" in rep.summary, rep.all_lines()
    assert signoff_events(fictional_store, STEP_SCORE) == []
    good = ingest(fictional_store, [signoff(fictional_store, STEP_SCORE, sample, second, fields, now=NOW)], now=NOW, name="ok")
    assert "1 signoff" in good.summary and "0 rejected" in good.summary, good.all_lines()


def test_the_second_score_falls_due_fourteen_days_after_the_sample_opens(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, event = one_sample(fictional_store)
    opened = date.fromisoformat(event["at"][:10])
    got = {d.step: d for d in app.due_steps(app.load_state(fictional_store), opened + timedelta(days=3)) if d.subject == sample}
    assert got[STEP_SCORE].due == opened + timedelta(days=14) and not got[STEP_SCORE].overdue
    late = {d.step: d for d in app.due_steps(app.load_state(fictional_store), opened + timedelta(days=15)) if d.subject == sample}
    assert late[STEP_SCORE].overdue
    assert STEP_RESULT not in got  # not before the second score


# --- audit-result --------------------------------------------------------------------------------------------------


def test_no_audit_result_before_the_second_score(fictional_store, example_roster):
    store(fictional_store, example_roster)
    one_sample(fictional_store)
    run(fictional_store, NOW + timedelta(days=1))
    assert audits_of(fictional_store) == []


@pytest.mark.parametrize("second, within, exact, agreed", [
    ([3, 3, 3, 3, 3], 1.0, 1.0, True),
    ([3, 3, 3, 4, 2], 1.0, 0.6, True),     # the exact edge: 3 of 5 equal is 0.6, which meets the threshold
    ([3, 3, 4, 4, 2], 1.0, 0.4, False),    # 2 of 5 equal: below exact
    ([3, 3, 3, 3, 1], 0.8, 0.8, False),    # one score two points away: below within-one (0.9)
    ([1, 1, 1, 1, 1], 0.0, 0.0, False),
])
def test_the_audit_event_carries_the_agreement_and_whether_it_met_the_calibration_thresholds(
        fictional_store, example_roster, second, within, exact, agreed):
    store(fictional_store, example_roster)
    sample, event = one_sample(fictional_store, scores=3)
    attrs = event["payload"]["attrs"]
    signed = score_second(fictional_store, sample, second)
    day = NOW + timedelta(days=2)
    run(fictional_store, day)
    (a,) = audits_of(fictional_store)
    assert events.check_event(a) == [] and a["subject_uri"] == sample and a["at"].startswith(day.date().isoformat())
    assert a["payload"] == {
        "sample": sample, "observation": attrs["observation"], "observer": attrs["observer"],
        "second_observer": attrs["second_observer"], "within_one_share": within, "exact_share": exact, "agreed": agreed,
        "referred_to_calibration": not agreed, "signoff_id": signed["payload"]["signoff_id"]}
    # the shares are rules.calibration_pass's: the same definitions as W5
    verdict = rules.calibration_pass(dict(zip(DOMAINS, second)), {d: 3 for d in DOMAINS}, STD["rules"])
    assert (verdict.detail["within_one"], verdict.detail["exact"], verdict.ok) == (within, exact, agreed)
    steps = [e for e in of_kind(fictional_store, "step") if e["payload"].get("step") == STEP_RESULT]
    assert len(steps) == 1 and steps[0]["subject_uri"] == sample
    checks = [e for e in of_kind(fictional_store, "check") if e["payload"].get("step") == STEP_RESULT]
    if agreed:
        assert checks == []
    else:
        (c,) = checks
        assert c["payload"] == {"step": STEP_RESULT, "result": "refer-to-calibration", "observer": attrs["observer"]}
        assert events.check_event(c) == []
    assert (STEP_RESULT, sample) not in {(d.step, d.subject) for d in app.due_steps(app.load_state(fictional_store), day.date())}
    # neither observer's scores are in the audit event or the check
    text = json.dumps([a, *checks])
    assert "fictional second-scoring note" not in text and '"scores"' not in text


def test_replaying_the_result_appends_nothing(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, _ = one_sample(fictional_store)
    score_second(fictional_store, sample, [1] * 5)
    run(fictional_store, NOW + timedelta(days=2))
    run(fictional_store, NOW + timedelta(days=2))  # the clearance checks react to the referral and settle on this run
    before = (fictional_store / app.EVENT_LOG).read_bytes()
    run(fictional_store, NOW + timedelta(days=2))
    run(fictional_store, NOW + timedelta(days=9))
    assert (fictional_store / app.EVENT_LOG).read_bytes() == before


def test_the_whole_round_trip_through_ingest(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, event = one_sample(fictional_store, scores=3)
    second = event["payload"]["attrs"]["second_observer"]
    tick(fictional_store)
    rep = ingest(fictional_store, [signoff(fictional_store, STEP_SCORE, sample, second, second_fields([3, 3, 4, 4, 2]), now=NOW)],
                 now=NOW)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    run(fictional_store, NOW + timedelta(days=1))
    (a,) = audits_of(fictional_store)
    assert a["payload"]["agreed"] is False and a["payload"]["referred_to_calibration"] is True
    assert (fictional_store / "signoffs" / f"{a['payload']['signoff_id']}.json").is_file()
    assert events.verify(fictional_store / app.EVENT_LOG) == []


# --- records.audits ------------------------------------------------------------------------------------------------


def audit_event(day, observer=K7, referred=False, n=0):
    payload = {"sample": f"tm:sample/{Q4}--{n:016x}", "observation": f"{n:016x}", "observer": observer, "second_observer": C5,
               "within_one_share": 1.0, "exact_share": 1.0, "agreed": not referred, "referred_to_calibration": referred,
               "signoff_id": f"{n + 1:016x}"}
    return events.make_event("audit", payload["sample"], "tm:system/teachermodel", payload, id=f"{n + 1:032x}",
                             at=f"{day}T09:00:00+00:00")


def test_records_audits_reads_audit_events_oldest_first():
    late, early = audit_event("2026-11-02", n=2), audit_event("2026-10-28", n=1)
    other = events.make_event("check", K7, "tm:system/teachermodel", {"step": STEP_RESULT, "result": "refer-to-calibration"})
    got = records.audits([late, other, early])
    assert [a["id"] for a in got] == [early["id"], late["id"]]
    assert got[0]["at"] == date(2026, 10, 28)
    assert {k: v for k, v in got[0].items() if k not in ("id", "at")} == early["payload"]
    assert records.audits([]) == [] and records.audits([other]) == []


# --- the referral: calibration lapses from the day of the audit, prospectively (decision 0015) ----------------------


def calibration_event(observer, day, passed=True):
    payload = {"exercise": "tm:exercise/0123456789abcdef", "observer": observer, "unit": "sl:unit/example-agent-loop@1",
               "rubric_version": "0.2.0", "within_one_share": 1.0, "exact_share": 1.0, "passed": passed,
               "signoff_id": hashlib.sha256(f"{observer}{day}".encode()).hexdigest()[:16]}
    return events.make_event("calibration", observer, "tm:system/teachermodel", payload,
                             id=hashlib.sha256(f"c{observer}{day}".encode()).hexdigest()[:32], at=f"{day}T09:00:00+00:00")


R = STD["rules"]


def calibrated(log_, who, on):
    """rules.is_calibrated over the log's passes and the observer's referral lapses (records.calibrations, records.lapses)."""
    return rules.is_calibrated(who, on, records.calibrations(log_), R, records.lapses(log_).get(who))


def test_a_referral_makes_the_observer_not_calibrated_from_the_day_of_the_audit_until_a_later_pass():
    d = date(2026, 10, 28)
    log_ = [calibration_event(K7, "2026-09-01"), calibration_event(C5, "2026-09-01"), audit_event("2026-10-28", referred=True)]
    assert calibrated(log_[:2], K7, d)  # before the audit is on record: calibrated
    assert not calibrated(log_, K7, d) and not calibrated(log_, K7, d + timedelta(days=30))
    assert calibrated(log_, C5, d)  # nobody else is affected
    # a pass on the day of the audit does not restore it; a later one does, for its own renewal period
    assert not calibrated([*log_, calibration_event(K7, "2026-10-28")], K7, d)
    later = [*log_, calibration_event(K7, "2026-10-29")]
    assert calibrated(later, K7, date(2026, 10, 29)) and calibrated(later, K7, date(2027, 4, 28))
    assert not calibrated(later, K7, date(2027, 4, 29))
    # a failed calibration does not restore it either
    assert not calibrated([*log_, calibration_event(K7, "2026-10-29", passed=False)], K7, date(2026, 10, 30))


def test_a_referral_is_prospective_the_days_before_it_keep_their_calibration():
    log_ = [calibration_event(K7, "2026-09-01"), audit_event("2026-10-28", referred=True)]
    assert calibrated(log_, K7, date(2026, 9, 1)) and calibrated(log_, K7, date(2026, 10, 27))  # before D: unaffected
    assert not calibrated(log_, K7, date(2026, 10, 28))  # from D
    # records.calibrations keeps every pass; the referral is in records.lapses
    assert records.calibrations(log_) == {K7: [date(2026, 9, 1)]}
    assert records.lapses(log_) == {K7: [date(2026, 10, 28)]}


def test_is_calibrated_without_lapses_is_unchanged():
    cals = {K7: [date(2026, 9, 1)]}
    for on in (date(2026, 9, 1), date(2027, 2, 28)):
        assert rules.is_calibrated(K7, on, cals, R) == rules.is_calibrated(K7, on, cals, R, []) is True
    assert rules.is_calibrated(K7, date(2027, 3, 1), cals, R) is False  # six months after 1 September


def test_a_clearance_judged_on_an_observation_dated_before_the_referral_still_counts():
    d = date(2026, 10, 28)
    log_ = [calibration_event(K7, "2026-09-01"), calibration_event(C5, "2026-09-01"), audit_event("2026-10-28", referred=True)]

    def obs(n, observer, day):
        return rules.Observation(f"obs-{n}", INSTRUCTOR, "sl:unit/example-agent-loop@1", observer, day, "full", True,
                                 {dom: 3 for dom in DOMAINS}, "in-person", "0.2.0")

    runs = [rules.DryRun(INSTRUCTOR, "sl:unit/example-agent-loop@1", "in-person", True, date(2026, 9, 20))]

    def verdict(observations):
        return rules.clearance_check(INSTRUCTOR, "sl:unit/example-agent-loop@1", "in-person", observations, runs,
                                     records.calibrations(log_), set(), list(DOMAINS), R, lapses=records.lapses(log_))

    before = verdict([obs(1, K7, d - timedelta(days=10)), obs(2, C5, d - timedelta(days=5))])
    assert before.ok, before.reasons
    assert sorted(before.detail["observations"]) == ["obs-1", "obs-2"]
    after = verdict([obs(1, K7, d), obs(2, C5, d - timedelta(days=5))])  # K7 observed on the day of the referral
    assert not after.ok and after.detail["observations"] == ["obs-2"]
    # without the lapses the same observation would have counted: the lapses are what keeps it out
    assert rules.clearance_check(INSTRUCTOR, "sl:unit/example-agent-loop@1", "in-person", [obs(1, K7, d)], runs,
                                 records.calibrations(log_), set(), list(DOMAINS), R).detail["observations"] == ["obs-1"]


def test_a_referral_brings_the_calibration_renewal_forward_to_the_audit_day():
    from teachermodel import due

    renewal = due.resolve("clearer_renewal")
    log_ = [calibration_event(K7, "2026-09-01")]
    assert renewal({}, K7, {"kind": "instructor"}, log_, date(2026, 10, 1)) == date(2027, 3, 1)
    referred = [*log_, audit_event("2026-10-28", referred=True)]
    assert renewal({}, K7, {"kind": "instructor"}, referred, date(2026, 10, 28)) == date(2026, 10, 28)
    # a pass after the referral sets the usual renewal again
    renewed = [*referred, calibration_event(K7, "2026-11-02")]
    assert renewal({}, K7, {"kind": "instructor"}, renewed, date(2026, 11, 2)) == date(2027, 5, 2)


def test_an_audit_that_agreed_leaves_the_calibration_alone():
    log_ = [calibration_event(K7, "2026-09-01"), audit_event("2026-10-28", referred=False)]
    assert records.calibrations(log_) == {K7: [date(2026, 9, 1)]}
    assert records.lapses(log_) == {}
    assert calibrated(log_, K7, date(2026, 11, 1))


def test_each_referral_lapses_until_the_next_pass_after_it():
    log_ = [calibration_event(K7, "2026-09-01"), audit_event("2026-10-28", referred=True, n=1),
            calibration_event(K7, "2026-11-01"), audit_event("2026-12-01", referred=True, n=2),
            calibration_event(K7, "2026-12-15")]
    assert records.lapses(log_) == {K7: [date(2026, 10, 28), date(2026, 12, 1)]}
    assert calibrated(log_, K7, date(2026, 10, 27))
    assert not calibrated(log_, K7, date(2026, 10, 31))
    assert calibrated(log_, K7, date(2026, 11, 1)) and calibrated(log_, K7, date(2026, 11, 30))
    assert not calibrated(log_, K7, date(2026, 12, 1)) and not calibrated(log_, K7, date(2026, 12, 14))
    assert calibrated(log_, K7, date(2026, 12, 15))


def test_records_calibrations_is_unchanged_without_audits():
    log_ = [calibration_event(K7, "2026-09-01"), calibration_event(K7, "2026-03-01"), calibration_event(C5, "2026-09-02", passed=False)]
    assert records.calibrations(log_) == {K7: [date(2026, 3, 1), date(2026, 9, 1)]}
    assert records.calibrations(iter(log_)) == {K7: [date(2026, 3, 1), date(2026, 9, 1)]}  # any iterable of events
    assert records.lapses(iter(log_)) == {}


def test_a_referred_observer_leaves_the_observer_pool_until_they_pass_again(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, event = one_sample(fictional_store, scores=3)
    first = event["payload"]["attrs"]["observer"]
    score_second(fictional_store, sample, [1] * 5)
    day = NOW + timedelta(days=2)
    run(fictional_store, day)
    st = app.load_state(fictional_store)
    assert first not in flows.common.observer_pool(st, day.date())
    assert first not in flows.common.observer_pool(st, day.date() + timedelta(days=60))
    calibrate(fictional_store, first, at="2026-10-29T09:00:00+00:00")
    st = app.load_state(fictional_store)
    assert first in flows.common.observer_pool(st, date(2026, 10, 30))


# --- the second observer is re-checked when they sign (decision 0015, appended 2026-10-25) --------------------------

from test_clearance import reasons as signing_reasons  # noqa: E402


def sample_and_second(private, **kw):
    sample, event = one_sample(private, **kw)
    return sample, event["payload"]["attrs"]["second_observer"], event


def void_checks(private):
    return [e for e in of_kind(private, "check") if e["payload"].get("step") == STEP_DRAW and e["payload"].get("result") == "void"]


def stop_coaching(private, coach):
    path = private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for row in doc["people"]:
        if row["roles"] == ["coach"] and row["instructor"] == coach:
            row["coaches"] = []
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")


def test_a_second_observer_who_has_since_become_the_instructors_coach_is_refused_at_signing(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, second, _ = sample_and_second(fictional_store)
    assert signing_reasons(fictional_store, STEP_SCORE, second, second_fields(), subject=sample) == []
    coach_row(fictional_store, second, INSTRUCTOR)  # from now on the second observer coaches the instructor
    found = signing_reasons(fictional_store, STEP_SCORE, second, second_fields(), subject=sample)
    assert found and any("coach" in r for r in found), found


def test_a_second_observer_who_coaches_someone_else_is_still_eligible(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, second, _ = sample_and_second(fictional_store)
    other = next(i for i in ALL if i not in (second, INSTRUCTOR))
    coach_row(fictional_store, second, other)
    assert signing_reasons(fictional_store, STEP_SCORE, second, second_fields(), subject=sample) == []


def test_a_second_observer_who_is_no_longer_calibrated_on_the_signing_day_is_refused(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, second, _ = sample_and_second(fictional_store)
    # the calibration of 2026-09-01 lapses six months later: still valid on 2027-02-28, not on 2027-03-01
    assert signing_reasons(fictional_store, STEP_SCORE, second, second_fields(), subject=sample,
                           at="2027-02-28T09:00:00+00:00") == []
    found = signing_reasons(fictional_store, STEP_SCORE, second, second_fields(), subject=sample, at="2027-03-01T09:00:00+00:00")
    assert any("calibrated" in r for r in found), found


def test_a_second_observer_who_has_dropped_below_clearer_is_refused(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, second, _ = sample_and_second(fictional_store)
    set_level(fictional_store, second, "cleared", at="2026-10-26T09:00:00+00:00")
    found = signing_reasons(fictional_store, STEP_SCORE, second, second_fields(), subject=sample)
    assert any("calibrated clearer" in r for r in found), found


def test_a_refused_sign_off_leaves_the_sample_open_and_ingest_says_why(fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, second, _ = sample_and_second(fictional_store)
    tick(fictional_store)
    coach_row(fictional_store, second, INSTRUCTOR)
    rep = ingest(fictional_store, [signoff(fictional_store, STEP_SCORE, sample, second, second_fields(), now=NOW)], now=NOW)
    assert "1 rejected" in rep.summary and any("coach" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_SCORE) == [] and audits_of(fictional_store) == []


def sampled_world(private, roster):
    """K7 made three observations in the quarter: two are sampled (the minimum), one is left over for a replacement."""
    store(private, roster)
    add(private, *[obs_event(2000 + n, K7, INSTRUCTOR, f"2026-10-{10 + n:02d}") for n in range(3)])
    run(private)
    found = samples(private)
    assert len(found) == 2
    return found


def test_draw_sample_voids_a_sample_whose_second_observer_is_no_longer_eligible_and_draws_a_replacement(
        fictional_store, example_roster):
    found = sampled_world(fictional_store, example_roster)
    victim = found[0]
    second = victim["payload"]["attrs"]["second_observer"]
    coach_row(fictional_store, second, INSTRUCTOR)
    run(fictional_store, NOW + timedelta(days=1))
    (void,) = void_checks(fictional_store)
    assert void["subject_uri"] in {e["subject_uri"] for e in found} and events.check_event(void) == []
    assert void["payload"]["result"] == "void" and any("coach" in r for r in void["payload"]["reasons"])
    voided = void["subject_uri"]
    # the voided sample is closed: its second-score is skipped, its audit-result is closed, and nothing is due for it
    assert {d.step for d in app.due_steps(app.load_state(fictional_store), (NOW + timedelta(days=1)).date())
            if d.subject == voided} == set()
    assert audits_of(fictional_store) == []
    # the sample was withdrawn from the observer's quota, so the third observation takes its place in the same quarter
    now_open = [e for e in samples(fictional_store) if e["subject_uri"] != voided]
    assert len(now_open) == 2
    drawn = {e["payload"]["attrs"]["observation"] for e in now_open}
    voided_obs = next(e for e in found if e["subject_uri"] == voided)["payload"]["attrs"]["observation"]
    assert voided_obs not in drawn and len(drawn) == 2
    replacement = next(e for e in now_open if e["subject_uri"] not in {f["subject_uri"] for f in found})
    assert replacement["payload"]["attrs"]["second_observer"] != second  # the coach of the instructor is never chosen


def test_the_voided_observation_is_not_drawn_again_and_a_void_is_said_once(fictional_store, example_roster):
    found = sampled_world(fictional_store, example_roster)
    coach_row(fictional_store, found[0]["payload"]["attrs"]["second_observer"], INSTRUCTOR)
    run(fictional_store, NOW + timedelta(days=1))
    run(fictional_store, NOW + timedelta(days=2))
    run(fictional_store, NOW + timedelta(days=40))
    (void,) = void_checks(fictional_store)
    voided_obs = void["subject_uri"].split("--", 1)[1]
    assert len([e for e in samples(fictional_store) if e["payload"]["attrs"]["observation"] == voided_obs]) == 1
    assert len(void_checks(fictional_store)) == 1


def test_a_second_run_after_a_void_appends_nothing(fictional_store, example_roster):
    found = sampled_world(fictional_store, example_roster)
    coach_row(fictional_store, found[0]["payload"]["attrs"]["second_observer"], INSTRUCTOR)
    run(fictional_store, NOW + timedelta(days=1))
    run(fictional_store, NOW + timedelta(days=1))
    before = (fictional_store / app.EVENT_LOG).read_bytes()
    run(fictional_store, NOW + timedelta(days=1))
    assert (fictional_store / app.EVENT_LOG).read_bytes() == before


def test_a_void_closes_the_second_score_with_a_skip_that_covers_its_inputs(fictional_store, example_roster):
    found = sampled_world(fictional_store, example_roster)
    coach_row(fictional_store, found[0]["payload"]["attrs"]["second_observer"], INSTRUCTOR)
    run(fictional_store, NOW + timedelta(days=1))
    (void,) = void_checks(fictional_store)
    uri = void["subject_uri"]
    (skip,) = [e for e in of_kind(fictional_store, "step")
               if e["subject_uri"] == uri and e["payload"].get("step") == STEP_SCORE]
    st = app.load_state(fictional_store)
    assert skip["payload"]["skipped"] is True and skip["actor"] == "tm:system/teachermodel"
    assert skip["payload"]["input_sha256"] == app._current_input_reader(st)(STEP_SCORE, uri)
    (closing,) = [e for e in of_kind(fictional_store, "step") if e["subject_uri"] == uri and e["payload"].get("step") == STEP_RESULT]
    assert closing["payload"]["void"] is True and "agreed" not in closing["payload"]


def test_the_second_score_step_can_be_skipped_and_is_bound_to_its_inputs():
    (score,) = [s for s in wf()["steps"] if s["id"] == STEP_SCORE]
    assert score["done_when"]["bind"] == "input" and score["done_when"]["skippable"] is True


def test_a_sample_already_second_scored_is_not_voided_even_if_the_second_observer_changes_afterwards(
        fictional_store, example_roster):
    store(fictional_store, example_roster)
    sample, second, _ = sample_and_second(fictional_store)
    score_second(fictional_store, sample, [3] * 5)
    coach_row(fictional_store, second, INSTRUCTOR)
    run(fictional_store, NOW + timedelta(days=2))
    assert void_checks(fictional_store) == []
    assert len(audits_of(fictional_store)) == 1


def test_a_voided_sample_cannot_be_signed_even_if_the_second_observer_is_eligible_again(fictional_store, example_roster):
    found = sampled_world(fictional_store, example_roster)
    victim = found[0]
    second = victim["payload"]["attrs"]["second_observer"]
    coach_row(fictional_store, second, INSTRUCTOR)
    run(fictional_store, NOW + timedelta(days=1))
    stop_coaching(fictional_store, second)  # eligible again, but the sample was voided
    st = app.load_state(fictional_store)
    document = {"decision": "approve", "step": STEP_SCORE, "subject_uri": victim["subject_uri"], "signer": second,
                "fields": second_fields(), "signed_at": "2027-01-05T09:00:00+00:00"}
    assert any("voided" in r for r in flows.content_reasons(st, document))


def test_a_void_with_no_other_observation_to_draw_leaves_no_replacement(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("k7m2q", "c5w1t"))  # two clearers: K7's sample is C5's to second-score
    sample, second, _ = sample_and_second(fictional_store)
    assert second == C5
    coach_row(fictional_store, C5, INSTRUCTOR)
    run(fictional_store, NOW + timedelta(days=1))
    (void,) = void_checks(fictional_store)
    assert void["subject_uri"] == sample
    assert len(samples(fictional_store)) == 1  # no other observation exists to take its place
