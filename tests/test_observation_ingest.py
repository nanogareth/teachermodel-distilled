"""W2 and the people-to-instructor mapping through the real mail round trip: pages -> receipt -> ingest -> hooks -> release.

The signer of `observe` is the assigned observer, of `self-assessment` the instructor observed (`signer` on the step,
decision 0012); a clearer is a roster instructor at level clearer, or one a people-list person holding that role is mapped
to. Fictional people only.
"""

from datetime import timedelta

import pytest
import yaml
from ingest_helpers import email_of, ingest, signoff, signoff_events
from test_observation import (
    CANDIDATE,
    COORD,
    DOMAINS,
    INSTRUCTOR,
    NOTE,
    R8,
    STEP_APPROVED,
    STEP_OBSERVE,
    STEP_SELF,
    T0,
    assignments,
    due_ids,
    observe_fields,
    of_kind,
    proposal,
    store,
)

from teachermodel import app, records
from teachermodel.flows import observation
from teachermodel.signoff import input_sha256

DAY = "2026-10-26"  # the session; not after the sign-off


def tick(private, at=T0):
    app.do_tick(private, now=at)
    return at


def approve_through_ingest(private, at=T0):
    tick(private, at)
    rows = {r["key"]: "approve" for r in proposal(private)["rows"]}
    rep = ingest(private, [signoff(private, STEP_APPROVED, CANDIDATE, COORD, {"rows": rows}, now=at)], now=at)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    return assignments(private)


def observe(private, assignment, *, at, fields=None, sender=None, signer=None):
    observer = assignment["payload"]["attrs"]["observer"]
    return signoff(private, STEP_OBSERVE, assignment["subject_uri"], signer or observer,
                   fields or observe_fields(3, day=DAY), now=at, sender=sender)


def test_the_batch_approval_opens_the_assignments_through_ingest(fictional_store, example_roster):
    store(fictional_store, example_roster)
    found = approve_through_ingest(fictional_store)
    assert len(found) == 2 and len({a["payload"]["attrs"]["observer"] for a in found}) == 2
    assert (STEP_APPROVED, CANDIDATE) not in due_ids(fictional_store)


def test_a_batch_approval_that_does_not_cover_the_proposed_rows_is_rejected(fictional_store, example_roster):
    store(fictional_store, example_roster)
    tick(fictional_store)
    rows = {r["key"]: "approve" for r in proposal(fictional_store)["rows"]}
    short = dict(list(rows.items())[:1])
    rep = ingest(fictional_store, [signoff(fictional_store, STEP_APPROVED, CANDIDATE, COORD, {"rows": short}, now=T0)], now=T0)
    assert "1 rejected" in rep.summary and any("do not match the rows" in line for line in rep.lines), rep.all_lines()
    rep = ingest(fictional_store, [signoff(fictional_store, STEP_APPROVED, CANDIDATE, COORD,
                                           {"rows": {**rows, "tm:assignment/ffffffffffffffff": "approve"}}, now=T0)],
                 now=T0, name="r2")
    assert "1 rejected" in rep.summary, rep.all_lines()
    rejected_one = {k: ("reject" if i == 0 else v) for i, (k, v) in enumerate(rows.items())}
    rep = ingest(fictional_store, [signoff(fictional_store, STEP_APPROVED, CANDIDATE, COORD, {"rows": rejected_one}, now=T0)],
                 now=T0, name="r3")
    assert any("not all approved" in line for line in rep.lines), rep.all_lines()
    assert assignments(fictional_store) == [] and (STEP_APPROVED, CANDIDATE) in due_ids(fictional_store)


def test_observers_and_the_instructor_sign_through_ingest_blind_until_both_have_observed(fictional_store, example_roster):
    store(fictional_store, example_roster)
    a, b = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    rep = ingest(fictional_store, [observe(fictional_store, a, at=at)], now=at, name="o1")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    app.do_run(fictional_store, now=at + timedelta(hours=3))
    assert of_kind(fictional_store, "observation") == []  # blind: the second observer has not submitted
    assert (fictional_store / observation.evidence_key(a["subject_uri"])).is_file()  # the notes are kept privately
    assert NOTE.split()[0] not in (fictional_store / app.EVENT_LOG).read_text(encoding="utf-8")

    later = at + timedelta(days=1)
    tick(fictional_store, later)
    rep = ingest(fictional_store, [
        observe(fictional_store, b, at=later, fields=observe_fields(2, day=DAY)),
        signoff(fictional_store, STEP_SELF, a["subject_uri"], INSTRUCTOR, {d: 3 for d in DOMAINS}, now=later),
    ], now=later, name="o2")
    assert "2 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    app.do_run(fictional_store, now=later + timedelta(hours=3))
    released = records.observations(app.read_events(fictional_store))
    assert len(released) == 2 and {o.instructor for o in released} == {INSTRUCTOR}
    assert {o.observer for o in released} == {x["payload"]["attrs"]["observer"] for x in (a, b)}
    assert (STEP_SELF, a["subject_uri"]) not in due_ids(fictional_store, later)


@pytest.mark.parametrize("damage", ["missing domain", "score out of range", "no note", "blank note", "bad length"])
def test_an_observe_signoff_with_unusable_scores_is_rejected_at_ingest_and_the_step_stays_open(
        fictional_store, example_roster, damage):
    store(fictional_store, example_roster)
    a, _ = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    fields = observe_fields(3, day=DAY)
    first = DOMAINS[0]
    if damage == "missing domain":
        del fields[first]
    elif damage == "score out of range":
        fields[first] = {"score": 5, "note": "fictional"}
    elif damage == "no note":
        fields[first] = {"score": 3}
    elif damage == "blank note":
        fields[first] = {"score": 3, "note": "   "}
    else:
        fields["length"] = "medium"
    stored = sorted((fictional_store / "signoffs").glob("*.json"))
    rep = ingest(fictional_store, [observe(fictional_store, a, at=at, fields=fields)], now=at)
    assert "1 rejected" in rep.summary and "0 signoff" not in rep.summary, rep.all_lines()
    assert any(f"domain {first}" in line or "length:" in line for line in rep.lines), rep.all_lines()  # the content rule
    assert signoff_events(fictional_store, STEP_OBSERVE) == []
    assert sorted((fictional_store / "signoffs").glob("*.json")) == stored  # the rejected sign-off was not stored
    assert (STEP_OBSERVE, a["subject_uri"]) in due_ids(fictional_store, at)
    # the reason names the field, never the answer
    assert all("fictional" not in line for line in rep.lines)
    good = ingest(fictional_store, [observe(fictional_store, a, at=at)], now=at, name="good")
    assert "1 signoff" in good.summary and "0 rejected" in good.summary, good.all_lines()


def test_only_the_assigned_observer_can_sign_observe(fictional_store, example_roster):
    store(fictional_store, example_roster)
    a, b = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    observer_a, observer_b = (x["payload"]["attrs"]["observer"] for x in (a, b))
    # the other observer, signing a's assignment with a's page data: a clearer, but not the one assigned
    data = observe(fictional_store, a, at=at)[0]
    forged = {**data, "signer": observer_b, "id": "a" * 16}
    rep = ingest(fictional_store, [(forged, email_of(fictional_store, observer_b))], now=at)
    assert any("not an expected signer" in line for line in rep.lines), rep.all_lines()
    # the instructor observed signing the observation of their own delivery
    forged = {**data, "signer": INSTRUCTOR, "id": "b" * 16}
    rep = ingest(fictional_store, [(forged, email_of(fictional_store, INSTRUCTOR))], now=at, name="r2")
    assert any("not an expected signer" in line for line in rep.lines), rep.all_lines()
    # the assigned observer's name, sent from someone else's mailbox
    rep = ingest(fictional_store, [(data, email_of(fictional_store, observer_b))], now=at, name="r3")
    assert any("not the named signer" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_OBSERVE) == []
    assert observer_a != observer_b


def test_only_the_instructor_observed_can_sign_the_self_assessment(fictional_store, example_roster):
    store(fictional_store, example_roster)
    a, _ = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    observer = a["payload"]["attrs"]["observer"]
    fields = {d: 3 for d in DOMAINS}
    page = signoff(fictional_store, STEP_SELF, a["subject_uri"], INSTRUCTOR, fields, now=at)[0]
    rep = ingest(fictional_store, [({**page, "signer": observer, "id": "c" * 16}, email_of(fictional_store, observer))], now=at)
    assert any("not an expected signer" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_SELF) == []
    rep = ingest(fictional_store, [(page, email_of(fictional_store, INSTRUCTOR))], now=at, name="ok")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()


def test_a_person_mapped_to_an_instructor_signs_as_that_instructor(fictional_store, example_roster):
    # r8n4h is a clearer by level and calibrated; the mapping lets a person sign as them from the person's own mailbox
    store(fictional_store, example_roster, clearers=("c5w1t", "r8n4h"), run=False)
    path = fictional_store / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/obs-9", "name": "Ola Observer", "email": "ola.observer@example.com",
                          "roles": ["clearer"], "instructor": R8})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    app.do_run(fictional_store, now=T0)
    a, b = approve_through_ingest(fictional_store)
    mapped = next(x for x in (a, b) if x["payload"]["attrs"]["observer"] == R8)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    rep = ingest(fictional_store, [observe(fictional_store, mapped, at=at, sender="ola.observer@example.com")], now=at)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    (event,) = signoff_events(fictional_store, STEP_OBSERVE)
    assert event["actor"] == R8 and "ola.observer" not in (fictional_store / app.EVENT_LOG).read_text(encoding="utf-8")


def test_a_people_list_clearer_mapped_to_a_non_clearer_cannot_sign_as_a_clearer(fictional_store, example_roster):
    # integration review finding 5: the role in the people list is not clearer status
    store(fictional_store, example_roster, clearers=("c5w1t", "k7m2q"), run=False)
    path = fictional_store / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/obs-9", "name": "Ola Observer", "email": "ola.observer@example.com",
                          "roles": ["clearer"], "instructor": R8})  # R8 is not a clearer by level
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    app.do_run(fictional_store, now=T0)
    a, _ = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    forged = {**observe(fictional_store, a, at=at)[0], "signer": R8, "id": "f" * 16}
    rep = ingest(fictional_store, [(forged, "ola.observer@example.com")], now=at)
    assert any("not an expected signer" in line or "lacks role" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_OBSERVE) == []


# --- when a sign-off was signed, and the session date (integration review finding 1) ---------------------------------


def test_a_backdated_observe_signoff_is_rejected_at_ingest(fictional_store, example_roster):
    store(fictional_store, example_roster)
    a, b = approve_through_ingest(fictional_store)  # the assignments opened on 2026-10-26
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    page = observe(fictional_store, a, at=at)[0]
    backdated = {**page, "signed_at": "2026-10-03T09:00:00+00:00", "id": "1" * 16}
    rep = ingest(fictional_store, [(backdated, email_of(fictional_store, a["payload"]["attrs"]["observer"]))], now=at)
    assert "1 rejected" in rep.summary and any("signed_at is before the step opened" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_OBSERVE) == []
    assert not (fictional_store / "signoffs" / f"{'1' * 16}.json").exists()
    # stamped on the day the assignment opened, the same document counts
    on_the_day = {**page, "signed_at": "2026-10-26T09:00:00+00:00", "id": "2" * 16}
    rep = ingest(fictional_store, [(on_the_day, email_of(fictional_store, a["payload"]["attrs"]["observer"]))], now=at, name="r2")
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()


def test_ingest_gives_the_content_checks_its_clock(fictional_store, example_roster, registries):
    store(fictional_store, example_roster)
    a, _ = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    seen = []
    registries.CONTENT_CHECKS.setdefault(STEP_OBSERVE, []).append(
        lambda st, document: (seen.append(st.cache.get("now")), [])[1])
    ingest(fictional_store, [observe(fictional_store, a, at=at)], now=at)
    assert seen and set(seen) == {at + timedelta(minutes=90)}  # the helper ingests 90 minutes after `now`


def test_a_sign_off_stamped_in_the_future_is_rejected_at_ingest(fictional_store, example_roster):
    store(fictional_store, example_roster)
    a, _ = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    page = observe(fictional_store, a, at=at)[0]
    # ingest runs at `at` + 90 minutes: more than a day later than that is the future
    future = {**page, "signed_at": (at + timedelta(days=2)).isoformat(timespec="seconds"), "id": "3" * 16}
    rep = ingest(fictional_store, [(future, email_of(fictional_store, a["payload"]["attrs"]["observer"]))], now=at)
    assert any("signed_at is in the future" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_OBSERVE) == []


def test_a_session_dated_before_the_assignment_opened_is_rejected_at_ingest(fictional_store, example_roster):
    store(fictional_store, example_roster)
    a, _ = approve_through_ingest(fictional_store)  # opened on 2026-10-26
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    rep = ingest(fictional_store, [observe(fictional_store, a, at=at, fields=observe_fields(3, day="2026-10-20"))], now=at)
    assert "1 rejected" in rep.summary and any("before the assignment was opened" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store, STEP_OBSERVE) == []


def test_the_app_derives_the_opening_day_of_a_child_subject_from_its_subject_event(fictional_store, example_roster):
    store(fictional_store, example_roster)
    st = app.load_state(fictional_store)
    assert app._opened_on_reader(st)("tm:step/propose-observations", CANDIDATE) == T0.date()
    a, _ = approve_through_ingest(fictional_store)
    later = app._opened_on_reader(app.load_state(fictional_store))
    assert later("tm:step/observe", a["subject_uri"]) == T0.date()  # the day the assignment was opened (ingest ran then)
    assert later("tm:step/observe", "tm:assignment/ffffffffffffffff") is None  # an unknown subject has no day


def test_the_second_observers_page_is_byte_identical_before_and_after_the_first_submits(fictional_store, example_roster):
    # blindness (finding 11): what the log shows of the first observer's sign-off must not change what the second sees
    store(fictional_store, example_roster)
    a, b = approve_through_ingest(fictional_store)
    at = T0 + timedelta(days=1)
    tick(fictional_store, at)
    second = b["payload"]["attrs"]["observer"]
    stem = app.page_stem(STEP_OBSERVE, b["subject_uri"], second)
    before = {p.name: p.read_bytes() for p in (fictional_store / "pages").glob(f"{stem}*")}
    assert before and any(name.endswith(".html") for name in before) and any(name.endswith(".input.json") for name in before)
    rep = ingest(fictional_store, [observe(fictional_store, a, at=at)], now=at)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    app.do_pages(fictional_store, now=at + timedelta(hours=2))
    after = {p.name: p.read_bytes() for p in (fictional_store / "pages").glob(f"{stem}*")}
    assert after == before
    # the logged hash of the first observer's fields is not a bare hash of them: it carries the sign-off id as a salt
    (first_event,) = signoff_events(fictional_store, STEP_OBSERVE)
    assert first_event["payload"]["fields_sha256"] != input_sha256(observe_fields(3, day=DAY))


def test_a_slug_in_common_does_not_make_a_person_an_instructor(fictional_store, example_roster):
    store(fictional_store, example_roster, clearers=("c5w1t",), run=False)
    path = fictional_store / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append({"person": "tm:person/r8n4h", "name": "Ola Observer", "email": "ola.observer@example.com",
                          "roles": ["clearer"]})  # same slug as the instructor, no mapping
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert observation.clearers(app.load_state(fictional_store)) == ["tm:instructor/c5w1t"]
